import pandas as pd

from tradalgo.data.universe import liquid_symbols, load_universe, refresh_constituents
from tests.conftest import ROOT


def test_committed_universe_has_both_indices():
    universe = load_universe(ROOT / "data_static")
    assert sum(c.index == "nifty50" for c in universe) == 50
    assert sum(c.index == "niftynext50" for c in universe) == 50
    assert len({c.symbol for c in universe}) == 100


def test_refresh_keeps_existing_list_on_bad_download(tmp_path):
    for name in ("nifty50", "niftynext50"):
        (tmp_path / f"{name}.csv").write_text((ROOT / "data_static" / f"{name}.csv").read_text())
    bad = "Company Name,Industry,Symbol,Series,ISIN Code\nOnly One,IT,ONE,EQ,X\n"

    def fetch(url):
        if "next50" in url:
            raise ConnectionError("offline")
        return bad

    problems = refresh_constituents(tmp_path, fetch=fetch)
    assert len(problems) == 2
    assert len(load_universe(tmp_path)) == 100


def test_liquidity_filter():
    def frame(close, volume, days=20):
        return pd.DataFrame({"close": [close] * days, "volume": [volume] * days})

    daily = {
        "LIQUID": frame(1000, 1_000_000),     # ₹100 cr/day
        "THIN": frame(1000, 100_000),         # ₹10 cr/day
        "PENNY": frame(40, 200_000_000),      # liquid but below min price
        "NEWLIST": frame(1000, 1_000_000, days=5),
    }
    assert liquid_symbols(daily, min_turnover_cr=50, min_price=50) == ["LIQUID"]
