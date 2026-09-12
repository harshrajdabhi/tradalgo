from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradalgo import indicators as ind

TZ = "Asia/Kolkata"


def frame(rows, index):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=index, dtype=float)
    df.index.name = "ts"
    return df


def daily(closes, highs=None, lows=None, start="2026-08-03", volume=1000.0):
    idx = pd.bdate_range(start, periods=len(closes), tz=TZ, name="ts")
    highs = highs if highs is not None else [c + 1 for c in closes]
    lows = lows if lows is not None else [c - 1 for c in closes]
    return frame([[c, h, l, c, volume] for c, h, l in zip(closes, highs, lows)], idx)


def test_true_range_and_wilder_atr_by_hand():
    df = daily([10, 11, 12, 11, 13], highs=[11, 12, 13, 12, 15], lows=[9, 10, 11, 10, 12])
    tr = ind.true_range(df)
    # bar0: h-l=2; bar1: max(2,|12-10|,|10-10|)=2; bar2: 2; bar3: max(2,|12-12|,|10-12|)=2; bar4: max(3,|15-11|,|12-11|)=4
    assert tr.tolist() == [2, 2, 2, 2, 4]
    atr = ind.atr(df, period=3)
    assert np.isnan(atr.iloc[1])
    assert atr.iloc[2] == pytest.approx(2.0)
    assert atr.iloc[3] == pytest.approx(2.0)
    assert atr.iloc[4] == pytest.approx((2.0 * 2 + 4) / 3)


def test_ema_seeds_with_sma():
    s = pd.Series([1.0, 2, 3, 4, 5])
    e = ind.ema(s, 3)
    assert np.isnan(e.iloc[1])
    assert e.iloc[2] == pytest.approx(2.0)
    assert e.iloc[3] == pytest.approx(3.0)
    assert e.iloc[4] == pytest.approx(4.0)


def test_rsi_extremes_and_by_hand():
    up = pd.Series(np.arange(1.0, 20))
    assert ind.rsi(up, 14).iloc[-1] == pytest.approx(100.0)
    s = pd.Series([10.0, 11, 10, 12])
    # period 2: gains [1,0] avg .5 losses [0,1] avg .5 -> rsi 50 at idx2; idx3 gain 2: ag=(.5+2)/2=1.25, al=.25 -> 83.33
    r = ind.rsi(s, 2)
    assert r.iloc[2] == pytest.approx(50.0)
    assert r.iloc[3] == pytest.approx(100 - 100 / (1 + 1.25 / 0.25))


def test_rsi_flat_series_is_neutral():
    assert ind.rsi(pd.Series([5.0] * 10), 3).iloc[-1] == pytest.approx(50.0)


def test_rolling_percentile_nan_when_current_nan():
    s = pd.Series([1.0, 2, 3, np.nan])
    assert np.isnan(ind.rolling_percentile(s, 4, min_periods=2).iloc[-1])


def test_adx_exact_values_by_hand():
    df = daily([9, 11, 12, 11, 14], highs=[10, 12, 13, 12, 15], lows=[8, 9, 11, 10, 12])
    # +DM: [-,2,1,0,3]  -DM: [-,0,0,1,0]  TR: [-,3,2,2,4]; Wilder(2) seeded with mean of bars 1..2
    s_tr, s_p, s_m = 2.5, 1.5, 0.0
    di = [(100 * s_p / s_tr, 100 * s_m / s_tr)]
    for tr, p, m in [(2, 0, 1), (4, 3, 0)]:
        s_tr, s_p, s_m = (s_tr + tr) / 2, (s_p + p) / 2, (s_m + m) / 2
        di.append((100 * s_p / s_tr, 100 * s_m / s_tr))
    dx = [100 * abs(p - m) / (p + m) for p, m in di]  # [100, 20, 76.47]
    adx2 = (dx[0] + dx[1]) / 2
    adx3 = (adx2 + dx[2]) / 2
    out = ind.adx(df, 2)
    assert out["plus_di"].iloc[2:].tolist() == pytest.approx([d[0] for d in di])
    assert out["minus_di"].iloc[2:].tolist() == pytest.approx([d[1] for d in di])
    assert np.isnan(out["adx"].iloc[2])
    assert out["adx"].iloc[3] == pytest.approx(60.0) == pytest.approx(adx2)
    assert out["adx"].iloc[4] == pytest.approx(adx3)
    assert adx3 == pytest.approx((60 + 100 * 52 / 68) / 2)


def test_session_vwap_exact_with_asymmetric_bars():
    idx = pd.DatetimeIndex(["2026-09-11 09:15", "2026-09-11 09:20", "2026-09-11 09:25"], tz=TZ)
    df = frame([[0, 12, 9, 11.4, 100], [0, 11, 10, 10.1, 300], [0, 13, 10, 12.5, 600]], idx)
    tp = [(12 + 9 + 11.4) / 3, (11 + 10 + 10.1) / 3, (13 + 10 + 12.5) / 3]
    expected = [tp[0], (tp[0] * 100 + tp[1] * 300) / 400, (tp[0] * 100 + tp[1] * 300 + tp[2] * 600) / 1000]
    assert ind.session_vwap(df).tolist() == pytest.approx(expected)


