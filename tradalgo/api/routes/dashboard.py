from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Engine

from tradalgo.api import services
from fastapi import Request

from tradalgo.api.deps import get_engine, settings_for_request
from tradalgo.api.models import HealthResponse, NowResponse
from tradalgo.api.util import df_records
from tradalgo.clock import IST, MarketCalendar, load_holidays
from tradalgo.config import KeyringStore, Settings
from tradalgo.dashboard import controls, queries

router = APIRouter(prefix="/api", tags=["dashboard"])


def _settings(request: Request) -> Settings:
    return settings_for_request(request)


def _engine(settings: Settings = Depends(_settings)) -> Engine:
    return get_engine(settings)


@router.get("/health", response_model=HealthResponse)
def health(settings: Settings = Depends(_settings)):
    now = datetime.now(IST)
    try:
        holidays = load_holidays(settings.paths.static_dir, now.year)
        calendar = MarketCalendar(settings.market, holidays)
        market_open = calendar.is_market_open(now)
        trading_day = calendar.is_trading_day(now.date())
    except Exception:
        market_open = False
        trading_day = False
    return HealthResponse(
        ok=True,
        db_path=str(settings.paths.db_path),
        market_open=market_open,
        trading_day=trading_day,
        kill_switch=controls.kill_switch_active(settings.paths.data_dir),
        fyers_token_expiry=services.safe_refresh_token_expiry(KeyringStore()),
    )


@router.get("/now", response_model=NowResponse)
def now_strip(date: str | None = Query(default=None), settings: Settings = Depends(_settings),
             engine: Engine = Depends(_engine)):
    trade_date = date or datetime.now(IST).date().isoformat()
    payload = services.now_strip_payload(engine, settings.paths.data_dir, trade_date)
    return NowResponse(**payload)


@router.get("/shortlist")
def shortlist(date: str = Query(...), engine: Engine = Depends(_engine)):
    return df_records(queries.shortlist_for_date(engine, date))


@router.get("/signals")
def signals(date: str = Query(...), engine: Engine = Depends(_engine)):
    return df_records(queries.signals_with_decisions(engine, date))


@router.get("/positions")
def positions(engine: Engine = Depends(_engine)):
    df = queries.trade_positions(engine)
    alerts = queries.alerts_log(engine)
    records = df_records(df)
    if not df.empty:
        for rec, signal_id in zip(records, df["signal_id"]):
            rec["awaiting_reply"] = services.awaiting_reply(alerts, signal_id)
    return records


@router.get("/alerts")
def alerts(status: str | None = None, date: str | None = None, engine: Engine = Depends(_engine)):
    df = queries.alerts_log(engine, status=status, trade_date=date)
    return {"alerts": df_records(df), "counts": services.alert_counts(df)}


@router.get("/journal")
def journal(from_: str | None = Query(default=None, alias="from"), to: str | None = None,
           strategy: str | None = None, symbol: str | None = None, engine: Engine = Depends(_engine)):
    return df_records(queries.journal(engine, date_from=from_, date_to=to, strategy=strategy, symbol=symbol))


@router.get("/analytics")
def analytics(engine: Engine = Depends(_engine)):
    return {
        "expectancy_by_strategy": df_records(queries.expectancy_by(engine, "strategy")),
        "expectancy_by_regime": df_records(queries.expectancy_by(engine, "regime")),
        "expectancy_by_hour": df_records(queries.expectancy_by(engine, "hour")),
        "expectancy_by_symbol": df_records(queries.expectancy_by(engine, "symbol")),
        "mfe_mae_points": df_records(queries.mfe_mae_points(engine)),
        "live_vs_backtest": df_records(queries.live_vs_backtest_expectancy(engine)),
    }


@router.get("/jobs")
def jobs(engine: Engine = Depends(_engine)):
    return {
        "job_runs": df_records(queries.latest_job_runs(engine)),
        "health_events": df_records(queries.health_events(engine)),
        "degraded_data": df_records(queries.degraded_periods(engine, "data")),
        "degraded_socket": df_records(queries.degraded_periods(engine, "socket")),
    }
