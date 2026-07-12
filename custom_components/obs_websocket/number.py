"""Number platform for OBS WebSocket — audio input volume sliders."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .coordinator import OBSWebSocketCoordinator, SIGNAL_OBS_UPDATE
from .entity import OBSEntity

_LOGGER = logging.getLogger(__name__)

# OBS volume range in dB (typical: -60 to 0)
VOLUME_MIN = -60.0
VOLUME_MAX = 0.0
VOLUME_STEP = 0.5


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OBS WebSocket number entities (volume sliders).

    Volume sliders are disabled by default (hidden in HA UI).
    Enable them in Settings → Integrations → OBS → Entities.
    """
    coordinator: OBSWebSocketCoordinator = hass.data[DOMAIN][entry.entry_id]

    _known_sources: set[str] = set()

    @callback
    def _async_add_new_entities(entry_id: str) -> None:
        if entry_id != entry.entry_id:
            return

        new_entities = []
        for source_name in coordinator.audio_inputs:
            if source_name not in _known_sources:
                _known_sources.add(source_name)
                new_entities.append(
                    OBSVolumeSlider(coordinator, entry.entry_id, source_name)
                )
        if new_entities:
            async_add_entities(new_entities)

    # Initial creation — audio_inputs might be empty on first call,
    # the dispatcher listener will add them after _refresh_state runs.
    _async_add_new_entities(entry.entry_id)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_OBS_UPDATE, _async_add_new_entities)
    )


class OBSVolumeSlider(OBSEntity, NumberEntity):
    """OBS WebSocket audio volume slider.

    Hidden by default. Enable in HA entity registry to use.
    """

    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        coordinator: OBSWebSocketCoordinator,
        entry_id: str,
        source_name: str,
    ) -> None:
        description = EntityDescription(
            key=f"volume_{source_name}",
            translation_key="volume",
            translation_placeholders={"source": source_name},
            icon="mdi:volume-high",
        )
        super().__init__(coordinator, entry_id, description)
        self._source_name = source_name
        self._attr_native_min_value = VOLUME_MIN
        self._attr_native_max_value = VOLUME_MAX
        self._attr_native_step = VOLUME_STEP
        self._attr_mode = NumberMode.SLIDER

    @property
    def native_value(self) -> float | None:
        """Return the current volume in dB."""
        source = self.coordinator.audio_inputs.get(self._source_name)
        if source:
            return source.get("volume_db", 0.0)
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Set the volume."""
        await self.coordinator.set_input_volume(self._source_name, float(value))