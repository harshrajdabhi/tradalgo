import ast
from datetime import date, datetime
from pathlib import Path

import pytest
from fyers_apiv3.fyersModel import FyersModel

from tradalgo.clock import IST
from tradalgo.data.base import ProviderError
from tradalgo.data.fyers_provider import FyersProvider, to_fyers_symbol
from tests.conftest import ROOT


class FakeClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def history(self, data):
        self.calls.append(data)
        return self.responses.pop(0)


def epoch(*args) -> int:
    return int(datetime(*args, tzinfo=IST).timestamp())


def provider(client):
    return FyersProvider(client, min_request_interval=0, sleep=lambda s: None)


def test_symbol_mapping():
    assert to_fyers_symbol("RELIANCE") == "NSE:RELIANCE-EQ"
    assert to_fyers_symbol("NIFTY50") == "NSE:NIFTY50-INDEX"


def test_candles_parsed_to_ist_frame():
    client = FakeClient({"s": "ok", "candles": [
        [epoch(2026, 9, 11, 9, 20), 101, 102, 100, 101.5, 900],
        [epoch(2026, 9, 11, 9, 15), 100, 101, 99, 100.5, 1000],
    ]})
    df = provider(client).get_candles("SBIN", "5m", date(2026, 9, 11), date(2026, 9, 11))
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index[0] == datetime(2026, 9, 11, 9, 15, tzinfo=IST)
    assert df.iloc[0]["close"] == 100.5
    assert client.calls[0] == {"symbol": "NSE:SBIN-EQ", "resolution": "5", "date_format": 1,
                               "range_from": "2026-09-11", "range_to": "2026-09-11", "cont_flag": 1}


def test_intraday_history_chunked_to_100_days():
    client = FakeClient({"s": "ok", "candles": []}, {"s": "no_data", "candles": []})
    df = provider(client).get_candles("SBIN", "5m", date(2026, 1, 1), date(2026, 6, 30))
    assert df.empty
    assert [(c["range_from"], c["range_to"]) for c in client.calls] == [
        ("2026-01-01", "2026-04-10"), ("2026-04-11", "2026-06-30"),
    ]


def test_api_error_raises():
    client = FakeClient({"s": "error", "message": "invalid token"})
    with pytest.raises(ProviderError, match="invalid token"):
        provider(client).get_candles("SBIN", "1d", date(2026, 9, 1), date(2026, 9, 11))


def test_package_never_references_fyers_order_methods():
    order_words = ("order", "position", "exit", "gtt", "basket", "alert", "smart", "funds", "holdings")
    forbidden = {m for m in dir(FyersModel) if not m.startswith("_") and any(w in m for w in order_words)}
    assert "place_order" in forbidden

    used = set()
    for path in Path(ROOT / "tradalgo").rglob("*.py"):
        used |= {n.attr for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Attribute)}
    assert not (used & forbidden)
