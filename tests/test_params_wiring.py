from datetime import timedelta

import pytest
from pydantic import ValidationError

from tests.conftest import ROOT
from tests.strategy_fixtures import at, ctx_at, with_today
from tests.test_positions import at as pat, kinds, plan
from tests.test_strategies_gap import CONT, FIRST15
from tests.test_strategies_orb import OR_ROWS, TRIGGER
from tradalgo.clock import MarketCalendar, load_holidays
from tradalgo.config import Settings, settings_with_overrides
from tradalgo.engine.positions import PositionManager
from tradalgo.strategies import registry
from tradalgo.strategies.base import Regime
from tradalgo.strategies.registry import PARAM_DEFAULTS, detect_all

UP = Regime.TREND_UP


@pytest.fixture
def calendar(settings):
    return MarketCalendar(settings.market, load_holidays(ROOT / "data_static", 2026))


def names(signals):
    return {s.strategy for s in signals}


def test_every_detector_declares_defaults_matching_its_fields():
    assert set(PARAM_DEFAULTS) == set(registry.ALL_DETECTORS)
    for name, defaults in PARAM_DEFAULTS.items():
        det = registry.ALL_DETECTORS[name]
        assert defaults and all(getattr(det, k) == v for k, v in defaults.items())
        assert "min_stop_atr" not in defaults and "name" not in defaults


def test_orb_threshold_from_config_flips_trigger(settings, calendar):
    ctx = ctx_at(with_today(OR_ROWS + [TRIGGER]), at(9, 40), regime=UP, market_regime=UP)
    assert "orb" in names(detect_all(ctx, settings, calendar))
    s = settings_with_overrides(settings, {"strategies": {"orb": {"params": {"min_rvol": 1000.0}}}})
    assert "orb" not in names(detect_all(ctx, s, calendar))


def test_gap_threshold_from_config_flips_trigger(settings, calendar):
    ctx = ctx_at(with_today(FIRST15 + [CONT]), at(9, 40), regime=UP, market_regime=UP)
    assert "gap" in names(detect_all(ctx, settings, calendar))
    s = settings_with_overrides(settings, {"strategies": {"gap": {"params": {"min_gap_pct": 50}}}})
    assert "gap" not in names(detect_all(ctx, s, calendar))


def test_params_and_stop_bounds_reach_every_detector(settings, calendar, monkeypatch):
    seen = {}

    def spy(name):
        def call(self, ctx):
            seen[name] = self
            return None
        return call

    for name, det in registry.ALL_DETECTORS.items():
        monkeypatch.setattr(type(det), "__call__", spy(name))
    overrides = {"strategies": {n: {"params": {k: v * 2 for k, v in list(d.items())[:1]}}
                                for n, d in PARAM_DEFAULTS.items()},
                 "position_management": {"stop_atr_min": 0.25, "stop_atr_max": 3.0}}
    s = settings_with_overrides(settings, overrides)
    for regime in (UP, Regime.RANGE):
        detect_all(ctx_at(with_today(OR_ROWS + [TRIGGER]), at(9, 40), regime=regime, market_regime=regime),
                   s, calendar)
    assert set(seen) == set(PARAM_DEFAULTS)
    for name, det in seen.items():
        key, value = next(iter(overrides["strategies"][name]["params"].items()))
        assert getattr(det, key) == value and type(getattr(det, key)) is type(PARAM_DEFAULTS[name][key])
        assert (det.min_stop_atr, det.max_stop_atr) == (0.25, 3.0)


def test_unknown_strategy_param_names_strategy_and_key(raw_config):
    raw_config["strategies"]["orb"]["params"] = {"rvol_minn": 2.0}
    with pytest.raises(ValidationError, match=r"strategy orb: unknown param 'rvol_minn'"):
        Settings.model_validate(raw_config)


@pytest.mark.parametrize("params, message", [
    ({"min_rvol": "high"}, "min_rvol"),
    ({"min_rvol": True}, "must be a number"),
    ({"or_minutes": 15.5}, "must be an integer"),
])
def test_bad_param_types_rejected(raw_config, params, message):
    raw_config["strategies"]["orb"]["params"] = params
    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(raw_config)


def test_integral_float_for_int_param_is_coerced(raw_config):
    raw_config["strategies"]["orb"]["params"] = {"or_minutes": 30.0}
    assert type(Settings.model_validate(raw_config).strategies["orb"].params["or_minutes"]) is int


@pytest.mark.parametrize("pm, message", [
    ({"partial_exit_fraction": 1.0}, "partial_exit_fraction"),
    ({"partial_exit_fraction": 0}, "partial_exit_fraction"),
    ({"stop_atr_min": 2.0, "stop_atr_max": 2.0}, "stop_atr_min must be less"),
    ({"runner_target_r": 2.0}, "runner_target_r must be greater"),
    ({"partial_exit_at_r": "x"}, "partial_exit_at_r"),
])
def test_position_bounds_rejected(raw_config, pm, message):
    raw_config["position_management"].update(pm)
    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(raw_config)


