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
            name="Scene Preview",
            icon="mdi:eye",
        )
        super().__init__(coordinator, entry_id, description)
        self._last_image: bytes | None = None
        self._last_update: float = 0

    @property
    def available(self) -> bool:
        """Return True if coordinator is connected."""
        return self.coordinator.scene is not None

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a preview screenshot of the current scene."""
        now = time.time()
        # Throttle: only fetch if last fetch was > PREVIEW_INTERVAL ago
        if self._last_image is not None and (now - self._last_update) < PREVIEW_INTERVAL:
            return self._last_image

        try:
            image = await asyncio.wait_for(
                self.coordinator.get_scene_preview(),
                timeout=15,
            )
            if image:
                self._last_image = image
                self._last_update = now
                return image
        except asyncio.TimeoutError:
            _LOGGER.debug("Scene preview timed out")
        except Exception as err:
            _LOGGER.debug("Error getting scene preview: %s", err)

        return self._last_image

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return the current scene name as attribute."""
        return {"scene": self.coordinator.scene}