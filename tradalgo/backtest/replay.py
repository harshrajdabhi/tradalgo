"""Walk-forward backtest: re-screen each day on data before it, then drive run_cycle bar by bar on cached candles.

Reads the candle cache only (CandleCache.load, never a provider fetch) and never writes the live shortlist.
"""
import json
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import Engine, insert

from tradalgo.backtest.metrics import compute_metrics
from tradalgo.backtest.paper_broker import PaperBroker
from tradalgo.clock import IST, MarketCalendar, load_holidays, to_ist
from tradalgo.config import MarketConfig, Settings
from tradalgo.data.base import INDEX_SYMBOL
from tradalgo.data.candle_cache import CandleCache
from tradalgo.data.universe import Constituent, liquid_symbols
from tradalgo.engine.cycle import BAR, CycleDeps, SessionState, SymbolFrames, run_cycle
from tradalgo.risk.plan import TradePlan
from tradalgo.screener.factors import compute_factors
from tradalgo.screener.rank import rank_candidates
from tradalgo.storage.schema import backtest_trades, decisions, signals

BACKFILL_HINT = "run `tradalgo backfill` to fill the candle cache for this date range"


class BacktestCancelled(Exception):
    pass


class MissingDataError(RuntimeError):
    pass


def _iso(dt: datetime) -> str:
    return to_ist(dt).isoformat()


def apply_params(settings: Settings, params: dict) -> Settings:
    """A copy of settings with the run's overrides; the shared Settings object is never mutated."""
    enabled = set(params["strategies"])
    return settings.model_copy(update={
        "capital": settings.capital.model_copy(update={
            "max_risk_pct": float(params["max_risk_pct"]), "initial_capital": float(params["initial_capital"])}),
        "screener": settings.screener.model_copy(update={"shortlist_size": int(params["shortlist_size"])}),
        "backtest": settings.backtest.model_copy(update={"slippage_pct": float(params["slippage_pct"])}),
        "strategies": {n: c.model_copy(update={"enabled": n in enabled}) for n, c in settings.strategies.items()},
    })


def trading_days(settings: Settings, start: date, end: date) -> tuple[MarketCalendar, list[date]]:
    holidays = set().union(*(load_holidays(settings.paths.static_dir, y) for y in range(start.year, end.year + 1)))
    calendar = MarketCalendar(settings.market, holidays)
    n = (end - start).days + 1
    return calendar, [d for d in (start + timedelta(days=i) for i in range(n)) if calendar.is_trading_day(d)]


def cycle_times(day: date, market: MarketConfig) -> list[datetime]:
    t = datetime.combine(day, market.open, tzinfo=IST) + BAR
    close = datetime.combine(day, market.close, tzinfo=IST)
    out = []
    while t <= close:
        out.append(t)
        t += BAR
    return out


def backtest_shortlist(settings: Settings, daily: dict[str, pd.DataFrame], index_daily: pd.DataFrame,
                       universe: list[Constituent], day: date) -> list[str]:
    """Same factors/ranking as the live screener, on daily candles strictly before `day`.

    Historical corporate-event blackouts and news are not available offline: blackout is empty, news neutral.
    """
    cfg = settings.screener
    prior = {s: df[df.index.date < day] for s, df in daily.items()}
    liquid = set(liquid_symbols(prior, cfg.min_avg_turnover_cr, cfg.min_price))
    factors = compute_factors(daily, index_daily, universe, day)
    if factors.empty:
        return []
    scored = rank_candidates(factors, cfg.factor_weights, liquid, set(), cfg.shortlist_size)
    return [s.symbol for s in scored if s.rejected is None]


