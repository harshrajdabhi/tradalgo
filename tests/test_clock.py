from datetime import date, datetime, timedelta, timezone

import pytest

from tradalgo.clock import IST, FixedClock, MarketCalendar, load_holidays
from tests.conftest import ROOT


@pytest.fixture
def cal(settings):
    return MarketCalendar(settings.market, load_holidays(ROOT / "data_static", 2026))


def ist(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=IST)


def test_weekend_and_holiday_are_not_trading_days(cal):
    assert cal.is_trading_day(date(2026, 9, 11))       # Friday
    assert not cal.is_trading_day(date(2026, 9, 12))   # Saturday
    assert not cal.is_trading_day(date(2026, 10, 2))   # Gandhi Jayanti


@pytest.mark.parametrize("dt, expected", [
    (ist(2026, 9, 11, 9, 14, 59), False),
    (ist(2026, 9, 11, 9, 15), True),
    (ist(2026, 9, 11, 15, 29, 59), True),
    (ist(2026, 9, 11, 15, 30), False),
    (ist(2026, 10, 2, 11, 0), False),
])
def test_market_open_boundaries(cal, dt, expected):
    assert cal.is_market_open(dt) is expected


def test_market_open_converts_other_timezones(cal):
    assert cal.is_market_open(datetime(2026, 9, 11, 3, 45, tzinfo=timezone.utc))  # 09:15 IST


def test_naive_datetime_rejected(cal):
    with pytest.raises(ValueError, match="naive"):
        cal.is_market_open(datetime(2026, 9, 11, 10, 0))
    with pytest.raises(ValueError, match="naive"):
        FixedClock(datetime(2026, 9, 11, 10, 0))


def test_entry_windows(cal, settings):
    orb = settings.strategies["orb"]
    vwap = settings.strategies["vwap"]
    assert not cal.can_enter(ist(2026, 9, 11, 9, 25), orb)
    assert cal.can_enter(ist(2026, 9, 11, 9, 30), orb)
    assert not cal.can_enter(ist(2026, 9, 11, 11, 0), orb)
    assert cal.can_enter(ist(2026, 9, 11, 13, 59, 59), vwap)
    assert not cal.can_enter(ist(2026, 9, 11, 14, 0), vwap)
    assert not cal.can_enter(ist(2026, 9, 11, 10, 0), orb.model_copy(update={"enabled": False}))


def test_hard_exit(cal):
    assert not cal.is_past_hard_exit(ist(2026, 9, 11, 14, 59, 59))
    assert cal.is_past_hard_exit(ist(2026, 9, 11, 15, 0))


def test_missing_holiday_file_warns(tmp_path):
    with pytest.warns(UserWarning, match="2031"):
        assert load_holidays(tmp_path, 2031) == set()


def test_fixed_clock_advances():
    clock = FixedClock(ist(2026, 9, 11, 9, 15))
    clock.advance(timedelta(minutes=5))
    assert clock.now() == ist(2026, 9, 11, 9, 20)
