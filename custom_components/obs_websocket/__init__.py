"""The OBS WebSocket integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, CONF_HOST, CONF_PORT, CONF_PASSWORD, EVENT_OBS_EVENT

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.BUTTON, Platform.CAMERA]

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up via YAML not supported, use config flow."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up OBS WebSocket from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    from .coordinator import OBSWebSocketCoordinator

    coordinator = OBSWebSocketCoordinator(
        hass,
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, 4455),
        password=entry.data.get(CONF_PASSWORD),
        entry_id=entry.entry_id,
    )

    hass.data[DOMAIN][entry.entry_id] = coordinator

    try:
        await coordinator.async_connect()
    except Exception as err:
        _LOGGER.error("Failed to connect to OBS WebSocket: %s", err)
        return False

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    _register_services(hass, entry)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        await coordinator.async_disconnect()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

def _register_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register integration services."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    async def handle_set_scene(call: ServiceCall) -> None:
        scene_name = call.data.get("scene")
        if scene_name:
            await coordinator.set_scene(scene_name)

    async def handle_start_streaming(call: ServiceCall) -> None:
        await coordinator.start_streaming()

    async def handle_stop_streaming(call: ServiceCall) -> None:
        await coordinator.stop_streaming()

    async def handle_start_recording(call: ServiceCall) -> None:
        await coordinator.start_recording()

    async def handle_stop_recording(call: ServiceCall) -> None:
        await coordinator.stop_recording()

    async def handle_toggle_mute(call: ServiceCall) -> None:
        source = call.data.get("source")
        if source:
            await coordinator.toggle_mute(source)

    hass.services.async_register(DOMAIN, "set_scene", handle_set_scene)
    hass.services.async_register(DOMAIN, "start_streaming", handle_start_streaming)
    hass.services.async_register(DOMAIN, "stop_streaming", handle_stop_streaming)
    hass.services.async_register(DOMAIN, "start_recording", handle_start_recording)
    hass.services.async_register(DOMAIN, "stop_recording", handle_stop_recording)
    hass.services.async_register(DOMAIN, "toggle_mute", handle_toggle_mute)