def test_regime_section_optional_with_identical_defaults(raw_config):
    raw_config.pop("regime")
    assert Settings.model_validate(raw_config).regime == Settings.model_validate(
        {**raw_config, "regime": {}}).regime
    assert Settings.model_validate(raw_config).regime.adx_trend == 25.0


def test_regime_params_reach_classify(settings):
    import inspect
    from tradalgo.regime import classify
    assert set(settings.regime.model_dump()) <= set(inspect.signature(classify).parameters)
    for k, v in settings.regime.model_dump().items():
        assert inspect.signature(classify).parameters[k].default == v


def test_settings_with_overrides_validates_and_does_not_mutate(settings):
    before = settings.model_dump()
    s = settings_with_overrides(settings, {"strategies": {"orb": {"enabled": False, "params": {"min_rvol": 2}}},
                                           "position_management": {"partial_exit_at_r": 1.5}})
    assert s.strategies["orb"].enabled is False and s.strategies["orb"].params == {"min_rvol": 2.0}
    assert s.position_management.partial_exit_at_r == 1.5
    assert settings.model_dump() == before
    with pytest.raises(ValidationError, match="partial_exit_fraction"):
        settings_with_overrides(settings, {"position_management": {"partial_exit_fraction": 2}})
    with pytest.raises(ValueError, match="unknown settings key 'position_management.partial_at_r'"):
        settings_with_overrides(settings, {"position_management": {"partial_at_r": 1.5}})
    with pytest.raises(ValidationError, match="strategy gap: unknown param"):
        settings_with_overrides(settings, {"strategies": {"gap": {"params": {"nope": 1}}}})


def test_default_settings_round_trip_unchanged(settings):
    assert settings_with_overrides(settings, {}) == settings


def test_partial_fires_at_configured_r():
    pm = PositionManager(partial_at_r=1.5)
    pm.open(1, plan())                                      # entry 100, stop 98 -> 1.5R = 103
    ev = pm.on_price(pat(10, 5), 103.0, 99.5, 102.5, True)
    partial = ev[kinds(ev).index("partial_exit")]
    assert (partial.price, partial.r_multiple, partial.qty) == (103.0, 1.5, 6)
    assert PositionManager().on_price(pat(10, 5), 103.0, 99.5, 102.5, True) == []


def test_runner_target_configurable():
    pm = PositionManager(runner_target_r=4.0)
    pm.open(1, plan())
    ev = pm.on_price(pat(10, 5), 106.5, 100.5, 106.0, True)   # past 3R, short of 4R
    assert "runner_exit" not in kinds(ev)
    ev = pm.on_price(pat(10, 10), 108.0, 106.0, 107.5, True)
    assert kinds(ev)[-1] == "runner_exit" and ev[-1].price == 108.0


def test_no_breakeven_keeps_original_stop_after_partial():
    pm = PositionManager(breakeven_after_partial=False, trail_bars=50)
    pm.open(1, plan())
    ev = pm.on_price(pat(10, 5), 104.0, 100.5, 103.5, True)
    assert kinds(ev) == ["partial_exit"]
    assert pm.to_dict()["trades"][0]["stop"] == 98.0
    ev = pm.on_price(pat(10, 10), 103.0, 99.0, 99.5, True)   # would have stopped at breakeven 100
    assert ev == []


def test_position_params_survive_state_round_trip():
    pm = PositionManager(partial_at_r=1.5, runner_target_r=2.5, breakeven_after_partial=False)
    back = PositionManager.from_dict(pm.to_dict())
    assert (back.partial_at_r, back.runner_target_r, back.breakeven_after_partial) == (1.5, 2.5, False)
    legacy = {k: v for k, v in pm.to_dict().items()
              if k not in ("partial_at_r", "runner_target_r", "breakeven_after_partial")}
    old = PositionManager.from_dict(legacy)
    assert (old.partial_at_r, old.runner_target_r, old.breakeven_after_partial) == (2.0, 3.0, True)


def test_cycle_builds_manager_and_plan_targets_from_config(settings):
    from tradalgo.engine.cycle import SessionState, open_position
    from tradalgo.risk.validator import validate
    from tradalgo.risk.limits import DailyRiskState
    s = settings_with_overrides(settings, {"position_management": {
        "partial_exit_at_r": 1.5, "runner_target_r": 2.5, "breakeven_after_partial": False}})
    sig = plan().signal
    tp = validate(sig, capital=1e6, capital_cfg=s.capital, costs_cfg=s.costs, symbol_leverage=5.0, levels=[],
                  limits_state=DailyRiskState(sig.ts.date()), partial_at_r=1.5, runner_target_r=2.5)
    assert (tp.target_2r, tp.target_3r) == (103.0, 105.0)
    state = SessionState.new(sig.ts.date(), 1e6)
    open_position(state, tp, 7, s)
    pm = state.position_manager["SBIN"]
    assert (pm.partial_at_r, pm.runner_target_r, pm.breakeven_after_partial) == (1.5, 2.5, False)
    assert tp.valid_until == sig.ts + timedelta(minutes=10)
