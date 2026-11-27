"""End-to-end test: OBS snapshot image must be served via the HA image proxy.

This reproduces the historical failure 'the image is not displayed':
set up the full integration with the image platform enabled, wait for the
coordinator-driven refresh, then fetch the entity through the exact URL the
frontend uses (GET /api/image_proxy/<entity_id>?token=...).
"""
from __future__ import annotations

from datetime import datetime

import pytest

from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.fake_obsws import FakeReqClient, install_fake_module, make_jpeg

DOMAIN = "obs_websocket"

ENTRY_DATA = {"host": "fake-obs", "port": 4455, "password": ""}
JPEG = make_jpeg()


def _image_entity(hass):
    """Locate the OBSScenePreview instance."""
    container = hass.data["image"]
    for ent in container.entities:
        if hasattr(ent, "_cached_bytes"):
            return ent
    return None


@pytest.mark.asyncio
async def test_setup_creates_image_entity(hass, enable_custom_integrations):
    install_fake_module()
    entry = MockConfigEntry(domain=DOMAIN, version=1, data=dict(ENTRY_DATA))
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state.value == "loaded", entry.state.value
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator._scene == "MultiView"

    states = hass.states.async_all("image")
    assert len(states) == 1, states
    state = states[0]
    assert state.state not in ("unavailable", "unknown"), state
    assert state.attributes["access_token"]
    assert state.attributes["scene"] == "MultiView"


@pytest.mark.asyncio
async def test_proxy_serves_jpeg_bytes(hass, enable_custom_integrations, hass_client):
    install_fake_module()
    entry = MockConfigEntry(domain=DOMAIN, version=1, data=dict(ENTRY_DATA))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator._notify_update()
    await hass.async_block_till_done()

    entity = _image_entity(hass)
    assert entity is not None, "OBSScenePreview not registered"
    assert entity._cached_bytes == JPEG, "image cache not filled by refresh"
    assert isinstance(entity._attr_image_last_updated, datetime)

    entity_id = entity.entity_id
    state = hass.states.get(entity_id)
    token = state.attributes["access_token"]

    client = await hass_client()
    resp = await client.get(f"/api/image_proxy/{entity_id}?token={token}")
    assert resp.status == 200, f"proxy returned {resp.status}"
    assert resp.headers["Content-Type"].startswith("image/jpeg"), dict(resp.headers)
    body = await resp.read()
    assert body == JPEG

    # state == isoformat of image_last_updated (HA ImageEntity contract)
    state = hass.states.get(entity_id)
    assert state.state == entity._attr_image_last_updated.isoformat()


@pytest.mark.asyncio
async def test_refresh_picks_up_new_screenshot(hass, enable_custom_integrations):
    """When the throttle window passes, the new OBS screenshot must be served."""
    install_fake_module()
    entry = MockConfigEntry(domain=DOMAIN, version=1, data=dict(ENTRY_DATA))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator._notify_update()
    await hass.async_block_till_done()

    entity = _image_entity(hass)
    assert entity is not None
    first = entity._cached_bytes
    assert first == JPEG

    # OBS returns a different screenshot now
    new_bytes = make_jpeg(color=(5, 200, 30))
    coordinator._client._wrapped.screenshot_bytes = new_bytes

    # Still inside PREVIEW_INTERVAL (10s): coordinator update must NOT refresh
    coordinator._notify_update()
    await hass.async_block_till_done()
    assert entity._cached_bytes == first, "throttle window failed"

    # Simulate the throttle window passing: reset _last_fetch and re-notify
    entity._last_fetch = None
    coordinator._notify_update()
    await hass.async_block_till_done()
    assert entity._cached_bytes == new_bytes, "new screenshot not picked up"

    state = hass.states.get(entity.entity_id)
    assert state.state == entity._attr_image_last_updated.isoformat()
