"""Walk-forward parameter sweep: rank override combinations on a train period, re-test the top K out of sample.

Every combination runs replay.run_backtest in memory (no DB rows) on candles preloaded once per worker process.
"""
import itertools
import json
import math
import os
import random
import resource
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from multiprocessing import get_context
from pathlib import Path

import yaml

from tradalgo.backtest import replay
from tradalgo.backtest.replay import BacktestSink, run_backtest
from tradalgo.config import Settings, settings_with_overrides
from tradalgo.data.base import INDEX_SYMBOL, empty_candles
from tradalgo.data.candle_cache import CandleCache
from tradalgo.data.universe import Constituent

DEFAULT_TRAIN = (date(2025, 10, 15), date(2026, 4, 30))
DEFAULT_TEST = (date(2026, 5, 1), date(2026, 9, 11))
OVERFIT_DECAY_R = 0.3
GATE_MIN_TRADES = 100
GATE_DD_MULT = 5


@dataclass
class Grid:
    overrides: dict
    max_combinations: int = 200
    seed: int = 0
    min_train_trades: int = 40
    top_k: int = 10
    drawdown_penalty: float = 0.02


@dataclass
class ComboResult:
    index: int
    overrides: dict
    train: dict
    score: float | None = None
    test: dict | None = None
    overfit: bool = False
    passes_gate: bool = False


@dataclass
class SweepResult:
    grid: Grid
    train: tuple[date, date]
    test: tuple[date, date]
    total_combinations: int
    combos: list[ComboResult]
    top: list[ComboResult] = field(default_factory=list)
    peak_rss_mb: float = 0.0

    @property
    def passing(self) -> list[ComboResult]:
        return [c for c in self.top if c.passes_gate]

    @property
    def best(self) -> ComboResult | None:
        return self.passing[0] if self.passing else None


def load_grid(path: str | Path, max_combinations: int | None = None) -> Grid:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    unknown = set(raw) - {"overrides", "max_combinations", "seed", "min_train_trades", "top_k", "drawdown_penalty"}
    if unknown:
        raise ValueError(f"unknown grid keys {sorted(unknown)}")
    if not isinstance(raw.get("overrides"), dict) or not raw["overrides"]:
        raise ValueError("grid needs a non-empty 'overrides:' mapping")
    grid = Grid(**raw)
    if max_combinations is not None:
        grid.max_combinations = max_combinations
    return grid


def _leaves(tree: dict, prefix: tuple = ()) -> list[tuple[tuple, list]]:
    out = []
    for key, value in tree.items():
        path = prefix + (key,)
        if isinstance(value, dict):
            out += _leaves(value, path)
        else:
            out.append((path, value if isinstance(value, list) else [value]))
    return out


def _nest(pairs) -> dict:
    out: dict = {}
    for path, value in pairs:
        node = out
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = value
    return out


def expand_grid(grid: Grid) -> tuple[int, list[dict]]:
    """(size of the full product, the combinations to run); a random seeded sample when over max_combinations."""
    leaves = _leaves(grid.overrides)
    for path, values in leaves:
        if not values:
            raise ValueError(f"grid key {'.'.join(map(str, path))!r} has no candidate values")
    sizes = [len(v) for _, v in leaves]
    total = math.prod(sizes)
    if total <= grid.max_combinations:
        picks = itertools.product(*(range(n) for n in sizes))
    else:
        chosen = sorted(random.Random(grid.seed).sample(range(total), grid.max_combinations))
        picks = (_unrank(i, sizes) for i in chosen)
    combos = [_nest((path, values[j]) for (path, values), j in zip(leaves, pick)) for pick in picks]
    return total, combos


def _unrank(i: int, sizes: list[int]) -> tuple[int, ...]:
    out = []
    for n in reversed(sizes):
        i, r = divmod(i, n)
        out.append(r)
    return tuple(reversed(out))


def validate_combos(settings: Settings, combos: list[dict]) -> None:
    for combo in combos:
        try:
            settings_with_overrides(settings, combo)
        except ValueError as exc:
            raise ValueError(f"invalid grid combination {combo}: {exc}") from exc


