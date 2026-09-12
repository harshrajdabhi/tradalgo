import time
from datetime import date, timedelta

import pandas as pd

from tradalgo.data.base import INDEX_SYMBOL, TZ, ProviderError, Resolution, normalize

FYERS_RESOLUTION = {"5m": "5", "15m": "15", "1d": "1D"}
MAX_DAYS_PER_REQUEST = {"5m": 100, "15m": 100, "1d": 366}


def to_fyers_symbol(symbol: str) -> str:
    return "NSE:NIFTY50-INDEX" if symbol == INDEX_SYMBOL else f"NSE:{symbol}-EQ"


class FyersProvider:
    """Read-only market data. Only `history` is ever called on the client; no order APIs."""

    name = "fyers"
    degraded = False

    def __init__(self, client, min_request_interval: float = 0.35, sleep=time.sleep):
        self._client = client
        self._min_interval = min_request_interval  # FYERS allows ~200 requests/minute
        self._sleep = sleep

    def get_candles(self, symbol: str, resolution: Resolution, start: date, end: date) -> pd.DataFrame:
        rows = []
        chunk_start = start
        while chunk_start <= end:
            chunk_end = min(end, chunk_start + timedelta(days=MAX_DAYS_PER_REQUEST[resolution] - 1))
            resp = self._client.history(data={
                "symbol": to_fyers_symbol(symbol),
                "resolution": FYERS_RESOLUTION[resolution],
                "date_format": 1,
                "range_from": chunk_start.isoformat(),
                "range_to": chunk_end.isoformat(),
                "cont_flag": 1,
            })
            status = resp.get("s")
            if status == "ok":
                rows.extend(resp.get("candles", []))
            elif status != "no_data":
                raise ProviderError(f"FYERS history failed for {symbol} {resolution}: {resp.get('message', resp)}")
            chunk_start = chunk_end + timedelta(days=1)
            if chunk_start <= end:
                self._sleep(self._min_interval)
        return candles_from_rows(rows)


def candles_from_rows(rows: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["epoch", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df.pop("epoch"), unit="s", utc=True).dt.tz_convert(TZ)
    return normalize(df)
