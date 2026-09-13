"""Pydantic response/request models. Tabular DB results (shortlist, signals, positions, alerts,
journal, trades) are returned as list[dict] since their column sets are read straight off the
existing dashboard/queries.py SQL and are documented in the B1 report; wrapping every one in a
bespoke model would just restate that SQL.
"""
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    ok: bool
    db_path: str
    market_open: bool
    trading_day: bool
    kill_switch: bool
    fyers_token_expiry: str | None = None


class NowResponse(BaseModel):
    headline: str
    quiet: bool


class KillSwitchRequest(BaseModel):
    on: bool


class BacktestParams(BaseModel):
    from_: str = Field(alias="from")
    to: str
    universe: str
    strategies: list[str]
    shortlist_size: int
    slippage_pct: float
    max_risk_pct: float
    initial_capital: float

    model_config = {"populate_by_name": True}

    def to_dict(self) -> dict:
        return {
            "from": self.from_, "to": self.to, "universe": self.universe,
            "strategies": self.strategies, "shortlist_size": self.shortlist_size,
            "slippage_pct": self.slippage_pct, "max_risk_pct": self.max_risk_pct,
            "initial_capital": self.initial_capital,
        }


class GateResult(BaseModel):
    passed: bool
    reason: str