class BacktestSink:
    def __init__(self, engine: Engine, run_id: int, broker: PaperBroker, frames: dict[str, SymbolFrames]):
        self.engine, self.run_id, self.broker, self.frames = engine, run_id, broker, frames
        self.records: list[dict] = []

    def record_signal(self, signal) -> int:
        with self.engine.begin() as conn:
            return conn.execute(insert(signals).values(
                ts=_iso(signal.ts), symbol=signal.symbol, strategy=signal.strategy, direction=signal.direction,
                regime=signal.regime.value, market_regime=signal.market_regime.value, entry=signal.entry,
                stop_loss=signal.stop_loss, target_2r=signal.target(2), target_3r=signal.target(3),
                features_json=json.dumps(signal.features, default=str, sort_keys=True),
                mode="backtest", backtest_run_id=self.run_id,
            )).inserted_primary_key[0]

    def record_decision(self, signal_id: int, decision) -> None:
        if isinstance(decision, TradePlan):
            values = dict(accepted=1, qty=decision.qty, leverage_used=decision.leverage_used,
                          risk_rupees=decision.risk_rupees, est_cost=decision.est_cost,
                          expected_value_r=decision.expected_value_r, room_to_target_r=decision.room_to_level_r)
        else:
            values = dict(accepted=0, rejection_reason=decision.reason)
        with self.engine.begin() as conn:
            conn.execute(insert(decisions).values(signal_id=signal_id, **values))

    def accept(self, plan: TradePlan, signal_id: int) -> int | None:
        bars = self.frames[plan.signal.symbol].candles_5m
        start = pd.Timestamp(plan.signal.ts) + BAR
        next_open = float(bars.at[start, "open"]) if start in bars.index else None
        fill = None if next_open is None else self.broker.fill_price(plan, next_open)
        if fill is None:
            self.broker.miss(plan, signal_id, next_open)
            return None
        return self.broker.open(plan, signal_id, start.to_pydatetime(), fill)

    def emit_event(self, event, taken: bool) -> None:
        record = self.broker.on_event(event)
        if record:
            self._store(record)

    def is_taken(self, trade_id: int) -> bool:
        return True

    def feed_bars(self, now: datetime) -> None:
        """MFE/MAE from the bar that just closed at `now`, before run_cycle manages exits on it."""
        start = pd.Timestamp(now) - BAR
        for trade_id in self.broker.open_trade_ids():
            bars = self.frames[self.broker.symbol_of(trade_id)].candles_5m
            if start in bars.index:
                self.broker.on_bar(trade_id, start.to_pydatetime(), float(bars.at[start, "high"]),
                                   float(bars.at[start, "low"]))

    def close_remaining(self, day: date) -> None:
        # only reachable when the day's data ends before the hard-exit bar
        for trade_id in self.broker.open_trade_ids():
            bars = self.frames[self.broker.symbol_of(trade_id)].candles_5m
            today = bars[bars.index.date == day]
            last = today.index[-1]
            self._store(self.broker.force_close(trade_id, (last + BAR).to_pydatetime(),
                                                float(today["close"].iloc[-1]), "eod_no_data"))

    def _store(self, r: dict) -> None:
        with self.engine.begin() as conn:
            conn.execute(insert(backtest_trades).values(
                backtest_run_id=self.run_id, signal_id=r["signal_id"], trade_date=r["trade_date"].isoformat(),
                symbol=r["symbol"], strategy=r["strategy"], direction=r["direction"],
                entry_ts=_iso(r["entry_ts"]), entry_price=r["entry_price"], exit_ts=_iso(r["exit_ts"]),
                exit_price=r["exit_price"], exit_reason=r["exit_reason"], qty=r["qty"],
                mfe_r=r["mfe_r"], mae_r=r["mae_r"], gross_r=r["gross_r"], net_r=r["net_r"],
            ))
        self.records.append(r)


class _IntradayCache:
    def __init__(self, cache: CandleCache):
        self.cache = cache
        self._frames: dict[str, tuple[pd.DataFrame, pd.Index]] = {}

    def window(self, symbol: str, day: date, sessions: int) -> pd.DataFrame:
        """That day's 5m bars plus the previous `sessions` sessions, which must all be in the cache."""
        if symbol not in self._frames:
            df = self.cache.load(symbol, "5m")
            self._frames[symbol] = (df, pd.Index(df.index.date))
        df, dates = self._frames[symbol]
        today = dates == day
        if not today.any():
            raise MissingDataError(f"no 5m candles for {symbol} on {day} in the cache; {BACKFILL_HINT}")
        prior = sorted(set(dates[dates < day]))[-sessions:]
        if len(prior) < sessions:
            raise MissingDataError(f"only {len(prior)} of {sessions} prior 5m sessions for {symbol} before {day} "
                                   f"in the cache; {BACKFILL_HINT}")
        return df[today | dates.isin(prior)]


def run_backtest(settings: Settings, engine: Engine, params: dict, run_id: int, cache: CandleCache,
                 universe: list[Constituent], progress_cb=lambda pct: None, cancel_cb=lambda: False, *,
                 classify=None, detect_all=None, leverage=lambda symbol: None) -> dict:
    """Known gap vs live: no historical corporate-event blackout or news (no free source), so news is neutral."""
    s = apply_params(settings, params)
    calendar, days = trading_days(s, date.fromisoformat(params["from"]), date.fromisoformat(params["to"]))
    members = [c for c in universe if params["universe"] == "both" or c.index == params["universe"]]

    daily = {c.symbol: cache.load(c.symbol, "1d") for c in members}
    daily = {sym: df for sym, df in daily.items() if not df.empty}
    index_daily = cache.load(INDEX_SYMBOL, "1d")
    if index_daily.empty or not daily:
        missing = INDEX_SYMBOL if index_daily.empty else f"the {params['universe']} universe"
        raise MissingDataError(f"no daily candles for {missing} in the cache; {BACKFILL_HINT}")

    deps = CycleDeps(settings=s, calendar=calendar, leverage=leverage)
    if classify is not None:
        deps.classify = classify
    if detect_all is not None:
        deps.detect_all = detect_all
    broker = PaperBroker(s.backtest.slippage_pct, s.costs)
    intraday = _IntradayCache(cache)
    capital = s.capital.initial_capital
    records: list[dict] = []

    for i, day in enumerate(days):
        if cancel_cb():
            raise BacktestCancelled(f"cancelled before {day}")
        picks = backtest_shortlist(s, daily, index_daily, members, day)
        n = max(deps.history_sessions, deps.regime_history_sessions)
        index_5m = intraday.window(INDEX_SYMBOL, day, n)
        frames = {sym: SymbolFrames(intraday.window(sym, day, n), daily[sym]) for sym in picks}
        sink = BacktestSink(engine, run_id, broker, frames)
        state = SessionState.new(day, capital)
        for now in cycle_times(day, s.market):
            sink.feed_bars(now)
            run_cycle(state, now, frames, index_5m, deps, sink, check_kill_switch=False)
        sink.close_remaining(day)
        records += sink.records
        capital += sum(r["net_rupees"] for r in sink.records)
        progress_cb(round(100 * (i + 1) / len(days), 1))

    if not days:
        progress_cb(100.0)
    return compute_metrics(sorted(records, key=lambda r: r["exit_ts"]), broker.missed)
