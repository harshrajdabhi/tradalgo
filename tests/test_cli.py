import yaml
from sqlalchemy import inspect

from tradalgo.cli import main
from tradalgo.storage.db import make_engine


def test_init_creates_db_with_all_tables(tmp_path, raw_config):
    raw_config["paths"]["data_dir"] = str(tmp_path / "data")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(raw_config))

    assert main(["--config", str(cfg), "init"]) == 0
    tables = set(inspect(make_engine(tmp_path / "data" / "tradalgo.db")).get_table_names())
    assert {"job_runs", "shortlist", "signals", "decisions", "alerts", "user_actions",
            "paper_trades", "backtest_runs", "backtest_trades", "health_events"} <= tables

