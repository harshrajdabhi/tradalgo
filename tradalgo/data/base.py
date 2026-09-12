from datetime import date
from typing import Literal, Protocol

import pandas as pd

Resolution = Literal["5m", "15m", "1d"]
CANDLE_COLUMNS = ["open", "high", "low", "close", "volume"]
INDEX_SYMBOL = "NIFTY50"
TZ = "Asia/Kolkata"


class ProviderError(RuntimeError):
    pass


class DataProvider(Protocol):
    name: str
    degraded: bool

    def get_candles(self, symbol: str, resolution: Resolution, start: date, end: date) -> pd.DataFrame:
        """Candles for NSE `symbol` (or INDEX_SYMBOL) from start to end inclusive, indexed by IST timestamp."""
        ...


def empty_candles() -> pd.DataFrame:
    return pd.DataFrame(columns=CANDLE_COLUMNS, index=pd.DatetimeIndex([], tz=TZ, name="ts"), dtype=float)


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return empty_candles()
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize(TZ) if idx.tz is None else idx.tz_convert(TZ)
    out = df[CANDLE_COLUMNS].astype(float)
    out.index = idx.rename("ts")
    return out[~out.index.duplicated(keep="last")].sort_index()


class FallbackProvider:
    """Uses `primary`; on any provider failure serves the request from `fallback` and marks data degraded."""

    def __init__(self, primary: DataProvider, fallback: DataProvider, on_fallback=lambda message: None):
        self.primary = primary
        self.fallback = fallback
        self.on_fallback = on_fallback
        self.degraded = False

    @property
    def name(self) -> str:
        return self.fallback.name if self.degraded else self.primary.name

    def get_candles(self, symbol: str, resolution: Resolution, start: date, end: date) -> pd.DataFrame:
        try:
            df = self.primary.get_candles(symbol, resolution, start, end)
            self.degraded = self.primary.degraded
            return df
        except Exception as exc:  # any primary failure (auth, network, API) must not stop the run
            self.on_fallback(f"{self.primary.name} failed for {symbol} {resolution}: {exc}; using {self.fallback.name}")
            self.degraded = True
            return self.fallback.get_candles(symbol, resolution, start, end)
