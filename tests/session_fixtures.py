"""A synthetic live day for session tests: one ORB-style long on AAA that reaches 2R, trails, hard-exits at 15:00."""
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import insert

from tradalgo.clock import MarketCalendar
from tradalgo.data.base import INDEX_SYMBOL, normalize
from tradalgo.data.candle_cache import CandleCache
from tradalgo.storage.db import init_db, make_engine
from tradalgo.storage.schema import shortlist
from tests.backtest_fixtures import TODAY, at, bars, daily_trend, make_signal, rising_day, trading_weekdays

SYMBOLS = ["AAA", "BBB"]


def today_bars(stop_bar: bool = False) -> pd.DataFrame:
    rows = [(100.0, 100.2, 99.8, 100.0, 1e5)] * 5                     # 09:15..09:35
    rows.append((100.0, 100.5, 98.5 if stop_bar else 99.8, 100.4, 1e5))  # 09:40
    rows.append((100.4, 102.2, 100.3, 102.0, 1e5))                     # 09:45: touches 2R=102
    price = 102.0
    while len(rows) < 75:
        rows.append((price, price + 0.05, price - 0.01, price + 0.01, 1e5))  # rising lows, never 3R
        price += 0.01
    return bars(at(9, 15), rows)


def frames(stop_bar: bool = False) -> dict:
    days = trading_weekdays(40, TODAY)
    out = {}
    for symbol in [*SYMBOLS, INDEX_SYMBOL]:
        out[(symbol, "1d")] = daily_trend(days[:-1], 50.0, 1.0)
        prior = [rising_day(d, 90.0) for d in days[-31:-1]]
        out[(symbol, "5m")] = normalize(pd.concat([*prior, today_bars(stop_bar)]))
    return out


class FakeProvider:
    """Serves the synthetic frames; `cutoff` hides today's bars starting at/after it, like a live feed."""
    name = "fake"

    def __init__(self, frames: dict, degraded: bool = False):
        self.frames, self.degraded = frames, degraded
        self.fail_next = False
        self.cutoff: datetime | None = None
        self.calls = []

    def get_candles(self, symbol, resolution, start: date, end: date) -> pd.DataFrame:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("boom")
        self.calls.append((symbol, resolution, start, end))
        df = self.frames[(symbol, resolution)]
        dates = df.index.date
        df = df[(dates >= start) & (dates <= end)]
        if self.cutoff is not None:
            df = df[(df.index.date < self.cutoff.date()) | (df.index < pd.Timestamp(self.cutoff))]
        return df


def make_cache(root, provider: FakeProvider) -> CandleCache:
    return CandleCache(root / "candles", provider)


def detector(extra: dict | None = None):
    """AAA orb long (09:35 bar) from 09:40 onward, re-detected every cycle; extra: {now: [signals]}."""
    sig = make_signal("AAA", "orb", ts=at(9, 35), entry=100.0, stop=99.0)

    def detect(ctx, settings, calendar):
        out = [sig] if ctx.symbol == "AAA" and ctx.now >= at(9, 40) else []
        return out + [s for s in (extra or {}).get(ctx.now, []) if s.symbol == ctx.symbol]
    return detect


def fake_classify(candles_15m, candles_5m=None, **kwargs):
    from tradalgo.strategies.base import Regime
    return Regime.TREND_UP


def make_db(tmp_path):
    engine = make_engine(tmp_path / "t.db")
    init_db(engine)
    with engine.begin() as conn:
        for i, s in enumerate(SYMBOLS):
            conn.execute(insert(shortlist).values(trade_date=TODAY.isoformat(), rank=i + 1, symbol=s,
                                                  composite_score=1.0, factor_scores_json="{}", demoted=0))
        conn.execute(insert(shortlist).values(trade_date=TODAY.isoformat(), rank=9, symbol="DEM",
                                              composite_score=1.0, factor_scores_json="{}", demoted=1))
    return engine


def calendar(settings) -> MarketCalendar:
    return MarketCalendar(settings.market, set())


def cycle_times(start: datetime, end: datetime):
    t = start
    while t <= end:
        yield t
        t += timedelta(minutes=5)
