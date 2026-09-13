from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Engine

from tradalgo.api import services
from tradalgo.api.deps import get_engine, settings_for_request
from tradalgo.api.util import is_valid_symbol
from tradalgo.clock import IST
from tradalgo.config import Settings
from tradalgo.dashboard import queries
from tradalgo.data.candle_cache import CandleCache

router = APIRouter(prefix="/api/candles", tags=["candles"])


def _settings(request: Request) -> Settings:
    return settings_for_request(request)


def _engine(settings: Settings = Depends(_settings)) -> Engine:
    return get_engine(settings)


@router.get("/{symbol}")
def get_candles(symbol: str, date: str | None = Query(default=None), engine: Engine = Depends(_engine),
                settings: Settings = Depends(_settings)):
    if not is_valid_symbol(symbol):
        raise HTTPException(status_code=404, detail=f"invalid symbol {symbol!r}")
    trade_date = date or datetime.now(IST).date().isoformat()
    day = datetime.fromisoformat(trade_date).date()

    cache = CandleCache(settings.paths.data_dir / "candles", provider=None)
    candles = services.day_candles(cache, symbol, day)

    sig_df = queries.signals_with_decisions(engine, trade_date)
    levels = {"entry": None, "stop": None, "target_partial": None, "target_runner": None}
    if not sig_df.empty:
        rows = sig_df[sig_df["symbol"] == symbol]
        if not rows.empty:
            sig = rows.iloc[0]
            levels = {"entry": sig.get("entry"), "stop": sig.get("stop_loss"),
                     "target_partial": sig.get("target_2r"), "target_runner": sig.get("target_3r")}

    return {
        "candles": services.candles_to_json(candles),
        "session_vwap": services.vwap_to_json(candles),
        "levels": levels,
    }
