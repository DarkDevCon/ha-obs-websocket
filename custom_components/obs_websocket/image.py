"""Image platform for OBS WebSocket — scene preview via screenshot."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import OBSWebSocketCoordinator
from .entity import OBSEntity

_LOGGER = logging.getLogger(__name__)

PREVIEW_INTERVAL = 10


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up OBS WebSocket image preview."""
    coordinator: OBSWebSocketCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([OBSScenePreview(coordinator, entry.entry_id, hass)])


class OBSScenePreview(OBSEntity, ImageEntity):
    """OBS WebSocket scene preview image.

    Saves screenshots to a file in HA's media dir and serves them
    via the image_file_path property.
    """

    def __init__(
        self,
        coordinator: OBSWebSocketCoordinator,
        entry_id: str,
        hass: HomeAssistant,
    ) -> None:
        description = EntityDescription(
            key="scene_preview",
            translation_key="scene_preview",
            icon="mdi:eye",
        )
        super().__init__(coordinator, entry_id, description)
        self._hass = hass
        self._last_update: float = 0
        self._image_path: str | None = None
        self._image_dir = hass.config.path("media/obs_websocket")
        self._image_file = os.path.join(self._image_dir, f"preview_{entry_id}.jpg")

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.scene is not None
        )

    @property
    def image_last_updated(self) -> float | None:
        """Return when the image was last updated."""
        if self._image_path and os.path.exists(self._image_path):
            return self._last_update or os.path.getmtime(self._image_path)
        return None

    @property
    def image_file_path(self) -> str | None:
        """Return the path to the saved image file."""
        if self._image_path and os.path.exists(self._image_path):
            return self._image_path
        return None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass, create dir and do first update."""
        await super().async_added_to_hass()
        os.makedirs(self._image_dir, exist_ok=True)

    async def async_update(self) -> None:
        """Fetch a new preview screenshot and save to file."""
        scene = self.coordinator.scene
        if not scene:
            return

        now = time.time()
        if self._image_path and os.path.exists(self._image_path) and (now - self._last_update) < PREVIEW_INTERVAL:
            return

        _LOGGER.info("Preview: requesting screenshot for scene '%s'", scene)
        try:
            image_data = await asyncio.wait_for(
                self.coordinator.get_scene_preview(),
                timeout=15,
            )
            if image_data:
                os.makedirs(self._image_dir, exist_ok=True)
                self._hass.async_add_executor_job(self._write_image, image_data)
                self._image_path = self._image_file
                self._last_update = now
                _LOGGER.info("Preview: saved %d bytes for scene '%s'", len(image_data), scene)
            else:
                _LOGGER.warning("Preview: get_scene_preview returned None for scene '%s'", scene)
        except asyncio.TimeoutError:
            _LOGGER.warning("Preview: timed out getting screenshot for scene '%s'", scene)
        except Exception as err:
            _LOGGER.warning("Preview: error getting screenshot for scene '%s': %s", scene, err)

    def _write_image(self, data: bytes) -> None:
        """Write image data to file (runs in executor)."""
        try:
            with open(self._image_file, "wb") as f:
                f.write(data)
        except Exception as err:
            _LOGGER.error("Preview: could not write image file: %s", err)

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return the current scene name as attribute."""
        return {"scene": self.coordinator.scene}