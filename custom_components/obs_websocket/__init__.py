"""The OBS WebSocket integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, CONF_HOST, CONF_PORT, CONF_PASSWORD, EVENT_OBS_EVENT

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.IMAGE,
]

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
        await coordinator.async_connect(skip_initial_refresh=True)
    except Exception as err:
        _LOGGER.error("Failed to connect to OBS WebSocket: %s", err)
        return False

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Now that all platforms/entities are set up, do the initial state refresh.
    # This ensures entities are registered as listeners before we notify them.
    await coordinator.refresh_state()

    # Register services (only once, they route to the right coordinator)
    _register_services(hass)

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

def _get_coordinator_for_entry(hass: HomeAssistant, entry_id: str):
    """Get coordinator by entry_id."""
    return hass.data[DOMAIN].get(entry_id)

def _register_services(hass: HomeAssistant) -> None:
    """Register integration services (multi-instance aware)."""

    def _get_coordinators(hass: HomeAssistant) -> list:
        """Return all registered coordinators."""
        return list(hass.data.get(DOMAIN, {}).values())

    async def handle_set_scene(call: ServiceCall) -> None:
        scene_name = call.data.get("scene")
        entry_id = call.data.get("entry_id")
        if entry_id:
            coordinator = _get_coordinator_for_entry(hass, entry_id)
            if coordinator and scene_name:
                await coordinator.set_scene(scene_name)
        else:
            # Apply to all coordinators
            for coordinator in _get_coordinators(hass):
                if scene_name and scene_name in coordinator.scenes:
                    await coordinator.set_scene(scene_name)
                    break

    async def handle_start_streaming(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        if entry_id:
            coordinator = _get_coordinator_for_entry(hass, entry_id)
            if coordinator:
                await coordinator.start_streaming()
        else:
            for coordinator in _get_coordinators(hass):
                await coordinator.start_streaming()

    async def handle_stop_streaming(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        if entry_id:
            coordinator = _get_coordinator_for_entry(hass, entry_id)
            if coordinator:
                await coordinator.stop_streaming()
        else:
            for coordinator in _get_coordinators(hass):
                await coordinator.stop_streaming()

    async def handle_start_recording(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        if entry_id:
            coordinator = _get_coordinator_for_entry(hass, entry_id)
            if coordinator:
                await coordinator.start_recording()
        else:
            for coordinator in _get_coordinators(hass):
                await coordinator.start_recording()

    async def handle_stop_recording(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        if entry_id:
            coordinator = _get_coordinator_for_entry(hass, entry_id)
            if coordinator:
                await coordinator.stop_recording()
        else:
            for coordinator in _get_coordinators(hass):
                await coordinator.stop_recording()

    async def handle_toggle_mute(call: ServiceCall) -> None:
        source = call.data.get("source")
        entry_id = call.data.get("entry_id")
        if entry_id:
            coordinator = _get_coordinator_for_entry(hass, entry_id)
            if coordinator and source:
                await coordinator.toggle_mute(source)
        elif source:
            for coordinator in _get_coordinators(hass):
                if source in coordinator.audio_inputs:
                    await coordinator.toggle_mute(source)
                    break

    # Only register once
    if not hass.services.has_service(DOMAIN, "set_scene"):
        hass.services.async_register(DOMAIN, "set_scene", handle_set_scene)
        hass.services.async_register(DOMAIN, "start_streaming", handle_start_streaming)
        hass.services.async_register(DOMAIN, "stop_streaming", handle_stop_streaming)
        hass.services.async_register(DOMAIN, "start_recording", handle_start_recording)
        hass.services.async_register(DOMAIN, "stop_recording", handle_stop_recording)
        hass.services.async_register(DOMAIN, "toggle_mute", handle_toggle_mute)