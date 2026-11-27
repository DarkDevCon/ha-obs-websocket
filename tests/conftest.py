"""Shared fixtures for the OBS WebSocket integration tests."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def hass_config_dir():
    """Point HA's config dir at the repo root so custom_components/obs_websocket
    is discoverable by the integration loader."""
    return str(REPO_ROOT)
