"""Sensor platform for OBS WebSocket."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import DOMAIN
from .coordinator import OBSWebSocketCoordinator, SIGNAL_OBS_UPDATE
from .entity import OBSEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OBSSensorEntityDescription(SensorEntityDescription):
    pass


SENSORS: tuple[OBSSensorEntityDescription, ...] = (
    OBSSensorEntityDescription(
        key="current_scene",
        name="Current Scene",
        icon="mdi:movie-open",
    ),
    OBSSensorEntityDescription(
        key="streaming",
        name="Streaming",
        icon="mdi:cast",
    ),
    OBSSensorEntityDescription(
        key="recording",
        name="Recording",
        icon="mdi:record-rec",
    ),
    OBSSensorEntityDescription(
        key="replay_buffer",
        name="Replay Buffer",
        icon="mdi:history",
    ),
    OBSSensorEntityDescription(
        key="virtualcam",
        name="Virtual Camera",
        icon="mdi:camera",
    ),
    OBSSensorEntityDescription(
        key="scene_count",
        name="Scene Count",
        icon="mdi:view-dashboard",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OBS WebSocket sensors."""
    coordinator: OBSWebSocketCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for description in SENSORS:
        entities.append(OBSSensor(coordinator, entry.entry_id, description))

    async_add_entities(entities)


class OBSSensor(OBSEntity, SensorEntity):
    """OBS WebSocket sensor."""

    def __init__(
        self,
        coordinator: OBSWebSocketCoordinator,
        entry_id: str,
        description: OBSSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, description)

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        key = self.entity_description.key

        if key == "current_scene":
            return self.coordinator.scene
        elif key == "streaming":
            return "on" if self.coordinator.streaming else "off"
        elif key == "recording":
            return "on" if self.coordinator.recording else "off"
        elif key == "replay_buffer":
            return "on" if self.coordinator.replay_buffer else "off"
        elif key == "virtualcam":
            return "on" if self.coordinator.virtualcam else "off"
        elif key == "scene_count":
            return len(self.coordinator.scenes)
        return None

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return extra state attributes."""
        key = self.entity_description.key

        if key == "current_scene":
            return {"scenes": self.coordinator.scenes}
        return None