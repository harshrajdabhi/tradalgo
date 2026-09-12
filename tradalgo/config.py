from datetime import time
from pathlib import Path
from typing import Literal

import keyring
import yaml
from pydantic import BaseModel, Field, model_validator

KEYRING_SERVICE = "tradalgo"
FACTORS = {
    "momentum_trend", "relative_strength", "volatility", "relative_volume",
    "structure", "level_proximity", "news_sentiment",
}
STRATEGIES = {"orb", "gap", "vwap", "pdhl", "pullback", "range_breakout"}


class CapitalConfig(BaseModel):
    initial_capital: float = Field(gt=0)
    max_risk_pct: float = Field(gt=0, le=0.03)
    max_leverage: float = Field(ge=1, le=5)
    fallback_leverage: float = Field(ge=1, le=5)
    fixed_cost_rupees: float = Field(ge=0)
    max_trades_per_day: int = Field(ge=1, le=2)
    daily_loss_limit_r: float = Field(gt=0)


class ScreenerConfig(BaseModel):
    shortlist_size: int = Field(ge=5, le=7)
    min_avg_turnover_cr: float = Field(ge=0)
    min_price: float = Field(ge=0)
    factor_weights: dict[str, float]

    @model_validator(mode="after")
    def _check_weights(self):
        if set(self.factor_weights) != FACTORS:
            raise ValueError(f"factor_weights keys must be exactly {sorted(FACTORS)}")
        if any(w < 0 for w in self.factor_weights.values()):
            raise ValueError("factor_weights must be non-negative")
        if abs(sum(self.factor_weights.values()) - 1.0) > 1e-6:
            raise ValueError("factor_weights must sum to 1.0")
        return self


class MarketConfig(BaseModel):
    timezone: Literal["Asia/Kolkata"]
    open: time
    close: time
    no_new_entries_after: time
    hard_exit: time

    @model_validator(mode="after")
    def _check_order(self):
        if not (self.open < self.no_new_entries_after < self.hard_exit < self.close):
            raise ValueError("market times must satisfy open < no_new_entries_after < hard_exit < close")
        return self


class StrategyConfig(BaseModel):
    enabled: bool
    window_start: time
    window_end: time


class PositionConfig(BaseModel):
    partial_exit_at_r: float = Field(gt=0)
    partial_exit_fraction: float = Field(gt=0, lt=1)
    trail_method: Literal["swing_structure", "atr_multiple"]


class BacktestConfig(BaseModel):
    slippage_pct: float = Field(ge=0)


class PathsConfig(BaseModel):
    data_dir: Path
    static_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "tradalgo.db"


class Settings(BaseModel):
    capital: CapitalConfig
    screener: ScreenerConfig
    market: MarketConfig
    strategies: dict[str, StrategyConfig]
    position_management: PositionConfig
    backtest: BacktestConfig
    paths: PathsConfig

    @model_validator(mode="after")
    def _check_strategies(self):
        if set(self.strategies) != STRATEGIES:
            raise ValueError(f"strategies keys must be exactly {sorted(STRATEGIES)}")
        for name, s in self.strategies.items():
            if not (self.market.open <= s.window_start < s.window_end <= self.market.no_new_entries_after):
                raise ValueError(f"strategy {name}: window must lie within open..no_new_entries_after")
        return self


def load_settings(path: str | Path = "config.yaml") -> Settings:
    with open(path) as f:
        return Settings.model_validate(yaml.safe_load(f))


def get_secret(name: str) -> str:
    value = keyring.get_password(KEYRING_SERVICE, name)
    if value is None:
        raise KeyError(f"secret {name!r} not found in keychain service {KEYRING_SERVICE!r}")
    return value
