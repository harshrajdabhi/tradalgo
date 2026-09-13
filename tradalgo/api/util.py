import json

import pandas as pd


def df_records(df: pd.DataFrame) -> list[dict]:
    """A DataFrame as JSON-safe list[dict]: NaN/NaT -> null, numpy scalars -> plain Python."""
    if df.empty:
        return []
    return json.loads(df.to_json(orient="records", date_format="iso"))
