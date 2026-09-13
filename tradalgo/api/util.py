import json
import re

import pandas as pd

# NSE symbols: letters/digits plus '&' (M&M) and '-' (BAJAJ-AUTO). Used to keep any user- or
# query-supplied symbol out of CandleCache's parquet path (root / resolution / f"{symbol}.parquet").
SYMBOL_RE = re.compile(r"^[A-Z0-9&-]{1,20}$")


def is_valid_symbol(symbol: str) -> bool:
    return bool(SYMBOL_RE.match(symbol))


def df_records(df: pd.DataFrame) -> list[dict]:
    """A DataFrame as JSON-safe list[dict]: NaN/NaT -> null, numpy scalars -> plain Python."""
    if df.empty:
        return []
    return json.loads(df.to_json(orient="records", date_format="iso"))
