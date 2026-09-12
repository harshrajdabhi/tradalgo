import json
from datetime import date, datetime

import pytest
from sqlalchemy import insert, select

from tradalgo.clock import IST
from tradalgo.screener.preopen import annotate_preopen
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import job_runs, shortlist

D = date(2026, 9, 11)
NOW = datetime(2026, 9, 11, 9, 8, tzinfo=IST)


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "t.db")
    init_db(eng)
    rows = [("FLAT", "long"), ("BIGGAP", "long"), ("OPPOSE", "long"), ("NOPRICE", "short"), ("SHORTOK", "short")]
    with eng.begin() as conn:
        for i, (sym, direction) in enumerate(rows, 1):
            conn.execute(insert(shortlist).values(
                trade_date=D.isoformat(), rank=i, symbol=sym, composite_score=70 - i,
                factor_scores_json=json.dumps({"direction": direction}), reasons="x", demoted=0))
        conn.execute(insert(shortlist).values(trade_date="2026-09-10", rank=1, symbol="OLD", composite_score=1,
                                              factor_scores_json="{}", demoted=0))
    return eng


def test_annotate_gap_and_demotion(engine):
    prev = {s: 100.0 for s in ("FLAT", "BIGGAP", "OPPOSE", "NOPRICE", "SHORTOK")}
    atr = {s: 2.0 for s in prev}
    pre = {"FLAT": 100.5, "BIGGAP": 102.0, "OPPOSE": 98.8, "SHORTOK": 99.2, "NEWSYM": 120.0}
    out = annotate_preopen(engine, D, pre, prev, atr, max_gap_atr=0.75, now=NOW)
    by = {r["symbol"]: r for r in out}
    assert "NEWSYM" not in by
    assert by["FLAT"]["gap_pct"] == pytest.approx(0.5) and not by["FLAT"]["demoted"]
    assert by["BIGGAP"]["demoted"]  # 1.0 ATR > 0.75
    assert by["OPPOSE"]["demoted"]  # -0.6 ATR against a long bias > 0.5
    assert not by["SHORTOK"]["demoted"]  # gap in bias direction, within limit
    assert by["NOPRICE"]["gap_pct"] is None and not by["NOPRICE"]["demoted"]
    with engine.connect() as conn:
        rows = {r["symbol"]: r for r in conn.execute(select(shortlist)).mappings()}
        job = conn.execute(select(job_runs)).mappings().one()
    assert len(rows) == 6
    assert rows["BIGGAP"]["demoted"] == 1 and rows["BIGGAP"]["gap_pct"] == pytest.approx(2.0)
    assert rows["OLD"]["gap_pct"] is None
    assert job["job"] == "preopen" and job["status"] == "succeeded"
