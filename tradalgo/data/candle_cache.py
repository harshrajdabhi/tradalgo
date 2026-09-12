from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from tradalgo.data.base import DataProvider, Resolution, empty_candles, normalize


class CandleCache:
    """Parquet cache per symbol/resolution. Fetches only uncovered head/tail ranges; never caches degraded data."""

    def __init__(self, root: str | Path, provider: DataProvider):
        self.root = Path(root)
        self.provider = provider

    def _path(self, symbol: str, resolution: Resolution) -> Path:
        return self.root / resolution / f"{symbol}.parquet"

    def load(self, symbol: str, resolution: Resolution) -> pd.DataFrame:
        path = self._path(symbol, resolution)
        return normalize(pd.read_parquet(path)) if path.exists() else empty_candles()

    def get(self, symbol: str, resolution: Resolution, start: date, end: date) -> pd.DataFrame:
        cached = self.load(symbol, resolution)
        if cached.empty:
            missing = [(start, end)]
        else:
            first, last = cached.index[0].date(), cached.index[-1].date()
            missing = []
            if start < first:
                missing.append((start, first - timedelta(days=1)))
            if end > last:
                missing.append((last, end))  # re-fetch the last cached day in case it was partial

        if missing:
            fetched = [self.provider.get_candles(symbol, resolution, a, b) for a, b in missing]
            cached = normalize(pd.concat([cached, *fetched]))
            if not self.provider.degraded:
                path = self._path(symbol, resolution)
                path.parent.mkdir(parents=True, exist_ok=True)
                cached.to_parquet(path)

        dates = cached.index.date
        return cached[(dates >= start) & (dates <= end)]
