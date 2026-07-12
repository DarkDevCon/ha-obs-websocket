"""Camera platform for OBS WebSocket — scene preview via screenshot."""
from __future__ import annotations

import asyncio
import logging
import time

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OBSWebSocketCoordinator
from .entity import OBSEntity

_LOGGER = logging.getLogger(__name__)

# Preview refresh interval (seconds)
PREVIEW_INTERVAL = 10


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OBS WebSocket camera preview."""
    coordinator: OBSWebSocketCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OBSScenePreview(coordinator, entry.entry_id)])


class OBSScenePreview(OBSEntity, Camera):
    """OBS WebSocket scene preview camera."""

    def __init__(
        self,
        coordinator: OBSWebSocketCoordinator,
        entry_id: str,
    ) -> None:
        description = EntityDescription(
            key="scene_preview",
            translation_key="scene_preview",
            icon="mdi:eye",
        )
        super().__init__(coordinator, entry_id, description)
        self._last_image: bytes | None = None
        self._last_update: float = 0

    @property
    def available(self) -> bool:
        """Return True if coordinator is connected and has a current scene."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.scene is not None
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a preview screenshot of the current scene."""
        scene = self.coordinator.scene
        if not scene:
            _LOGGER.debug("Preview: no current scene available")
            return self._last_image

        now = time.time()
        # Throttle: only fetch if last fetch was > PREVIEW_INTERVAL ago
        if self._last_image is not None and (now - self._last_update) < PREVIEW_INTERVAL:
            return self._last_image

        _LOGGER.info("Preview: requesting screenshot for scene '%s'", scene)
        try:
            image = await asyncio.wait_for(
                self.coordinator.get_scene_preview(),
                timeout=15,
            )
            if image:
                _LOGGER.info("Preview: got %d bytes for scene '%s'", len(image), scene)
                self._last_image = image
                self._last_update = now
                return image
            else:
                _LOGGER.warning("Preview: get_scene_preview returned None for scene '%s'", scene)
        except asyncio.TimeoutError:
            _LOGGER.warning("Preview: timed out getting screenshot for scene '%s'", scene)
        except Exception as err:
            _LOGGER.warning("Preview: error getting screenshot for scene '%s': %s", scene, err)

        return self._last_image

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return the current scene name as attribute."""
        return {"scene": self.coordinator.scene}