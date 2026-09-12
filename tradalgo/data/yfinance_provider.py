from datetime import date, timedelta

import pandas as pd

from tradalgo.data.base import CANDLE_COLUMNS, INDEX_SYMBOL, Resolution, empty_candles, normalize


def to_yahoo_symbol(symbol: str) -> str:
    return "^NSEI" if symbol == INDEX_SYMBOL else f"{symbol}.NS"


def _default_ticker(symbol: str):
    import yfinance
    return yfinance.Ticker(symbol)


class YFinanceProvider:
    """Free fallback. Data can be delayed and 5m history is limited to ~60 days, so it is always degraded."""

    name = "yfinance"
    degraded = True

    def __init__(self, ticker_factory=_default_ticker):
        self._ticker = ticker_factory

    def get_candles(self, symbol: str, resolution: Resolution, start: date, end: date) -> pd.DataFrame:
        df = self._ticker(to_yahoo_symbol(symbol)).history(
            start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
            interval=resolution, auto_adjust=False,
        )
        if df.empty:
            return empty_candles()
        return normalize(df.rename(columns=str.lower)[CANDLE_COLUMNS])
