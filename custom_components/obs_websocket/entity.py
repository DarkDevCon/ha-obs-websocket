"""Base entity class for OBS WebSocket."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OBSWebSocketCoordinator


class OBSEntity(CoordinatorEntity):
    """Base entity for OBS WebSocket."""

    def __init__(
        self,
        coordinator: OBSWebSocketCoordinator,
        entry_id: str,
        description: EntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=f"OBS Studio {coordinator.host}",
            manufacturer="OBS Project",
            model="OBS Studio",
            sw_version="WebSocket 5.x",
        )