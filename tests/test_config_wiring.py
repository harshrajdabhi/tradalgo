import pytest
from pydantic import ValidationError

from tradalgo.config import Settings, load_leverage_overrides
from tests.conftest import ROOT


def test_shipped_config_has_new_sections(settings):
    assert settings.risk.win_prob == 0.40
    assert settings.risk.runner_avg_r == 2.0
    assert settings.risk.min_room_r == 2.0
    assert settings.risk.band_fraction_r == 0.1
    assert settings.risk.trail_bars == 3
    assert settings.preopen.max_gap_atr == 0.75
    assert settings.preopen.oppose_gap_atr == 0.5
    assert settings.telegram.enabled is True
    assert settings.dashboard.host == "127.0.0.1"
    assert settings.dashboard.port == 8501
    assert settings.screener.stop_atr_frac == 0.3
    assert settings.screener.trigger_zone_atr == 0.25
    assert settings.screener.min_room_r == 2.0


def test_new_sections_are_optional_for_backward_compatibility(raw_config):
    for key in ("risk", "preopen", "telegram", "dashboard"):
        raw_config.pop(key, None)
    for key in ("stop_atr_frac", "trigger_zone_atr", "min_room_r"):
        raw_config["screener"].pop(key, None)
    s = Settings.model_validate(raw_config)
    assert s.risk.win_prob == 0.40
    assert s.dashboard.port == 8501
    assert s.screener.stop_atr_frac == 0.3


@pytest.mark.parametrize("mutate, message", [
    (lambda c: c["risk"].update(win_prob=0), "win_prob"),
    (lambda c: c["risk"].update(win_prob=1), "win_prob"),
    (lambda c: c["risk"].update(trail_bars=0), "trail_bars"),
    (lambda c: c["dashboard"].update(host="0.0.0.0"), "loopback"),
    (lambda c: c["dashboard"].update(port=0), "port"),
])
def test_invalid_new_sections_rejected(raw_config, mutate, message):
    raw_config.setdefault("risk", {"win_prob": 0.4, "runner_avg_r": 2.0, "min_room_r": 2.0,
                                   "band_fraction_r": 0.1, "trail_bars": 3})
    raw_config.setdefault("dashboard", {"host": "127.0.0.1", "port": 8501})
    mutate(raw_config)
    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(raw_config)


def test_load_leverage_overrides_returns_dict():
    overrides = load_leverage_overrides(ROOT / "data_static")
    assert isinstance(overrides, dict)


def test_load_leverage_overrides_missing_file_returns_empty(tmp_path):
    assert load_leverage_overrides(tmp_path) == {}


def test_load_leverage_overrides_reads_symbol_values(tmp_path):
    (tmp_path / "mis_leverage.yaml").write_text("overrides:\n  RELIANCE: 4\n  TATASTEEL: 5\n")
    assert load_leverage_overrides(tmp_path) == {"RELIANCE": 4, "TATASTEEL": 5}
