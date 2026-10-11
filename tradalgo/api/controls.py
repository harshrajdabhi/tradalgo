"""The only write paths the dashboard uses. All narrow and validated."""
import shutil
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy import Engine, select, update

from tradalgo.config import Settings
from tradalgo.storage import repo
from tradalgo.storage.schema import alerts, backtest_runs

VALID_UNIVERSES = ("nifty50", "niftynext50", "both")
VALID_STRATEGIES = ("orb", "gap", "vwap", "pdhl", "pullback", "range_breakout")


def kill_switch_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "KILL"


def kill_switch_active(data_dir: str | Path) -> bool:
    return kill_switch_path(data_dir).exists()


def set_kill_switch(data_dir: str | Path, on: bool) -> None:
    path = kill_switch_path(data_dir)
    if on:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    else:
        path.unlink(missing_ok=True)


def validate_backtest_params(params: dict) -> None:
    for key in ("from", "to", "universe", "strategies", "shortlist_size",
                "slippage_pct", "max_risk_pct", "initial_capital"):
        if key not in params:
            raise ValueError(f"missing backtest param: {key}")
    datetime.fromisoformat(params["from"])
    datetime.fromisoformat(params["to"])
    if params["from"] > params["to"]:
        raise ValueError("from date must not be after to date")
    if params["universe"] not in VALID_UNIVERSES:
        raise ValueError(f"universe must be one of {VALID_UNIVERSES}")
    if not params["strategies"] or any(s not in VALID_STRATEGIES for s in params["strategies"]):
        raise ValueError(f"strategies must be a non-empty subset of {VALID_STRATEGIES}")
    if not (5 <= params["shortlist_size"] <= 7):
        raise ValueError("shortlist_size must be between 5 and 7")
    if params["slippage_pct"] < 0:
        raise ValueError("slippage_pct must be >= 0")
    if not (0 < params["max_risk_pct"] <= 0.03):
        raise ValueError("max_risk_pct must be in (0, 0.03]")
    if params["initial_capital"] <= 0:
        raise ValueError("initial_capital must be > 0")


def queue_backtest(engine: Engine, params: dict, now: datetime) -> int:
    validate_backtest_params(params)
    return repo.enqueue_backtest_run(engine, params, now)


def request_cancel_backtest(engine: Engine, run_id: int) -> None:
    with engine.begin() as conn:
        status = conn.execute(select(backtest_runs.c.status).where(backtest_runs.c.id == run_id)).scalar()
        if status == "queued":
            conn.execute(update(backtest_runs).where(backtest_runs.c.id == run_id).values(status="cancelled"))
        elif status == "running":
            conn.execute(update(backtest_runs).where(backtest_runs.c.id == run_id)
                         .values(status="cancel_requested"))


def resend_alert(engine: Engine, alert_id: int) -> bool:
    """Sets status back to 'queued' so the always-on worker's sender loop resends. Only from 'failed'."""
    with engine.begin() as conn:
        result = conn.execute(update(alerts).where(
            alerts.c.id == alert_id, alerts.c.status == "failed",
        ).values(status="queued"))
        return result.rowcount == 1


def save_settings(config_path: str | Path, new_dict: dict) -> None:
    """Validates with Settings, backs up the current file, then writes the new YAML. Raises on invalid config."""
    Settings.model_validate(new_dict)
    config_path = Path(config_path)
    if config_path.exists():
        backup = config_path.with_name(
            f"{config_path.name}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        shutil.copy2(config_path, backup)
    with open(config_path, "w") as f:
        yaml.safe_dump(new_dict, f, sort_keys=False)
