"""Number platform for OBS WebSocket — audio input volume sliders."""
from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory

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
    """Set up OBS WebSocket number entities (volume sliders)."""
    coordinator: OBSWebSocketCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Initial creation
    entities: list[OBSVolumeSlider] = []
    for source_name in coordinator.audio_inputs:
        entities.append(OBSVolumeSlider(coordinator, entry.entry_id, source_name))

    async_add_entities(entities)

    # Listen for new audio inputs being added
    @callback
    def _async_update_entities(entry_id: str) -> None:
        if entry_id != entry.entry_id:
            return
        # Check for new sources not yet tracked
        existing_names = {
            entity._source_name
            for entity in entities
            if isinstance(entity, OBSVolumeSlider)
        }
        new_entities = []
        for source_name in coordinator.audio_inputs:
            if source_name not in existing_names:
                new_entity = OBSVolumeSlider(coordinator, entry.entry_id, source_name)
                entities.append(new_entity)
                new_entities.append(new_entity)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_OBS_UPDATE, _async_update_entities)
    )


class OBSVolumeSlider(OBSEntity, NumberEntity):
    """OBS WebSocket audio volume slider."""

    _attr_entity_category = EntityCategory.CONFIG

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