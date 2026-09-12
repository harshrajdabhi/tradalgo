import json
from datetime import date, datetime

import pandas as pd
import pytest
from sqlalchemy import select

from tradalgo.clock import IST
from tradalgo.screener.factors import FACTOR_KEYS
from tradalgo.screener.rank import ScoredSymbol, rank_candidates
from tradalgo.screener.run import run_screen
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import health_events, job_runs, shortlist
from tests.test_screener_factors import TRADE_DATE, universe_and_data

WEIGHTS = {k: 1 / 7 for k in FACTOR_KEYS}


def factor_row(score, direction="long", room_atr=3.0, level=110.0, level_name="PDH"):
    row = {k: score for k in FACTOR_KEYS}
    row.update(direction=direction, room_atr=room_atr, nearest_level=level, level_name=level_name,
               ret20=0.05, rs_nifty=0.031, rs_sector=0.01, atr_pct=0.02, atr_pct_pctile=82.0, rvol=1.4, close=100.0)
    return row


def test_composite_weighted_and_top_n():
    df = pd.DataFrame({f"S{i}": factor_row(10 * i) for i in range(8)}).T
    out = rank_candidates(df, WEIGHTS, liquid=set(df.index), blackout=set(), shortlist_size=3)
    picks = [s for s in out if s.rejected is None]
    assert [p.symbol for p in picks] == ["S7", "S6", "S5"]
    assert picks[0].composite_score == pytest.approx(70)
    assert isinstance(picks[0], ScoredSymbol)
    assert any("RS +3.1% vs NIFTY" in r for r in picks[0].reasons)
    assert any("3.0 ATR room to PDH" in r for r in picks[0].reasons)


def test_hard_filters_and_2r_room_reject():
    df = pd.DataFrame({
        "ILLIQ": factor_row(99), "EVENT": factor_row(98), "BLOCKED": factor_row(97, room_atr=0.5),
        "OK": factor_row(50), "NOLEVEL": factor_row(40, room_atr=float("nan"), level=None, level_name=None),
    }).T
    out = rank_candidates(df, WEIGHTS, liquid={"EVENT", "BLOCKED", "OK", "NOLEVEL"}, blackout={"EVENT"},
                          shortlist_size=5, stop_atr_frac=0.3)
    by = {s.symbol: s for s in out}
    assert "liquidity" in by["ILLIQ"].rejected
    assert "event" in by["EVENT"].rejected
    # 0.5 ATR room < 2 x 0.3 ATR stop
    assert "2R blocked" in by["BLOCKED"].rejected
    assert by["OK"].rejected is None and by["NOLEVEL"].rejected is None
    assert [s.symbol for s in out if s.rejected is None] == ["OK", "NOLEVEL"]


def fake_events(trade_date, next_day):
    return {"S1"}, "event calendar unavailable: test"


def fake_news(constituent, now):
    return 50.0


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "t.db")
    init_db(eng)
    return eng


def test_run_screen_persists_idempotently(settings, engine):
    universe, daily, index = universe_and_data()
    for df in daily.values():
        df["volume"] = 5e6
        # close at the bar's extreme so the prior-day level is not an immediate blocker
        last = df.index[-1]
        extreme = "high" if df["close"].iloc[-1] > df["close"].iloc[-21] else "low"
        df.loc[last, extreme] = df.loc[last, "close"]
    now = datetime(2026, 9, 11, 7, 0, tzinfo=IST)
    for _ in range(2):
        picks = run_screen(settings, engine, daily, index, universe, TRADE_DATE, now,
                           fetch_events=fake_events, fetch_news=fake_news)
    assert 0 < len(picks) <= settings.screener.shortlist_size
    assert all(p.rejected is None for p in picks)
    assert "S1" not in [p.symbol for p in picks]
    with engine.connect() as conn:
        rows = conn.execute(select(shortlist).order_by(shortlist.c.rank)).mappings().all()
        jobs = conn.execute(select(job_runs)).mappings().all()
        warnings = conn.execute(select(health_events)).mappings().all()
    assert [r["symbol"] for r in rows] == [p.symbol for p in picks]
    assert rows[0]["trade_date"] == "2026-09-11" and rows[0]["rank"] == 1
    stored = json.loads(rows[0]["factor_scores_json"])
    assert set(FACTOR_KEYS) <= set(stored) and stored["direction"] in ("long", "short")
    assert rows[0]["reasons"]
    assert len(jobs) == 2 and all(j["job"] == "screen" and j["status"] == "succeeded" for j in jobs)
    assert any("event calendar" in w["message"] for w in warnings)


def test_run_screen_records_failed_job(settings, engine):
    universe, daily, index = universe_and_data()

    def boom(trade_date, next_day):
        raise ValueError("bad")

    with pytest.raises(ValueError):
        run_screen(settings, engine, daily, index, universe, date(2026, 9, 11),
                   datetime(2026, 9, 11, 7, tzinfo=IST), fetch_events=boom, fetch_news=fake_news)
    with engine.connect() as conn:
        assert conn.execute(select(job_runs.c.status)).scalar() == "failed"
