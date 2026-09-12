"""09:08 pre-open pass. Never adds symbols.

Demotion rule: gap_atr = (preopen - prev_close) / daily ATR. A pick is demoted when |gap_atr| > max_gap_atr
(the expected move is already used up), or when the gap opposes the bias by more than oppose_gap_atr
(long with gap_atr < -oppose_gap_atr, short with gap_atr > +oppose_gap_atr).
"""
import json
from datetime import date, datetime

from sqlalchemy import Engine, select, update

from tradalgo.clock import IST
from tradalgo.storage.repo import finish_job_run, start_job_run
from tradalgo.storage.schema import shortlist


def annotate_preopen(engine: Engine, trade_date: date, preopen_prices: dict[str, float],
                     prev_close: dict[str, float], daily_atr: dict[str, float], max_gap_atr: float = 0.75,
                     oppose_gap_atr: float = 0.5, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(IST)
    run_id = start_job_run(engine, "preopen", now)
    out = []
    try:
        with engine.begin() as conn:
            rows = conn.execute(select(shortlist.c.id, shortlist.c.symbol, shortlist.c.factor_scores_json)
                                .where(shortlist.c.trade_date == trade_date.isoformat())
                                .order_by(shortlist.c.rank)).all()
            for row_id, symbol, scores_json in rows:
                direction = json.loads(scores_json).get("direction")
                price, pc, atr = preopen_prices.get(symbol), prev_close.get(symbol), daily_atr.get(symbol)
                result = {"symbol": symbol, "direction": direction, "gap_pct": None, "gap_atr": None,
                          "demoted": False, "reason": None}
                if price is not None and pc:
                    result["gap_pct"] = (price - pc) / pc * 100
                    if atr:
                        gap_atr = (price - pc) / atr
                        result["gap_atr"] = gap_atr
                        if abs(gap_atr) > max_gap_atr:
                            result.update(demoted=True, reason=f"gap {gap_atr:+.2f} ATR used up expected move")
                        elif (direction == "long" and gap_atr < -oppose_gap_atr) or \
                                (direction == "short" and gap_atr > oppose_gap_atr):
                            result.update(demoted=True, reason=f"gap {gap_atr:+.2f} ATR against {direction} bias")
                    conn.execute(update(shortlist).where(shortlist.c.id == row_id).values(
                        gap_pct=result["gap_pct"], demoted=int(result["demoted"])))
                out.append(result)
    except Exception as exc:
        finish_job_run(engine, run_id, now, error=str(exc))
        raise
    finish_job_run(engine, run_id, now)
    return out
