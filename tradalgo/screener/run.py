import json
import logging
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import Engine, delete, insert

from tradalgo.clock import to_ist
from tradalgo.config import Settings
from tradalgo.data.universe import Constituent, liquid_symbols
from tradalgo.screener import events
from tradalgo.screener.factors import compute_factors
from tradalgo.screener.rank import ScoredSymbol, rank_candidates
from tradalgo.storage.repo import finish_job_run, start_job_run
from tradalgo.storage.schema import health_events, shortlist

log = logging.getLogger(__name__)


def _next_weekday(d: date) -> date:
    # Holidays are ignored here: blacking out one extra day around a holiday is harmless.
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def run_screen(settings: Settings, engine: Engine, daily_by_symbol: dict[str, pd.DataFrame],
               index_daily: pd.DataFrame, universe: list[Constituent], trade_date: date, now: datetime,
               fetch_events=events.fetch_event_blackout, fetch_news=events.news_sentiment,
               stop_atr_frac: float = 0.3) -> list[ScoredSymbol]:
    """Screen, persist and return the ranked picks for trade_date (rejected symbols are not returned)."""
    cfg = settings.screener
    run_id = start_job_run(engine, "screen", now)
    try:
        prior = {s: df[df.index.date < trade_date] for s, df in daily_by_symbol.items()}
        liquid = set(liquid_symbols(prior, cfg.min_avg_turnover_cr, cfg.min_price))
        blackout, warning = fetch_events(trade_date, _next_weekday(trade_date))
        if warning:
            log.warning(warning)
            with engine.begin() as conn:
                conn.execute(insert(health_events).values(
                    ts=to_ist(now).isoformat(), component="screener", level="warning", message=warning))
        news = {c.symbol: fetch_news(c, now) for c in universe if c.symbol in liquid}
        factors = compute_factors(daily_by_symbol, index_daily, universe, trade_date, news)
        scored = rank_candidates(factors, cfg.factor_weights, liquid, blackout, cfg.shortlist_size, stop_atr_frac)
        picks = [s for s in scored if s.rejected is None]
        with engine.begin() as conn:
            conn.execute(delete(shortlist).where(shortlist.c.trade_date == trade_date.isoformat()))
            for rank, p in enumerate(picks, 1):
                conn.execute(insert(shortlist).values(
                    trade_date=trade_date.isoformat(), rank=rank, symbol=p.symbol,
                    composite_score=p.composite_score,
                    factor_scores_json=json.dumps({**p.factor_scores, "direction": p.direction}),
                    reasons="; ".join(p.reasons), demoted=0,
                ))
    except Exception as exc:
        finish_job_run(engine, run_id, now, error=str(exc))
        raise
    finish_job_run(engine, run_id, now)
    return picks
