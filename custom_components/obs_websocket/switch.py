"""Switch platform for OBS WebSocket — streaming/recording toggles and scene item visibility."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityDescription, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .coordinator import OBSWebSocketCoordinator, SIGNAL_OBS_UPDATE
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

    # Static switches (streaming, recording, etc.)
    entities: list[SwitchEntity] = []
    for description in SWITCHES:
        entities.append(OBSSwitch(coordinator, entry.entry_id, description))

    async_add_entities(entities)

    # Dynamic visibility switches per scene item (disabled by default via entity_category)
    _known_vis_keys: set[tuple[str, str]] = set()

    @callback
    def _async_add_vis_switches(entry_id: str) -> None:
        if entry_id != entry.entry_id:
            return

        new_entities = []
        for scene_name, sources in coordinator.scene_items.items():
            for source_name in sources:
                key = (scene_name, source_name)
                if key not in _known_vis_keys:
                    _known_vis_keys.add(key)
                    new_entities.append(
                        OBSSceneItemVisibilitySwitch(
                            coordinator, entry.entry_id, scene_name, source_name
                        )
                    )
        if new_entities:
            async_add_entities(new_entities)

    # Initial creation — scene_items might be empty on first call
    _async_add_vis_switches(entry.entry_id)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_OBS_UPDATE, _async_add_vis_switches)
    )


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


class OBSSceneItemVisibilitySwitch(OBSEntity, SwitchEntity):
    """OBS WebSocket visibility toggle for a source within a scene.

    Disabled by default via entity_category=config.
    Enable in HA entity registry to use.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: OBSWebSocketCoordinator,
        entry_id: str,
        scene_name: str,
        source_name: str,
    ) -> None:
        description = EntityDescription(
            key=f"visibility_{scene_name}_{source_name}",
            translation_key="scene_item_visibility",
            translation_placeholders={"source": source_name, "scene": scene_name},
            icon="mdi:eye",
        )
        super().__init__(coordinator, entry_id, description)
        self._scene_name = scene_name
        self._source_name = source_name

    @property
    def is_on(self) -> bool:
        """Return True if the source is visible in the scene."""
        scene = self.coordinator.scene_items.get(self._scene_name, {})
        return scene.get(self._source_name, True)

    @property
    def available(self) -> bool:
        """Return True if the scene and source still exist."""
        return (
            self._scene_name in self.coordinator.scene_items
            and self._source_name in self.coordinator.scene_items.get(self._scene_name, {})
        )

    async def async_turn_on(self) -> None:
        """Show the source in the scene."""
        await self.coordinator.set_scene_item_enabled(self._scene_name, self._source_name, True)

    async def async_turn_off(self) -> None:
        """Hide the source in the scene."""
        await self.coordinator.set_scene_item_enabled(self._scene_name, self._source_name, False)