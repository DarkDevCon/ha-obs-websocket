"""Button platform for OBS WebSocket — scene switching & actions."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OBSWebSocketCoordinator
from .entity import OBSEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OBSButtonEntityDescription(ButtonEntityDescription):
    action_fn: str = ""


BUTTONS: tuple[OBSButtonEntityDescription, ...] = (
    OBSButtonEntityDescription(
        key="start_stream",
        name="Start Stream",
        icon="mdi:cast",
        action_fn="start_streaming",
    ),
    OBSButtonEntityDescription(
        key="stop_stream",
        name="Stop Stream",
        icon="mdi:cast-off",
        action_fn="stop_streaming",
    ),
    OBSButtonEntityDescription(
        key="start_recording",
        name="Start Recording",
        icon="mdi:record-rec",
        action_fn="start_recording",
    ),
    OBSButtonEntityDescription(
        key="stop_recording",
        name="Stop Recording",
        icon="mdi:stop",
        action_fn="stop_recording",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OBS WebSocket buttons."""
    coordinator: OBSWebSocketCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for description in BUTTONS:
        entities.append(OBSButton(coordinator, entry.entry_id, description))

    async_add_entities(entities)


class OBSButton(OBSEntity, ButtonEntity):
    """OBS WebSocket button."""

    def __init__(
        self,
        coordinator: OBSWebSocketCoordinator,
        entry_id: str,
        description: OBSButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, description)
        self._description = description

    async def async_press(self) -> None:
        """Press the button."""
        fn = getattr(self.coordinator, self._description.action_fn, None)
        if fn and callable(fn):
            await fn()
        else:
            _LOGGER.warning("Action %s not found on coordinator", self._description.action_fn)