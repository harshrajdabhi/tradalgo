"""Seed a throwaway data dir + config for the real-API e2e run. Usage: seed.py <out_dir>.

Never touches data/tradalgo.db: everything lives under <out_dir>.
"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from datetime import datetime

from sqlalchemy import insert, text, update

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from tests.test_api_helpers import seed  # noqa: E402
from tradalgo.clock import IST  # noqa: E402
from tradalgo.storage.db import init_db, make_engine  # noqa: E402
from tradalgo.storage.schema import alerts, backtest_runs, backtest_trades  # noqa: E402

SYMBOL = "RELIANCE"
SEED_DAY = "2026-09-10"  # the day baked into tests.test_api_helpers.seed


def main(out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    data_dir = out / "data"
    (data_dir / "candles" / "5m").mkdir(parents=True)

    engine = make_engine(data_dir / "tradalgo.db")
    init_db(engine)
    ids = seed(engine)
    legs = [
        {"kind": "partial_exit", "ts": "2026-09-10T10:15:00+05:30", "price": 102.0, "qty": 5, "r": 1.0},
        {"kind": "trail_update", "ts": "2026-09-10T10:45:00+05:30", "price": None, "qty": 0, "r": 0.0,
         "new_stop": 100.0},
        {"kind": "stop_hit", "ts": "2026-09-10T11:30:00+05:30", "price": 104.0, "qty": 5, "r": 2.8},
    ]
    with engine.begin() as conn:
        conn.execute(update(backtest_trades).where(backtest_trades.c.id == ids["trade_id"]).values(
            exit_ts="2026-09-10T11:30:00+05:30", legs_json=json.dumps(legs)))
        conn.execute(update(backtest_runs).where(backtest_runs.c.id == ids["run_id"]).values(
            params_json=json.dumps({"from": "2026-01-01", "to": "2026-06-30"}),
            metrics_json=json.dumps({"trades": 1, "win_rate": 1.0, "expectancy_r": 1.9, "max_drawdown_r": 0.0,
                                     "fill_rate": 1.0, "missed_entries": 0, "by_strategy": {"orb": {"trades": 1}}})))
        conn.execute(insert(alerts).values(
            dedup_key="d2", alert_type="entry", symbol="TCS", text="TCS long", status="sent",
            created_at="2026-09-10T09:40:00+05:30", attempts=1, valid_until="2026-09-10T10:40:00+05:30"))
    # the UI asks for 'today', so move every seeded timestamp onto today
    today = datetime.now(IST).date().isoformat()
    with engine.begin() as conn:
        tables = [r[0] for r in conn.execute(text("select name from sqlite_master where type='table'"))]
        for table in tables:
            for _, col, ctype, *_ in conn.execute(text(f"pragma table_info({table})")).all():
                if "TEXT" in ctype.upper() or "CHAR" in ctype.upper():
                    conn.execute(text(f"update {table} set {col} = replace({col}, :a, :b) where {col} like :l"),
                                 {"a": SEED_DAY, "b": today, "l": f"%{SEED_DAY}%"})
    engine.dispose()

    idx = pd.date_range(f"{today} 09:15", f"{today} 15:25", freq="5min", tz="Asia/Kolkata")
    rng = np.random.default_rng(1)
    close = 100 + np.cumsum(rng.normal(0.05, 0.4, len(idx)))
    candles = pd.DataFrame({"open": close - 0.1, "high": close + 0.4, "low": close - 0.4,
                            "close": close, "volume": rng.integers(1000, 5000, len(idx)).astype(float)}, index=idx)
    candles.index.name = "ts"
    candles.to_parquet(data_dir / "candles" / "5m" / f"{SYMBOL}.parquet")

    with open(REPO / "config.yaml") as f:
        cfg = yaml.safe_load(f)
    cfg["paths"]["data_dir"] = str(data_dir)
    with open(out / "config.yaml", "w") as f:
        yaml.safe_dump(cfg, f)
    (out / "ids.json").write_text(json.dumps(ids))
    print(f"seeded {out}: {ids}")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
