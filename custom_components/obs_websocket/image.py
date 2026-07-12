"""Image platform for OBS WebSocket — scene preview via screenshot."""
from __future__ import annotations

import asyncio
import collections
import logging
from datetime import datetime, timedelta
from random import SystemRandom

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.httpx_client import get_async_client

from .const import DOMAIN
from .coordinator import OBSWebSocketCoordinator
from .entity import OBSEntity

_LOGGER = logging.getLogger(__name__)

# How often to refresh the screenshot (seconds)
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

    Overrides image() to return screenshot bytes from OBS.
    """

    _attr_should_poll = True

    def __init__(
        self,
        coordinator: OBSWebSocketCoordinator,
        entry_id: str,
        hass: HomeAssistant,
    ) -> None:
        # MUST set access_tokens BEFORE super().__init__ because
        # CoordinatorEntity.__init__ / HA internals may trigger
        # async_write_ha_state() during init, which reads state_attributes,
        # which reads access_tokens.
        self.access_tokens: collections.deque = collections.deque([], 2)
        self.access_tokens.append(hex(SystemRandom().getrandbits(256))[2:])

        description = ImageEntityDescription(
            key="scene_preview",
            translation_key="scene_preview",
            icon="mdi:eye",
        )
        super().__init__(coordinator, entry_id, description)

        # Now safe to set remaining ImageEntity attributes
        self._client = get_async_client(hass, verify_ssl=False)
        self._attr_content_type = "image/jpeg"
        self._attr_image_last_updated: datetime | None = None
        self._last_fetch: datetime | None = None
        self._cached_bytes: bytes | None = None

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.scene is not None
        )

    def image(self) -> bytes | None:
        """Return screenshot bytes.

        Called by HA's async_image() in an executor thread.
        Returns cached bytes if recent enough, otherwise None
        (async_update fetches new bytes asynchronously).
        """
        return self._cached_bytes

    async def async_update(self) -> None:
        """Fetch a new preview screenshot periodically."""
        scene = self.coordinator.scene
        if not scene:
            return

        now = datetime.now()
        if self._last_fetch and (now - self._last_fetch) < timedelta(seconds=PREVIEW_INTERVAL):
            return

        _LOGGER.debug("Preview: requesting screenshot for scene '%s'", scene)
        try:
            image_data = await asyncio.wait_for(
                self.coordinator.get_scene_preview(),
                timeout=15,
            )
            if image_data:
                self._cached_bytes = image_data
                self._attr_image_last_updated = now
                self._last_fetch = now
                self.async_write_ha_state()
                _LOGGER.debug("Preview: got %d bytes for scene '%s'", len(image_data), scene)
            else:
                _LOGGER.warning("Preview: get_scene_preview returned None for scene '%s'", scene)
        except asyncio.TimeoutError:
            _LOGGER.warning("Preview: timed out getting screenshot for scene '%s'", scene)
        except Exception as err:
            _LOGGER.warning("Preview: error getting screenshot for scene '%s': %s", scene, err)

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return the current scene name as attribute."""
        return {"scene": self.coordinator.scene}