import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime

import requests

from tradalgo.clock import to_ist
from tradalgo.data.universe import Constituent

NSE_HOME = "https://www.nseindia.com"
NSE_EVENTS_URL = "https://www.nseindia.com/api/event-calendar"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-event-calendar",
}

POSITIVE = {
    "surge", "surges", "surged", "jump", "jumps", "jumped", "rally", "rallies", "rallied", "gain", "gains",
    "soar", "soars", "soared", "record", "beat", "beats", "upgrade", "upgraded", "win", "wins", "won",
    "profit", "rise", "rises", "rose", "bullish", "outperform", "strong", "growth", "deal", "order",
    "orders", "approval", "approves", "buyback", "dividend", "expansion", "high",
}
NEGATIVE = {
    "fall", "falls", "fell", "plunge", "plunges", "plunged", "slump", "slumps", "drop", "drops", "dropped",
    "decline", "declines", "loss", "losses", "downgrade", "downgraded", "miss", "misses", "probe", "fraud",
    "penalty", "raid", "weak", "bearish", "resigns", "resignation", "default", "cut", "cuts", "lawsuit",
    "ban", "crash", "crashes", "slips", "tumbles", "low", "concern", "concerns", "sebi",
}


def fetch_event_blackout(trade_date: date, next_trading_day: date, http=None) -> tuple[set[str], str | None]:
    """Symbols with a corporate event (results/board meeting etc.) on trade_date or next_trading_day.

    Fails open: on any failure returns an empty set plus a warning that callers must surface.
    """
    http = http or requests.Session()
    try:
        # NSE rejects API calls without the cookies set by the home page.
        http.get(NSE_HOME, headers=BROWSER_HEADERS, timeout=15)
        resp = http.get(NSE_EVENTS_URL, headers=BROWSER_HEADERS, timeout=15, params={
            "index": "equities",
            "from_date": trade_date.strftime("%d-%m-%Y"),
            "to_date": next_trading_day.strftime("%d-%m-%Y"),
        })
        resp.raise_for_status()
        days = {trade_date, next_trading_day}
        return {
            row["symbol"].strip() for row in resp.json()
            if datetime.strptime(row["date"], "%d-%b-%Y").date() in days
        }, None
    except Exception as exc:  # network/format/anti-bot failures must not stop the screen
        return set(), f"NSE event calendar unavailable ({exc}); earnings blackout NOT applied"


def score_headlines(headlines: list[str]) -> float:
    pos = neg = 0
    for h in headlines:
        words = re.findall(r"[a-z]+", h.lower())
        pos += sum(w in POSITIVE for w in words)
        neg += sum(w in NEGATIVE for w in words)
    if pos + neg == 0:
        return 50.0
    return 50.0 + 50.0 * (pos - neg) / (pos + neg)


def news_sentiment(constituent: Constituent, now: datetime, http=None, lookback_days: int = 3) -> float:
    """Keyword sentiment 0..100 of Google News headlines from the last `lookback_days`; 50 on none/failure."""
    http = http or requests
    try:
        resp = http.get(GOOGLE_NEWS_RSS, timeout=15, headers={"User-Agent": BROWSER_HEADERS["User-Agent"]}, params={
            "q": f"{constituent.company} NSE", "hl": "en-IN", "gl": "IN", "ceid": "IN:en",
        })
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        now_ist = to_ist(now)
        titles = []
        for item in root.iter("item"):
            title, pub = item.findtext("title"), item.findtext("pubDate")
            if not title or not pub:
                continue
            published = to_ist(parsedate_to_datetime(pub))
            if now_ist - timedelta(days=lookback_days) <= published <= now_ist:
                titles.append(title)
        return score_headlines(titles)
    except Exception:  # sentiment is optional context; neutral beats failing the screen
        return 50.0