def test_adx_strong_uptrend():
    closes = list(np.arange(100.0, 160.0))
    out = ind.adx(daily(closes), 14)
    assert list(out.columns) == ["adx", "plus_di", "minus_di"]
    last = out.iloc[-1]
    assert last["plus_di"] > last["minus_di"]
    assert last["adx"] > 50


def test_session_vwap_resets_each_date():
    idx = pd.DatetimeIndex(["2026-09-10 15:20", "2026-09-10 15:25", "2026-09-11 09:15", "2026-09-11 09:20"], tz=TZ)
    df = frame([[0, 12, 8, 10, 100], [0, 22, 18, 20, 300], [0, 31, 29, 30, 50], [0, 41, 39, 40, 50]], idx)
    v = ind.session_vwap(df)
    assert v.iloc[0] == pytest.approx(10)
    assert v.iloc[1] == pytest.approx((10 * 100 + 20 * 300) / 400)
    assert v.iloc[2] == pytest.approx(30)
    assert v.iloc[3] == pytest.approx(35)


def test_intraday_relative_volume_same_time_of_day():
    idx = pd.DatetimeIndex([f"2026-09-{d:02d} {t}" for d in (8, 9, 10) for t in ("09:15", "09:20")], tz=TZ)
    vols = [100, 10, 300, 30, 400, 40]
    df = frame([[1, 1, 1, 1, v] for v in vols], idx)
    rv = ind.intraday_relative_volume(df, lookback_sessions=2)
    assert np.isnan(rv.iloc[0]) and np.isnan(rv.iloc[1])
    assert rv.iloc[2] == pytest.approx(3.0)
    assert rv.iloc[4] == pytest.approx(400 / 200)
    assert rv.iloc[5] == pytest.approx(40 / 20)


def test_daily_relative_volume():
    df = daily([10.0] * 21)
    df.iloc[-1, df.columns.get_loc("volume")] = 3000
    assert ind.daily_relative_volume(df, 20) == pytest.approx(3.0)


def test_percentiles_in_range():
    rng = np.random.default_rng(0)
    closes = list(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))))
    df = daily(closes)
    rv = ind.realized_vol_percentile(df)
    ap = ind.atr_pct_percentile(df)
    assert 0 <= rv.iloc[-1] <= 100 and 0 <= ap.iloc[-1] <= 100


def test_swings_confirmed_only_after_n_bars():
    highs = [10, 11, 15, 12, 11, 10]
    lows = [9, 8, 7, 9, 10, 9]
    df = daily([h - 0.5 for h in highs], highs=highs, lows=lows)
    sw = ind.swings(df, n=2)
    # swing high at bar 2 becomes known at bar 4
    assert np.isnan(sw["swing_high"].iloc[3])
    assert sw["swing_high"].iloc[4] == 15
    assert sw["swing_low"].iloc[4] == 7
    # truncating future bars must not create a swing earlier
    assert sw["swing_high"].iloc[:4].isna().all()
    assert ind.swings(df.iloc[:4], n=2)["swing_high"].isna().all()


def test_prev_day_week_and_opening_range():
    df = daily([10, 11, 12, 13, 14, 15, 16], highs=[11, 20, 13, 14, 15, 16, 17], lows=[9, 10, 5, 12, 13, 14, 15])
    # 2026-08-03 Mon .. 08-07 Fri, 08-10 Mon, 08-11 Tue
    assert ind.prev_day_hlc(df, date(2026, 8, 11)) == (16, 14, 15)
    assert ind.prev_week_hl(df, date(2026, 8, 11)) == (20, 5)
    idx = pd.DatetimeIndex(["2026-09-11 09:15", "2026-09-11 09:20", "2026-09-11 09:25", "2026-09-11 09:30"], tz=TZ)
    m5 = frame([[0, 10, 9, 0, 1], [0, 12, 8, 0, 1], [0, 11, 9.5, 0, 1], [0, 50, 1, 0, 1]], idx)
    assert ind.opening_range(m5, date(2026, 9, 11)) == (12, 8)


def test_consolidation_measures():
    closes = [100 + (5 if i % 2 else -5) for i in range(40)] + [100.0] * 20
    highs = [c + 3 for c in closes[:-1]] + [100.1]
    lows = [c - 3 for c in closes[:-1]] + [99.9]
    df = daily(closes, highs=highs, lows=lows)
    assert ind.nr7(df).iloc[-1]
    assert ind.bb_width_percentile(df, lookback=40).iloc[-1] <= 30


def test_key_levels_and_nearest():
    closes = [100.0] * 30
    highs = [101.0] * 30
    lows = [99.0] * 30
    highs[10] = 110.0
    lows[15] = 90.0
    highs[-1] = 101.02
    df = daily(closes, highs=highs, lows=lows)
    as_of = (df.index[-1] + pd.Timedelta(days=1)).date()
    levels = ind.key_levels(df, as_of, tolerance_pct=0.001)
    assert levels == sorted(levels)
    assert 110.0 in levels and 90.0 in levels
    assert sum(abs(l - 101.0) < 0.2 for l in levels) == 1
    assert ind.nearest_level_above(102, levels) == 110.0
    assert ind.nearest_level_below(95, levels) == 90.0
    assert ind.nearest_level_above(200, levels) is None
