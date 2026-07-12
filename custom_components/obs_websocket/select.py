"""Select platform for OBS WebSocket — scene selector."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OBSWebSocketCoordinator
from .entity import OBSEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OBS WebSocket select entities."""
    coordinator: OBSWebSocketCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OBSSceneSelect(coordinator, entry.entry_id)])


class OBSSceneSelect(OBSEntity, SelectEntity):
    """OBS WebSocket scene selector."""

    def __init__(
        self,
        coordinator: OBSWebSocketCoordinator,
        entry_id: str,
    ) -> None:
        from homeassistant.helpers.entity import EntityDescription
        description = EntityDescription(
            key="scene_selector",
            name="Scene",
            icon="mdi:movie-open",
        )
        super().__init__(coordinator, entry_id, description)

    @property
    def current_option(self) -> str | None:
        """Return the current selected scene."""
        return self.coordinator.scene

    @property
    def options(self) -> list[str]:
        """Return available scenes."""
        return self.coordinator.scenes

    async def async_select_option(self, option: str) -> None:
        """Select a scene."""
        await self.coordinator.set_scene(option)