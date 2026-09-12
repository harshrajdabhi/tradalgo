from pathlib import Path

import pytest
import yaml

from tradalgo.config import Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def raw_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def settings(raw_config) -> Settings:
    return Settings.model_validate(raw_config)
