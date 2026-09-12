from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from tradalgo.clock import IST
from tradalgo.data.base import FallbackProvider, ProviderError
from tradalgo.data.candle_cache import CandleCache
from tradalgo.data.yfinance_provider import YFinanceProvider


def daily_frame(start: date, end: date) -> pd.DataFrame:
    days = pd.date_range(start, end, freq="D", tz="Asia/Kolkata")
    return pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0}, index=days)


class RangeProvider:
    name = "fake"

    def __init__(self, degraded=False):
        self.degraded = degraded
        self.calls = []

    def get_candles(self, symbol, resolution, start, end):
        self.calls.append((start, end))
        return daily_frame(start, end)


class FailingProvider:
    name = "fyers"
    degraded = False

    def get_candles(self, *args):
        raise ProviderError("token expired")


def test_yfinance_maps_symbol_and_converts_to_ist():
    seen = {}

    class Ticker:
        def __init__(self, symbol):
            seen["symbol"] = symbol

        def history(self, **kwargs):
            seen.update(kwargs)
            idx = pd.DatetimeIndex([datetime(2026, 9, 11, 3, 45)], tz="UTC")
            return pd.DataFrame({"Open": [1], "High": [2], "Low": [0.5], "Close": [1.5], "Volume": [10],
                                 "Dividends": [0]}, index=idx)

    p = YFinanceProvider(ticker_factory=Ticker)
    df = p.get_candles("RELIANCE", "5m", date(2026, 9, 11), date(2026, 9, 11))
    assert p.degraded
    assert seen["symbol"] == "RELIANCE.NS"
    assert (seen["start"], seen["end"], seen["interval"]) == ("2026-09-11", "2026-09-12", "5m")
    assert df.index[0] == datetime(2026, 9, 11, 9, 15, tzinfo=IST)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_fallback_used_and_reported_when_primary_fails():
    messages = []
    backup = RangeProvider(degraded=True)
    p = FallbackProvider(FailingProvider(), backup, on_fallback=messages.append)
    df = p.get_candles("SBIN", "1d", date(2026, 9, 1), date(2026, 9, 2))
    assert len(df) == 2 and p.degraded and p.name == "fake"
    assert "token expired" in messages[0]


def test_cache_fetches_only_missing_ranges(tmp_path):
    provider = RangeProvider()
    cache = CandleCache(tmp_path, provider)
    assert len(cache.get("SBIN", "1d", date(2026, 9, 1), date(2026, 9, 10))) == 10
    assert len(cache.get("SBIN", "1d", date(2026, 9, 3), date(2026, 9, 5))) == 3
    cache.get("SBIN", "1d", date(2026, 8, 30), date(2026, 9, 12))
    assert provider.calls == [
        (date(2026, 9, 1), date(2026, 9, 10)),
        (date(2026, 8, 30), date(2026, 8, 31)),
        (date(2026, 9, 10), date(2026, 9, 12)),
    ]
    assert len(CandleCache(tmp_path, RangeProvider()).load("SBIN", "1d")) == 14


def test_cache_does_not_persist_degraded_data(tmp_path):
    cache = CandleCache(tmp_path, RangeProvider(degraded=True))
    assert len(cache.get("SBIN", "1d", date(2026, 9, 1), date(2026, 9, 2))) == 2
    assert cache.load("SBIN", "1d").empty
