import warnings
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

import yaml

from tradalgo.config import MarketConfig, StrategyConfig

IST = ZoneInfo("Asia/Kolkata")


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(IST)


class FixedClock:
    def __init__(self, dt: datetime):
        self._dt = to_ist(dt)

    def now(self) -> datetime:
        return self._dt

    def advance(self, delta: timedelta) -> None:
        self._dt += delta


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("naive datetime not allowed; use a timezone-aware datetime")
    return dt.astimezone(IST)


def load_holidays(static_dir: str | Path, year: int) -> set[date]:
    path = Path(static_dir) / f"nse_holidays_{year}.yaml"
    if not path.exists():
        warnings.warn(f"NSE holiday list missing for {year} ({path}); only weekends treated as closed")
        return set()
    with open(path) as f:
        return {date.fromisoformat(str(d)) for d in yaml.safe_load(f)["holidays"]}


class MarketCalendar:
    def __init__(self, market: MarketConfig, holidays: set[date]):
        self.market = market
        self.holidays = holidays

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def is_market_open(self, dt: datetime) -> bool:
        dt = to_ist(dt)
        return self.is_trading_day(dt.date()) and self.market.open <= dt.time() < self.market.close

    def can_enter(self, dt: datetime, strategy: StrategyConfig) -> bool:
        dt = to_ist(dt)
        t = dt.time()
        return (
            strategy.enabled
            and self.is_market_open(dt)
            and strategy.window_start <= t < strategy.window_end
            and t < self.market.no_new_entries_after
        )

    def is_past_hard_exit(self, dt: datetime) -> bool:
        return to_ist(dt).time() >= self.market.hard_exit
