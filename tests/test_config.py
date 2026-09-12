import pytest
from pydantic import ValidationError

from tradalgo import config
from tradalgo.config import Settings, get_secret, load_settings
from tests.conftest import ROOT


def test_shipped_config_loads_spec_values():
    s = load_settings(ROOT / "config.yaml")
    assert s.capital.initial_capital == 20000
    assert s.capital.max_risk_pct == 0.03
    assert s.capital.max_leverage == 5
    assert s.capital.fixed_cost_rupees == 50
    assert s.capital.max_trades_per_day == 2
    assert s.screener.shortlist_size == 6
    assert s.position_management.partial_exit_fraction == 0.6


@pytest.mark.parametrize("mutate, message", [
    (lambda c: c["screener"]["factor_weights"].update(momentum_trend=0.5), "sum to 1.0"),
    (lambda c: c["screener"]["factor_weights"].pop("structure"), "keys must be exactly"),
    (lambda c: c["screener"].update(shortlist_size=8), "shortlist_size"),
    (lambda c: c["screener"].update(shortlist_size=4), "shortlist_size"),
    (lambda c: c["capital"].update(max_risk_pct=0.05), "max_risk_pct"),
    (lambda c: c["capital"].update(max_leverage=6), "max_leverage"),
    (lambda c: c["capital"].update(max_trades_per_day=3), "max_trades_per_day"),
    (lambda c: c["market"].update(hard_exit="15:45"), "market times"),
    (lambda c: c["strategies"]["orb"].update(window_end="14:30"), "strategy orb"),
    (lambda c: c["strategies"].pop("gap"), "strategies keys"),
])
def test_invalid_config_rejected(raw_config, mutate, message):
    mutate(raw_config)
    with pytest.raises(ValidationError, match=message):
        Settings.model_validate(raw_config)


def test_get_secret_reads_keyring(monkeypatch):
    store = {("tradalgo", "TELEGRAM_BOT_TOKEN"): "abc"}
    monkeypatch.setattr(config.keyring, "get_password", lambda svc, name: store.get((svc, name)))
    assert get_secret("TELEGRAM_BOT_TOKEN") == "abc"
    with pytest.raises(KeyError, match="FYERS_PIN"):
        get_secret("FYERS_PIN")
