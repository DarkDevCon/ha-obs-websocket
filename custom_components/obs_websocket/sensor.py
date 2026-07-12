"""Sensor platform for OBS WebSocket."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
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
        translation_key="current_scene",
        icon="mdi:movie-open",
    ),
    OBSSensorEntityDescription(
        key="streaming",
        translation_key="streaming",
        icon="mdi:cast",
    ),
    OBSSensorEntityDescription(
        key="recording",
        translation_key="recording",
        icon="mdi:record-rec",
    ),
    OBSSensorEntityDescription(
        key="replay_buffer",
        translation_key="replay_buffer",
        icon="mdi:history",
    ),
    OBSSensorEntityDescription(
        key="virtualcam",
        translation_key="virtualcam",
        icon="mdi:camera",
    ),
    OBSSensorEntityDescription(
        key="scene_count",
        translation_key="scene_count",
        icon="mdi:view-dashboard",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    # === Stream Stats ===
    OBSSensorEntityDescription(
        key="stream_bytes",
        translation_key="stream_bytes",
        icon="mdi:server-network",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    OBSSensorEntityDescription(
        key="stream_duration",
        translation_key="stream_duration",
        icon="mdi:timer",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    OBSSensorEntityDescription(
        key="stream_skipped_frames",
        translation_key="stream_skipped_frames",
        icon="mdi:alert-circle",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    OBSSensorEntityDescription(
        key="stream_total_frames",
        translation_key="stream_total_frames",
        icon="mdi:filmstrip",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    OBSSensorEntityDescription(
        key="stream_dropped_frames_pct",
        translation_key="stream_dropped_frames_pct",
        icon="mdi:percent",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    OBSSensorEntityDescription(
        key="stream_congestion",
        translation_key="stream_congestion",
        icon="mdi:lan-connect",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    # === System Stats ===
    OBSSensorEntityDescription(
        key="active_fps",
        translation_key="active_fps",
        icon="mdi:speedometer",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    OBSSensorEntityDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        icon="mdi:cpu-64-bit",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    OBSSensorEntityDescription(
        key="memory_usage",
        translation_key="memory_usage",
        icon="mdi:memory",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    OBSSensorEntityDescription(
        key="render_skipped_frames",
        translation_key="render_skipped_frames",
        icon="mdi:alert-circle-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    OBSSensorEntityDescription(
        key="render_total_frames",
        translation_key="render_total_frames",
        icon="mdi:filmstrip-box",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    OBSSensorEntityDescription(
        key="render_missed_frames",
        translation_key="render_missed_frames",
        icon="mdi:alert-octagon-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    OBSSensorEntityDescription(
        key="avg_frame_render_time",
        translation_key="avg_frame_render_time",
        icon="mdi:timer-sand",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    OBSSensorEntityDescription(
        key="available_disk_space",
        translation_key="available_disk_space",
        icon="mdi:harddisk",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
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

        # Status sensors
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

        # Stream stats
        elif key == "stream_bytes":
            return self.coordinator.stream_bytes
        elif key == "stream_duration":
            # Convert milliseconds to seconds for HA duration
            return round(self.coordinator.stream_duration / 1000, 1)
        elif key == "stream_skipped_frames":
            return self.coordinator.stream_skipped_frames
        elif key == "stream_total_frames":
            return self.coordinator.stream_total_frames
        elif key == "stream_dropped_frames_pct":
            total = self.coordinator.stream_total_frames
            if total > 0:
                return round(
                    (self.coordinator.stream_skipped_frames / total) * 100, 1
                )
            return 0.0
        elif key == "stream_congestion":
            return self.coordinator.stream_congestion

        # System stats
        elif key == "active_fps":
            return round(self.coordinator.active_fps, 1)
        elif key == "cpu_usage":
            return round(self.coordinator.cpu_usage, 1)
        elif key == "memory_usage":
            return round(self.coordinator.memory_usage, 1)
        elif key == "render_skipped_frames":
            return self.coordinator.render_skipped_frames
        elif key == "render_total_frames":
            return self.coordinator.render_total_frames
        elif key == "render_missed_frames":
            return self.coordinator.render_missed_frames
        elif key == "avg_frame_render_time":
            return round(self.coordinator.avg_frame_render_time, 2)
        elif key == "available_disk_space":
            return round(self.coordinator.available_disk_space, 1)

        return None

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return extra state attributes."""
        key = self.entity_description.key

        if key == "current_scene":
            return {"scenes": self.coordinator.scenes}
        elif key == "streaming":
            return {
                "reconnecting": self.coordinator.stream_reconnecting,
                "bytes_sent": self.coordinator.stream_bytes,
                "duration": round(self.coordinator.stream_duration / 1000, 1),
                "skipped_frames": self.coordinator.stream_skipped_frames,
                "total_frames": self.coordinator.stream_total_frames,
                "congestion": self.coordinator.stream_congestion,
            }
        return None