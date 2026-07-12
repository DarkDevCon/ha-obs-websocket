"""Switch platform for OBS WebSocket — streaming/recording toggles."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OBSWebSocketCoordinator
from .entity import OBSEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OBSSwitchEntityDescription(SwitchEntityDescription):
    turn_on_fn: str = ""
    turn_off_fn: str = ""
    state_fn: str = ""


SWITCHES: tuple[OBSSwitchEntityDescription, ...] = (
    OBSSwitchEntityDescription(
        key="streaming",
        translation_key="streaming",
        icon="mdi:cast",
        turn_on_fn="start_streaming",
        turn_off_fn="stop_streaming",
        state_fn="streaming",
    ),
    OBSSwitchEntityDescription(
        key="recording",
        translation_key="recording",
        icon="mdi:record-rec",
        turn_on_fn="start_recording",
        turn_off_fn="stop_recording",
        state_fn="recording",
    ),
    OBSSwitchEntityDescription(
        key="replay_buffer",
        translation_key="replay_buffer",
        icon="mdi:history",
        turn_on_fn="start_replay_buffer",
        turn_off_fn="stop_replay_buffer",
        state_fn="replay_buffer",
    ),
    OBSSwitchEntityDescription(
        key="virtualcam",
        translation_key="virtualcam",
        icon="mdi:camera",
        turn_on_fn="start_virtualcam",
        turn_off_fn="stop_virtualcam",
        state_fn="virtualcam",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OBS WebSocket switches."""
    coordinator: OBSWebSocketCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SwitchEntity] = []
    for description in SWITCHES:
        entities.append(OBSSwitch(coordinator, entry.entry_id, description))

    async_add_entities(entities)


class OBSSwitch(OBSEntity, SwitchEntity):
    """OBS WebSocket switch."""

    def __init__(
        self,
        coordinator: OBSWebSocketCoordinator,
        entry_id: str,
        description: OBSSwitchEntityDescription,
    ) -> None:
        super().__init__(coordinator, entry_id, description)
        self._description = description

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return getattr(self.coordinator, self._description.state_fn, False)

    async def async_turn_on(self) -> None:
        """Turn the switch on."""
        fn = getattr(self.coordinator, self._description.turn_on_fn, None)
        if fn and callable(fn):
            await fn()
        else:
            _LOGGER.warning("Action %s not found on coordinator", self._description.turn_on_fn)

    async def async_turn_off(self) -> None:
        """Turn the switch off."""
        fn = getattr(self.coordinator, self._description.turn_off_fn, None)
        if fn and callable(fn):
            await fn()
        else:
            _LOGGER.warning("Action %s not found on coordinator", self._description.turn_off_fn)