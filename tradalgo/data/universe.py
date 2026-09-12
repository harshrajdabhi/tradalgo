import csv
import io
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

SOURCES = {
    "nifty50": "https://niftyindices.com/IndexConstituent/ind_nifty50list.csv",
    "niftynext50": "https://niftyindices.com/IndexConstituent/ind_niftynext50list.csv",
}
MIN_ROWS = 45


@dataclass(frozen=True)
class Constituent:
    symbol: str
    company: str
    industry: str
    index: str


def _parse(text: str, index: str) -> list[Constituent]:
    return [
        Constituent(r["Symbol"].strip(), r["Company Name"].strip(), r["Industry"].strip(), index)
        for r in csv.DictReader(io.StringIO(text))
        if r.get("Symbol") and r.get("Series", "EQ").strip() == "EQ"
    ]


def load_universe(static_dir: str | Path) -> list[Constituent]:
    return [c for index in SOURCES for c in _parse((Path(static_dir) / f"{index}.csv").read_text(), index)]


def _http_get(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    resp.raise_for_status()
    return resp.text


def refresh_constituents(static_dir: str | Path, fetch=_http_get) -> list[str]:
    """Overwrite the local CSVs with fresh index lists; keeps the existing file on any failure. Returns problems."""
    problems = []
    for index, url in SOURCES.items():
        try:
            text = fetch(url)
            rows = _parse(text, index)
        except Exception as exc:  # network/format failures fall back to the committed copy
            problems.append(f"{index}: download failed ({exc}); using existing list")
            continue
        if len(rows) < MIN_ROWS:
            problems.append(f"{index}: only {len(rows)} rows downloaded; using existing list")
            continue
        (Path(static_dir) / f"{index}.csv").write_text(text)
    return problems


def liquid_symbols(daily: dict[str, pd.DataFrame], min_turnover_cr: float, min_price: float,
                   lookback: int = 20) -> list[str]:
    """Symbols whose last close >= min_price and average daily turnover over `lookback` days >= min_turnover_cr."""
    keep = []
    for symbol, df in daily.items():
        recent = df.tail(lookback)
        if len(recent) < lookback:
            continue
        turnover_cr = (recent["close"] * recent["volume"]).mean() / 1e7
        if recent["close"].iloc[-1] >= min_price and turnover_cr >= min_turnover_cr:
            keep.append(symbol)
    return keep
