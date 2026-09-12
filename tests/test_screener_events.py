from datetime import date, datetime

import pytest

from tradalgo.clock import IST
from tradalgo.data.universe import Constituent
from tradalgo.screener import events


class FakeResp:
    def __init__(self, text="", data=None, status=200):
        self.text, self._data, self.status_code = text, data, status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttp:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        for prefix, resp in sorted(self.responses.items(), key=lambda kv: -len(kv[0])):
            if url.startswith(prefix):
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected url {url}")


def test_event_blackout_today_and_next_day_after_cookie_warmup():
    data = [
        {"symbol": "TCS", "purpose": "Financial Results", "date": "11-Sep-2026"},
        {"symbol": "INFY", "purpose": "Board Meeting", "date": "14-Sep-2026"},
        {"symbol": "HDFCBANK", "purpose": "Dividend", "date": "20-Sep-2026"},
    ]
    http = FakeHttp({events.NSE_EVENTS_URL: FakeResp(data=data), events.NSE_HOME: FakeResp("ok")})
    symbols, warning = events.fetch_event_blackout(date(2026, 9, 11), date(2026, 9, 14), http=http)
    assert symbols == {"TCS", "INFY"}
    assert warning is None
    assert http.calls[0][0] == events.NSE_HOME
    assert "User-Agent" in http.calls[0][1]["headers"]


def test_event_blackout_fails_open_with_warning():
    http = FakeHttp({events.NSE_HOME: FakeResp("ok"), events.NSE_EVENTS_URL: FakeResp(status=401)})
    symbols, warning = events.fetch_event_blackout(date(2026, 9, 11), date(2026, 9, 14), http=http)
    assert symbols == set()
    assert "event calendar" in warning


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Tata Consultancy shares surge after record profit</title><pubDate>Thu, 10 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>TCS wins major deal, upgrade by brokers</title><pubDate>Wed, 09 Sep 2026 10:00:00 GMT</pubDate></item>
<item><title>TCS stock falls on probe</title><pubDate>Mon, 01 Sep 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""

NOW = datetime(2026, 9, 11, 7, 0, tzinfo=IST)
TCS = Constituent("TCS", "Tata Consultancy Services Ltd.", "IT", "nifty50")


def test_news_sentiment_scores_recent_headlines_only():
    http = FakeHttp({events.GOOGLE_NEWS_RSS: FakeResp(RSS)})
    score = events.news_sentiment(TCS, NOW, http=http)
    assert score > 50
    assert "Tata" in http.calls[0][1]["params"]["q"]
    assert score == pytest.approx(100.0)  # old negative headline ignored


def test_news_sentiment_neutral_on_failure_or_no_headlines():
    assert events.news_sentiment(TCS, NOW, http=FakeHttp({events.GOOGLE_NEWS_RSS: RuntimeError("down")})) == 50.0
    empty = "<rss><channel></channel></rss>"
    assert events.news_sentiment(TCS, NOW, http=FakeHttp({events.GOOGLE_NEWS_RSS: FakeResp(empty)})) == 50.0


def test_headline_score_lexicon():
    assert events.score_headlines(["shares plunge after fraud probe"]) < 50
    assert events.score_headlines(["nothing notable"]) == 50.0
