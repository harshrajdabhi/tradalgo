from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradalgo.data.universe import Constituent
from tradalgo.screener.factors import FACTOR_KEYS, compute_factors

TZ = "Asia/Kolkata"
TRADE_DATE = date(2026, 9, 11)


def make_daily(drift: float, seed: int, n: int = 260, vol: float = 1e6, end="2026-09-10") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=end, periods=n, tz=TZ, name="ts")
    close = 500 * np.exp(np.cumsum(rng.normal(drift, 0.004, n)))
    high = close * (1 + rng.uniform(0.002, 0.015, n))
    low = close * (1 - rng.uniform(0.002, 0.015, n))
    volume = vol * rng.uniform(0.7, 1.3, n)
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


def universe_and_data():
    universe = [Constituent(f"S{i}", f"Company {i}", "Banks" if i < 4 else "IT", "nifty50") for i in range(8)]
    daily = {c.symbol: make_daily((i - 4) * 0.002, seed=i) for i, c in enumerate(universe)}
    index = make_daily(0.0, seed=99)
    return universe, daily, index


def test_factor_keys_match_config(settings):
    assert set(FACTOR_KEYS) == set(settings.screener.factor_weights)


def test_scores_in_range_and_bias():
    universe, daily, index = universe_and_data()
    df = compute_factors(daily, index, universe, TRADE_DATE)
    assert set(df.index) == set(daily)
    for key in FACTOR_KEYS:
        assert df[key].between(0, 100).all()
    assert (df["news_sentiment"] == 50).all()
    assert df.loc["S7", "direction"] == "long"
    assert df.loc["S0", "direction"] == "short"
    # strong trend in either direction scores high on momentum
    assert df.loc["S7", "momentum_trend"] > df.loc["S4", "momentum_trend"]
    assert df.loc["S0", "momentum_trend"] > df.loc["S4", "momentum_trend"]


def test_sector_relative_strength_uses_industry_peers():
    universe, daily, index = universe_and_data()
    df = compute_factors(daily, index, universe, TRADE_DATE)
    banks = [f"S{i}" for i in range(4)]
    peers_mean = df.loc[banks, "ret20"].mean()
    s0 = df.loc["S0"]
    others = df.loc[banks[1:], "ret20"].mean()
    assert s0["rs_sector"] == pytest.approx(s0["ret20"] - others)
    assert np.isfinite(peers_mean)


def test_news_scores_bias_adjusted():
    universe, daily, index = universe_and_data()
    df = compute_factors(daily, index, universe, TRADE_DATE, news_scores={"S1": 90.0, "S7": 90.0})
    assert df.loc["S7", "direction"] == "long" and df.loc["S7", "news_sentiment"] == 90.0
    assert df.loc["S1", "direction"] == "short" and df.loc["S1", "news_sentiment"] == pytest.approx(10.0)


def test_long_bias_stock_lagging_its_sector_scores_low_on_rs():
    universe = [Constituent(f"S{i}", f"Company {i}", "Banks" if i < 4 else "IT", "nifty50") for i in range(8)]
    drifts = [0.002, 0.01, 0.01, 0.01, 0.002, 0.002, 0.002, 0.002]
    daily = {c.symbol: make_daily(drifts[i], seed=i) for i, c in enumerate(universe)}
    df = compute_factors(daily, make_daily(0.0, seed=99), universe, TRADE_DATE)
    assert df.loc["S0", "direction"] == "long"
    assert df.loc["S0", "rs_sector"] < 0
    assert df.loc["S0", "relative_strength"] < 50
    assert df.loc["S0", "relative_strength"] < df.loc["S1", "relative_strength"]


def level_fixture(last_close: float, swing_high: float, n: int = 80) -> pd.DataFrame:
    """Flat 99..101 range (ATR ~2), one confirmed swing high at bar 40, last close below PDH=101."""
    idx = pd.bdate_range(end="2026-09-10", periods=n, tz=TZ, name="ts")
    close = np.full(n, 100.0)
    high = np.full(n, 101.0)
    low = np.full(n, 99.0)
    high[40] = swing_high
    close[-1] = last_close
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": 1e6}, index=idx)


def _one(df):
    universe = [Constituent("X", "X Ltd", "IT", "nifty50")]
    return compute_factors({"X": df}, level_fixture(100.0, 101.0), universe, TRADE_DATE).loc["X"]


def test_level_at_pdh_is_trigger_and_room_measured_to_swing_beyond():
    row = _one(level_fixture(100.6, swing_high=106.0))
    assert row["direction"] == "long"
    assert row["trigger_name"] == "PDH" and row["trigger_level"] == 101.0
    assert row["nearest_level"] == 106.0
    assert row["room_atr"] == pytest.approx(5.0 / row["atr14"])
    assert row["room_atr"] > 2.0


def _rank_one(df):
    from tradalgo.screener.rank import rank_candidates
    universe = [Constituent("X", "X Ltd", "IT", "nifty50")]
    factors = compute_factors({"X": df}, level_fixture(100.0, 101.0), universe, TRADE_DATE)
    return rank_candidates(factors, {k: 1 / 7 for k in FACTOR_KEYS}, {"X"}, set(), 5)[0]


def test_trending_stock_under_pdh_with_swing_far_above_is_accepted():
    pick = _rank_one(level_fixture(100.6, swing_high=106.0))
    assert pick.rejected is None
    assert any("beyond PDH trigger" in r for r in pick.reasons)


def test_swing_just_beyond_pdh_trigger_blocks():
    row = _one(level_fixture(100.6, swing_high=101.8))
    assert row["trigger_name"] == "PDH"
    assert row["room_atr"] == pytest.approx(0.8 / row["atr14"])
    assert 0.35 < row["room_atr"] < 0.45
    assert "2R blocked" in _rank_one(level_fixture(100.6, swing_high=101.8)).rejected


def test_level_outside_trigger_zone_but_inside_required_room_rejects():
    # PDH 101 is 1.0 away (~0.5 ATR): beyond the 0.25 ATR trigger zone, short of the 0.6 ATR needed
    row = _one(level_fixture(100.0, swing_high=106.0))
    assert row["trigger_level"] is None and row["level_name"] == "PDH"
    assert "2R blocked" in _rank_one(level_fixture(100.0, swing_high=106.0)).rejected


def test_no_lookahead_future_rows_do_not_change_scores():
    universe, daily, index = universe_and_data()
    base = compute_factors(daily, index, universe, TRADE_DATE)
    future_daily = {}
    for s, df in daily.items():
        extra = make_daily(0.05, seed=123, n=5, vol=9e9, end="2026-09-17")
        future_daily[s] = pd.concat([df, extra])
    future_index = pd.concat([index, make_daily(-0.05, seed=5, n=5, end="2026-09-17")])
    after = compute_factors(future_daily, future_index, universe, TRADE_DATE)
    pd.testing.assert_frame_equal(base, after)


def test_short_history_symbols_skipped():
    universe, daily, index = universe_and_data()
    daily["S3"] = daily["S3"].tail(10)
    df = compute_factors(daily, index, universe, TRADE_DATE)
    assert "S3" not in df.index
