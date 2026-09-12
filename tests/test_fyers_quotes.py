import pytest

from tradalgo.data.base import ProviderError
from tradalgo.data.fyers_provider import FyersProvider


class FakeQuoteClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def quotes(self, data):
        self.calls.append(data)
        return self.responses.pop(0)


def provider(client):
    return FyersProvider(client, min_request_interval=0, sleep=lambda s: None)


def test_get_quotes_parses_last_price():
    client = FakeQuoteClient({"s": "ok", "d": [
        {"n": "NSE:RELIANCE-EQ", "v": {"lp": 2500.5}},
        {"n": "NSE:TCS-EQ", "v": {"lp": 3800.0}},
    ]})
    quotes = provider(client).get_quotes(["RELIANCE", "TCS"])
    assert quotes == {"RELIANCE": 2500.5, "TCS": 3800.0}
    assert client.calls[0] == {"symbols": "NSE:RELIANCE-EQ,NSE:TCS-EQ"}


def test_get_quotes_omits_missing_symbols():
    client = FakeQuoteClient({"s": "ok", "d": [{"n": "NSE:RELIANCE-EQ", "v": {"lp": 2500.5}}]})
    quotes = provider(client).get_quotes(["RELIANCE", "TCS"])
    assert quotes == {"RELIANCE": 2500.5}


def test_get_quotes_raises_on_error_status():
    client = FakeQuoteClient({"s": "error", "message": "bad request"})
    with pytest.raises(ProviderError, match="bad request"):
        provider(client).get_quotes(["RELIANCE"])


def test_get_quotes_batches_over_50_symbols():
    symbols = [f"SYM{i}" for i in range(120)]
    client = FakeQuoteClient(
        {"s": "ok", "d": [{"n": f"NSE:{s}-EQ", "v": {"lp": 1.0}} for s in symbols[:50]]},
        {"s": "ok", "d": [{"n": f"NSE:{s}-EQ", "v": {"lp": 2.0}} for s in symbols[50:100]]},
        {"s": "ok", "d": [{"n": f"NSE:{s}-EQ", "v": {"lp": 3.0}} for s in symbols[100:]]},
    )
    quotes = provider(client).get_quotes(symbols)
    assert len(client.calls) == 3
    assert all(len(c["symbols"].split(",")) <= 50 for c in client.calls)
    assert quotes["SYM0"] == 1.0
    assert quotes["SYM119"] == 3.0
