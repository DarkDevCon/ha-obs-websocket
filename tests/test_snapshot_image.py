"""End-to-end test: OBS snapshot image must be served via the HA image proxy.

This reproduces the historical failure 'the image is not displayed':
set up the full integration with the image platform enabled, wait for the
coordinator-driven refresh, then fetch the entity through the exact URL the
frontend uses (GET /api/image_proxy/<entity_id>?token=...).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from pytest_homeassistant_custom_component.common import MockConfigEntry

from tests.fake_obsws import install_fake_module, make_jpeg

DOMAIN = "obs_websocket"
PREVIEW_INTERVAL = 5  # mirror custom_components/obs_websocket/image.py

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
async def test_truncated_large_payload_still_served(hass, enable_custom_integrations):
    """The live failure shape: OBS truncates a large payload.

    The salvage decoder must recover a JPEG-signature image from the
    truncated 640px payload without needing a retry.
    """
    import base64 as b64mod

    install_fake_module()
    entry = MockConfigEntry(domain=DOMAIN, version=1, data=dict(ENTRY_DATA))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    fake_client = coordinator._client._wrapped

    full = b64mod.b64encode(fake_client.screenshot_bytes).decode().rstrip("=")
    truncated = full[: len(full) - ((len(full) - 1) % 4)]  # data % 4 == 1
    assert len(truncated) % 4 == 1

    fake_client.get_source_screenshot = lambda *a, **k: SimpleNamespace(
        image_data=truncated
    )
    coordinator._notify_update()
    await hass.async_block_till_done()

    entity = _image_entity(hass)
    assert entity is not None
    assert entity._cached_bytes is not None
    assert entity._cached_bytes[:2] == b"\xff\xd8", entity._cached_bytes[:16]


@pytest.mark.asyncio
async def test_preview_retries_smaller_size(hass, enable_custom_integrations):
    """Unusable large payloads must trigger the smaller-size retry ladder."""
    install_fake_module()
    entry = MockConfigEntry(domain=DOMAIN, version=1, data=dict(ENTRY_DATA))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][entry.entry_id]
    fake_client = coordinator._client._wrapped
    fake_client.fail_large_screenshots = True

    coordinator._notify_update()
    await hass.async_block_till_done()

    entity = _image_entity(hass)
    assert entity is not None
    assert entity._cached_bytes == JPEG

    # Clear the 10s throttle so the next update actually fetches
    entity._last_fetch = None
    coordinator._notify_update()
    await hass.async_block_till_done()

    widths = [req[0] for req in fake_client.screenshot_requests]
    assert entity._cached_bytes == JPEG, "retry ladder did not produce a JPEG"
    assert 640 in widths, f"expected a 640px attempt: {widths}"
    assert widths[-1] == 480, f"expected ladder to stop at the successful 480px: {widths}"


@pytest.mark.asyncio
async def test_timer_pulls_every_5_seconds(hass, enable_custom_integrations):
    """The periodic timer must pull a fresh screenshot every PREVIEW_INTERVAL."""
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

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
    assert entity._cached_bytes == JPEG
    fake_client = coordinator._client._wrapped
    requests_before = len(fake_client.screenshot_requests)

    # OBS renders a different image now
    new_bytes = make_jpeg(color=(255, 0, 255))
    fake_client.screenshot_bytes = new_bytes

    # Advance HA time by one PREVIEW_INTERVAL (5s) — the entity's timer must
    # fire and pull a new screenshot. Simulate a full-interval-old fetch so
    # the throttle (loop-time based) lets it through.
    entity._last_fetch = entity.hass.loop.time() - PREVIEW_INTERVAL - 0.5
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=5, milliseconds=50)
    )
    await hass.async_block_till_done()

    assert len(fake_client.screenshot_requests) == requests_before + 1, (
        fake_client.screenshot_requests
    )
    assert entity._cached_bytes == new_bytes

    # State reflects the new fetch
    state = hass.states.get(entity.entity_id)
    assert state.state == entity._attr_image_last_updated.isoformat()


@pytest.mark.asyncio
async def test_throttle_boundary_survives_jitter(hass, enable_custom_integrations):
    """A fetch measured at ~4.8s ago must pull again — the old wall-clock
    throttle skipped it (< 5.0s strictly), which doubled the effective
    interval to 10s when the 5s timer hit the boundary."""
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
    fake_client = coordinator._client._wrapped
    requests_before = len(fake_client.screenshot_requests)

    # Simulate a fetch 4.8s ago (inside the strict old throttle, inside the
    # new slack): a triggered refresh must go through.
    entity._last_fetch = entity.hass.loop.time() - (PREVIEW_INTERVAL - 0.2)
    await entity._async_refresh_image()
    assert len(fake_client.screenshot_requests) == requests_before + 1

    # Just after a fresh fetch (elapsed ~0s): still throttled.
    entity._last_fetch = entity.hass.loop.time() - 0.1
    await entity._async_refresh_image()
    assert len(fake_client.screenshot_requests) == requests_before + 1


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
