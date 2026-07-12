"""OBS WebSocket Coordinator — manages connection and state."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import DOMAIN, EVENT_OBS_EVENT

_LOGGER = logging.getLogger(__name__)

SIGNAL_OBS_UPDATE = f"{DOMAIN}_update"

class OBSWebSocketCoordinator(DataUpdateCoordinator):
    """Coordinator for OBS WebSocket connection."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        password: str | None,
        entry_id: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,  # Event-driven, not polling
        )
        self._host = host
        self._port = port
        self._password = password
        self._entry_id = entry_id
        self._client = None
        self._data: dict[str, Any] = {}

        # State
        self._scene: str | None = None
        self._streaming: bool = False
        self._recording: bool = False
        self._replay_buffer: bool = False
        self._virtualcam: bool = False
        self._scenes: list[str] = []
        self._sources: dict[str, dict] = {}

    @property
    def host(self) -> str:
        return self._host

    @property
    def scene(self) -> str | None:
        return self._scene

    @property
    def streaming(self) -> bool:
        return self._streaming

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def replay_buffer(self) -> bool:
        return self._replay_buffer

    @property
    def virtualcam(self) -> bool:
        return self._virtualcam

    @property
    def scenes(self) -> list[str]:
        return self._scenes

    async def async_connect(self) -> None:
        """Connect to OBS WebSocket."""
        import obsws_python as obs

        self._client = obs.ReqClient(
            host=self._host,
            port=self._port,
            password=self._password or "",
            timeout=10,
        )

        # Get initial state
        await self._refresh_state()

        # Subscribe to events via EventClient
        self._event_client = obs.EventClient(
            host=self._host,
            port=self._port,
            password=self._password or "",
            timeout=10,
        )

        self._event_client.callback.register(self._on_obs_event)
        self._event_client.connect()

        _LOGGER.info("Connected to OBS WebSocket at %s:%s", self._host, self._port)

    async def async_disconnect(self) -> None:
        """Disconnect from OBS WebSocket."""
        if self._event_client:
            try:
                self._event_client.disconnect()
            except Exception:
                pass
            self._event_client = None

        if self._client:
            try:
                self._client = None
            except Exception:
                pass
            self._client = None

        _LOGGER.info("Disconnected from OBS WebSocket")

    async def _refresh_state(self) -> None:
        """Refresh all state from OBS."""
        if not self._client:
            return

        try:
            # Current scene
            scene = await self.hass.async_add_executor_job(
                self._client.get_current_program_scene
            )
            self._scene = scene.scene_name if scene else None

            # Streaming / Recording / Replay / VirtualCam status
            status = await self.hass.async_add_executor_job(
                self._client.get_stream_status
            )
            self._streaming = bool(status.output_active) if status else False

            rec = await self.hass.async_add_executor_job(
                self._client.get_record_status
            )
            self._recording = bool(rec.output_active) if rec else False

            replay = await self.hass.async_add_executor_job(
                self._client.get_replay_buffer_status
            )
            self._replay_buffer = bool(replay.output_active) if replay else False

            vcam = await self.hass.async_add_executor_job(
                self._client.get_virtual_cam_status
            )
            self._virtualcam = bool(vcam.output_active) if vcam else False

            # Scenes list
            scenes_resp = await self.hass.async_add_executor_job(
                self._client.get_scene_list
            )
            self._scenes = [s.scene_name for s in scenes_resp.scenes] if scenes_resp else []

        except Exception as err:
            _LOGGER.error("Error refreshing OBS state: %s", err)

        self._notify_update()

    def _on_obs_event(self, event) -> None:
        """Handle OBS WebSocket events."""
        event_type = event.event_type
        data = event.data if hasattr(event, "data") else {}

        _LOGGER.debug("OBS event: %s — %s", event_type, data)

        if event_type == "CurrentProgramSceneChanged":
            self._scene = data.get("scene_name", self._scene)

        elif event_type == "StreamStateChanged":
            self._streaming = data.get("output_active", self._streaming)

        elif event_type == "RecordStateChanged":
            self._recording = data.get("output_active", self._recording)

        elif event_type == "ReplayBufferStateChanged":
            self._replay_buffer = data.get("output_active", self._replay_buffer)

        elif event_type == "VirtualcamStateChanged":
            self._virtualcam = data.get("output_active", self._virtualcam)

        elif event_type == "SceneListChanged":
            self.hass.async_create_task(self._refresh_scenes())

        # Fire HA event
        self.hass.bus.async_fire(
            EVENT_OBS_EVENT,
            {"event_type": event_type, "data": data, "entry_id": self._entry_id},
        )

        self._notify_update()

    async def _refresh_scenes(self) -> None:
        if not self._client:
            return
        try:
            scenes_resp = await self.hass.async_add_executor_job(
                self._client.get_scene_list
            )
            self._scenes = [s.scene_name for s in scenes_resp.scenes] if scenes_resp else []
        except Exception:
            pass
        self._notify_update()

    @callback
    def _notify_update(self) -> None:
        """Notify entities of state update."""
        async_dispatcher_send(self.hass, SIGNAL_OBS_UPDATE, self._entry_id)

    # === Control Methods ===

    async def set_scene(self, scene_name: str) -> None:
        await self.hass.async_add_executor_job(
            self._client.set_current_program_scene, scene_name
        )

    async def start_streaming(self) -> None:
        await self.hass.async_add_executor_job(self._client.start_stream)

    async def stop_streaming(self) -> None:
        await self.hass.async_add_executor_job(self._client.stop_stream)

    async def start_recording(self) -> None:
        await self.hass.async_add_executor_job(self._client.start_record)

    async def stop_recording(self) -> None:
        await self.hass.async_add_executor_job(self._client.stop_record)

    async def toggle_mute(self, source: str) -> None:
        await self.hass.async_add_executor_job(
            self._client.toggle_input_mute, source
        )

    async def start_replay_buffer(self) -> None:
        await self.hass.async_add_executor_job(self._client.start_replay_buffer)

    async def stop_replay_buffer(self) -> None:
        await self.hass.async_add_executor_job(self._client.stop_replay_buffer)

    async def start_virtualcam(self) -> None:
        await self.hass.async_add_executor_job(self._client.start_virtual_cam)

    async def stop_virtualcam(self) -> None:
        await self.hass.async_add_executor_job(self._client.stop_virtual_cam)

    async def get_input_volume(self, source: str) -> dict:
        return await self.hass.async_add_executor_job(
            self._client.get_input_volume, source
        )

    async def set_input_volume(self, source: str, volume_db: float) -> None:
        await self.hass.async_add_executor_job(
            self._client.set_input_volume, source, vol_db=volume_db
        )