def check_split(train: tuple[date, date], test: tuple[date, date]) -> None:
    for name, (start, end) in (("train", train), ("test", test)):
        if start > end:
            raise ValueError(f"{name} range {start}..{end} ends before it starts")
    if train[0] <= test[1] and test[0] <= train[1]:
        raise ValueError(f"train {train[0]}..{train[1]} and test {test[0]}..{test[1]} overlap")


def default_workers() -> int:
    # each worker holds its own preloaded candles, so cap the fan-out for smaller-RAM machines
    return max(1, min((os.cpu_count() or 2) - 1, 4))


def _peak_rss_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(rss / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)  # bytes on macOS, KiB on Linux


def _header(grid: Grid, train, test) -> dict:
    return json.loads(json.dumps({"type": "header", "grid": asdict(grid), "train": list(train), "test": list(test)},
                                 default=str))


def _load_checkpoint(path: Path, header: dict) -> list[dict]:
    lines = []
    for line in path.read_text().splitlines():
        try:
            lines.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a line cut off by the interruption
    if not lines or lines[0].get("type") != "header":
        raise ValueError(f"{path} is not a sweep checkpoint")
    if lines[0] != header:
        raise ValueError(f"checkpoint {path} does not match this grid/split")
    return [entry for entry in lines[1:] if entry.get("type") == "result"]


def score(train: dict, grid: Grid) -> float | None:
    if train["trades"] < grid.min_train_trades:
        return None
    return round(train["expectancy_r"] - grid.drawdown_penalty * train["max_drawdown_r"], 4)


def is_overfit(train: dict, test: dict) -> bool:
    return (test["expectancy_r"] < 0 < train["expectancy_r"]) or \
        (train["expectancy_r"] - test["expectancy_r"] > OVERFIT_DECAY_R)


def passes_gate(settings: Settings, train: dict, test: dict) -> bool:
    return (test["expectancy_r"] > 0 and train["trades"] + test["trades"] >= GATE_MIN_TRADES
            and test["max_drawdown_r"] <= settings.capital.daily_loss_limit_r * GATE_DD_MULT)


class PreloadedCache:
    """CandleCache.load over frames held in memory, so each combination skips parquet reads."""

    def __init__(self, frames: dict):
        self.frames = frames

    def load(self, symbol, resolution):
        return self.frames.get((symbol, resolution), empty_candles())


def preload(cache_root: Path, symbols: list[str]) -> PreloadedCache:
    from tradalgo.jobs.backtest_worker import _CacheOnlyProvider
    cache = CandleCache(cache_root, _CacheOnlyProvider())
    return PreloadedCache({(s, r): cache.load(s, r) for s in symbols + [INDEX_SYMBOL] for r in ("1d", "5m")})


class MemorySink(BacktestSink):
    """BacktestSink behaviour without any DB writes."""

    record_legs = False

    def __init__(self, engine, run_id, broker, frames):
        super().__init__(None, run_id, broker, frames)
        self._ids = itertools.count(1)

    def record_signal(self, signal) -> int:
        return next(self._ids)

    def record_decision(self, signal_id, decision) -> None:
        pass

    def _store(self, r: dict) -> None:
        self.records.append(r)


_WORKER: dict = {}
_SHORTLISTS: dict = {}
_ORIGINAL_SHORTLIST = _uncached_shortlist = replay.backtest_shortlist


def cached_shortlist(settings, daily, index_daily, universe, day):
    """The shortlist depends only on screener settings, universe and day, so combos share it (~14% of a run)."""
    key = (settings.screener.model_dump_json(), tuple(c.symbol for c in universe), day)
    if key not in _SHORTLISTS:
        _SHORTLISTS[key] = _uncached_shortlist(settings, daily, index_daily, universe, day)
    return _SHORTLISTS[key]


def _init_worker(settings, cache_root, universe, kwargs):
    replay.backtest_shortlist = cached_shortlist
    if _WORKER.get("key") == (id(settings), cache_root):
        return
    _SHORTLISTS.clear()
    _WORKER.update(key=(id(settings), cache_root), settings=settings, universe=universe, kwargs=kwargs,
                   cache=preload(Path(cache_root), [c.symbol for c in universe]))


