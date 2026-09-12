"""Synthetic builders for cycle / paper broker / replay / worker tests. Index = IST candle start."""
from datetime import date, datetime, time, timedelta

import pandas as pd

from tradalgo.clock import IST
from tradalgo.data.base import INDEX_SYMBOL, normalize
from tradalgo.data.candle_cache import CandleCache
from tradalgo.data.universe import Constituent
from tradalgo.risk.plan import TradePlan
from tradalgo.strategies.base import Regime, Signal

TODAY = date(2026, 9, 15)  # Tuesday; 2026-09-14 is an NSE holiday
HOLIDAY = date(2026, 9, 14)
COLS = ["open", "high", "low", "close", "volume"]


def at(hh: int, mm: int, day: date = TODAY) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=IST)


def bars(start: datetime, rows: list[tuple], minutes: int = 5) -> pd.DataFrame:
    idx = pd.DatetimeIndex([start + timedelta(minutes=minutes * i) for i in range(len(rows))], name="ts")
    return pd.DataFrame([list(map(float, r)) for r in rows], index=idx, columns=COLS)


def rising_day(day: date, base: float, step: float = 0.5, volume: float = 1e5) -> pd.DataFrame:
    """75 bars; each opens at the prior close and rises `step`, so stops below never trigger."""
    rows = []
    for i in range(75):
        o = base + step * i
        rows.append((o, o + step + 0.1, o - 0.1, o + step, volume))
    return bars(at(9, 15, day), rows)


def make_signal(symbol="AAA", strategy="orb", ts=None, entry=100.0, stop=99.0, direction="long",
                regime=Regime.TREND_UP) -> Signal:
    return Signal(symbol=symbol, strategy=strategy, direction=direction, ts=ts or at(9, 35), entry=entry,
                  stop_loss=stop, regime=regime, market_regime=Regime.TREND_UP, counter_trend=False,
                  reason="test", features={})


def make_plan(signal: Signal, qty: int = 100) -> TradePlan:
    rps = signal.risk_per_share
    long = signal.direction == "long"
    band = 0.1 * rps
    return TradePlan(
        signal=signal, qty=qty, leverage_used=3.0, margin_required=0.0, risk_rupees=qty * rps,
        target_2r=signal.target(2), target_3r=signal.target(3), est_cost=50.0, room_to_level_r=99.0,
        expected_value_r=0.5,
        limit_low=signal.entry if long else signal.entry - band,
        limit_high=signal.entry + band if long else signal.entry,
        valid_until=signal.ts + timedelta(minutes=10),
    )


def fake_classify(candles_15m, candles_5m=None, **kwargs) -> Regime:
    return Regime.TREND_UP


def trading_weekdays(n: int, last: date) -> list[date]:
    out, d = [], last
    while len(out) < n:
        if d.weekday() < 5 and d != HOLIDAY:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def daily_trend(days: list[date], start: float, step: float, volume: float = 1e7) -> pd.DataFrame:
    rows, idx = [], []
    for i, d in enumerate(days):
        c = start + step * i
        rows.append((c - step / 2, c, c - 1, c, volume))  # high == close: no key level above the trend
        idx.append(datetime.combine(d, time(0, 0), tzinfo=IST))
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx, name="ts"), columns=COLS)


def universe(symbols: list[str]) -> list[Constituent]:
    return [Constituent(s, f"{s} Ltd", f"IND{i}", "nifty50") for i, s in enumerate(symbols)]


class FakeProvider:
    name = "fake"
    degraded = False

    def __init__(self, frames: dict[tuple[str, str], pd.DataFrame]):
        self.frames = frames

    def get_candles(self, symbol, resolution, start, end):
        df = normalize(self.frames[(symbol, resolution)])
        dates = df.index.date
        return df[(dates >= start) & (dates <= end)]


REPLAY_SYMBOLS = {"AAA": 1.5, "BBB": 1.6, "CCC": 1.7, INDEX_SYMBOL: 1.0}  # daily close step per day
REPLAY_DAYS = [date(2026, 9, 15), date(2026, 9, 16), date(2026, 9, 17)]


def build_replay_cache(root, alter_5m=None) -> CandleCache:
    """90 daily bars trending up (no levels above price) and 8 sessions of rising 5m bars opening above them."""
    days = trading_weekdays(90, REPLAY_DAYS[-1])
    frames = {}
    for symbol, step in REPLAY_SYMBOLS.items():
        daily = daily_trend(days, 50.0, step)
        frames[(symbol, "1d")] = daily
        five = pd.concat([rising_day(d, float(daily[daily.index.date < d]["close"].iloc[-1]) + 2)
                          for d in days[-8:]])
        frames[(symbol, "5m")] = alter_5m(five) if alter_5m else five
    cache = CandleCache(root, FakeProvider(frames))
    for symbol, resolution in frames:
        cache.get(symbol, resolution, days[0], days[-1])
    return cache


def replay_params(frm: date, to: date) -> dict:
    return {"from": frm.isoformat(), "to": to.isoformat(), "universe": "nifty50",
            "strategies": ["orb", "gap", "vwap", "pdhl", "pullback", "range_breakout"], "shortlist_size": 6,
            "slippage_pct": 0.05, "max_risk_pct": 0.03, "initial_capital": 20000.0}