def _params(s: Settings, frm: date, to: date) -> dict:
    return {"from": frm.isoformat(), "to": to.isoformat(), "universe": "both",
            "strategies": [n for n, c in s.strategies.items() if c.enabled],
            "shortlist_size": s.screener.shortlist_size, "slippage_pct": s.backtest.slippage_pct,
            "max_risk_pct": s.capital.max_risk_pct, "initial_capital": s.capital.initial_capital}


def _run_one(task: tuple[int, dict, date, date]) -> tuple[int, dict, float]:
    index, overrides, frm, to = task
    s = settings_with_overrides(_WORKER["settings"], overrides)
    metrics = run_backtest(s, None, _params(s, frm, to), 0, _WORKER["cache"], _WORKER["universe"],
                           sink_factory=MemorySink, **_WORKER["kwargs"])
    metrics.pop("missed", None)
    return index, metrics, _peak_rss_mb()


def _map(tasks, workers, init_args, on_done):
    if not tasks:
        return
    if workers <= 1:
        _init_worker(*init_args)
        try:
            for task in tasks:
                on_done(_run_one(task))
        finally:
            replay.backtest_shortlist = _ORIGINAL_SHORTLIST  # in-process: leave replay as other callers expect
        return
    with get_context("spawn").Pool(workers, initializer=_init_worker, initargs=init_args) as pool:
        for out in pool.imap_unordered(_run_one, tasks):
            on_done(out)


def run_sweep(settings: Settings, grid: Grid, train=DEFAULT_TRAIN, test=DEFAULT_TEST, workers: int | None = None,
              cache_root: str | Path = "data/candles", universe: list[Constituent] = (),
              progress_cb=lambda done, total, phase, peak_rss_mb: None, checkpoint: str | Path | None = None,
              resume: bool = False, **backtest_kwargs) -> SweepResult:
    """backtest_kwargs (classify/detect_all) go to run_backtest and must be picklable when workers > 1.

    checkpoint: a JSONL file getting a header line and then one line per finished combination per phase;
    resume=True reloads it (it must match grid and split), skips finished work and keeps appending.
    """
    check_split(train, test)
    total, combos = expand_grid(grid)
    validate_combos(settings, combos)
    workers = workers if workers is not None else default_workers()
    init_args = (settings, str(cache_root), list(universe), backtest_kwargs)
    results = [ComboResult(i, c, {}) for i, c in enumerate(combos)]
    header = _header(grid, train, test)
    finished = _load_checkpoint(Path(checkpoint), header) if resume else []
    if checkpoint is not None and not resume:
        Path(checkpoint).parent.mkdir(parents=True, exist_ok=True)
        Path(checkpoint).write_text(json.dumps(header) + "\n")
    completed = set()
    peak = 0.0
    for entry in finished:
        setattr(results[entry["index"]], entry["phase"], entry["metrics"])
        completed.add((entry["phase"], entry["index"]))
        peak = max(peak, entry.get("peak_rss_mb") or 0.0)
    steps = len(combos) + min(grid.top_k, len(combos))
    done = len(finished)

    def record(phase):
        def on_done(out):
            nonlocal done, peak
            index, metrics, rss = out
            setattr(results[index], phase, metrics)
            if checkpoint is not None:
                with open(checkpoint, "a") as f:
                    f.write(json.dumps({"type": "result", "phase": phase, "index": index,
                                        "overrides": results[index].overrides, "metrics": metrics,
                                        "peak_rss_mb": rss}, default=str) + "\n")
            peak = max(peak, rss)
            done += 1
            progress_cb(done, steps, phase, peak)
        return on_done

    todo = [(c.index, c.overrides, *train) for c in results if ("train", c.index) not in completed]
    _map(todo, workers, init_args, record("train"))
    for c in results:
        c.score = score(c.train, grid)
    top = sorted((c for c in results if c.score is not None), key=lambda c: (-c.score, c.index))[:grid.top_k]
    todo = [(c.index, c.overrides, *test) for c in top if ("test", c.index) not in completed]
    _map(todo, min(workers, max(1, len(todo))), init_args, record("test"))
    for c in top:
        c.overfit = is_overfit(c.train, c.test)
        c.passes_gate = passes_gate(settings, c.train, c.test)
    return SweepResult(grid, tuple(train), tuple(test), total, results, top, peak)


def _flat(tree: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in tree.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        out.update(_flat(v, key) if isinstance(v, dict) else {key: v})
    return out


def _fmt(x) -> str:
    if x is None:
        return "n/a"
    return f"{x:.3f}" if isinstance(x, float) else str(x)


def verdict(result: SweepResult) -> str:
    n = len(result.passing)
    return f"{n} configurations pass the out-of-sample gate" if n else \
        "No configuration passes — do not trust live alerts yet"


def render_markdown(result: SweepResult, settings: Settings) -> str:
    g = result.grid
    lines = [
        "# Walk-forward sweep", "",
        f"- Train: {result.train[0]} → {result.train[1]}; test: {result.test[0]} → {result.test[1]}",
        f"- Grid product: {result.total_combinations}; combinations run: {len(result.combos)} "
        f"(max {g.max_combinations}, seed {g.seed})",
        f"- Score = train expectancy_r − {g.drawdown_penalty} × train max_drawdown_r; min train trades "
        f"{g.min_train_trades}; top_k {g.top_k}; slippage {settings.backtest.slippage_pct}%",
        f"- Gate: test expectancy_r > 0, train+test trades ≥ {GATE_MIN_TRADES}, test maxDD ≤ "
        f"{settings.capital.daily_loss_limit_r * GATE_DD_MULT}R",
        f"- Peak worker RSS: {result.peak_rss_mb} MB",
        "", "## Grid", "", "```yaml", yaml.safe_dump(g.overrides, sort_keys=True).rstrip(), "```", "",
        "## Top combinations (ranked on train)", "",
        "| # | overrides | train trades | train win | train exp R | train PF | train maxDD | score | "
        "test trades | test win | test exp R | test PF | test maxDD | overfit | gate |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for rank, c in enumerate(result.top, 1):
        tr, te = c.train, c.test
        ov = "<br>".join(f"{k}={v}" for k, v in _flat(c.overrides).items())
        lines.append(f"| {rank} | {ov} | {tr['trades']} | {_fmt(tr['win_rate'])} | {_fmt(tr['expectancy_r'])} | "
                     f"{_fmt(tr['profit_factor'])} | {_fmt(tr['max_drawdown_r'])} | {_fmt(c.score)} | "
                     f"{te['trades']} | {_fmt(te['win_rate'])} | {_fmt(te['expectancy_r'])} | "
                     f"{_fmt(te['profit_factor'])} | {_fmt(te['max_drawdown_r'])} | {'yes' if c.overfit else 'no'} | "
                     f"{'PASS' if c.passes_gate else 'fail'} |")
    if not result.top:
        lines.append(f"\nNo combination reached {g.min_train_trades} train trades.")
    best = result.best
    if best:
        lines += ["", "## Best passing combination: test breakdown by strategy", "",
                  "| strategy | trades | win | expectancy R |", "|---|---|---|---|"]
        lines += [f"| {k} | {v['trades']} | {_fmt(v['win_rate'])} | {_fmt(v['expectancy_r'])} |"
                  for k, v in best.test["by_strategy"].items()]
    lines += ["", "## Verdict", "", f"**{verdict(result)}.**", ""]
    return "\n".join(lines)


def write_reports(result: SweepResult, settings: Settings, out_dir: str | Path, now: datetime) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"sweep-{now:%Y%m%d-%H%M%S}"
    paths = {"md": stem.with_suffix(".md"), "json": stem.with_suffix(".json")}
    paths["md"].write_text(render_markdown(result, settings))
    payload = {"generated_at": now.isoformat(), "train": [d.isoformat() for d in result.train],
               "test": [d.isoformat() for d in result.test], "grid": asdict(result.grid),
               "total_combinations": result.total_combinations, "verdict": verdict(result),
               "peak_rss_mb": result.peak_rss_mb,
               "top": [asdict(c) for c in result.top], "combos": [asdict(c) for c in result.combos]}
    paths["json"].write_text(json.dumps(payload, indent=2, default=str))
    if result.best:
        paths["recommended"] = out / f"{stem.name}-recommended.yaml"
        paths["recommended"].write_text(yaml.safe_dump(result.best.overrides, sort_keys=True))
    return paths
