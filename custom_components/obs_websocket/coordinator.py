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
        self._event_client = None
        self._data: dict[str, Any] = {}

        # State
        self._scene: str | None = None
        self._streaming: bool = False
        self._recording: bool = False
        self._replay_buffer: bool = False
        self._virtualcam: bool = False
        self._scenes: list[str] = []
        # Audio sources: {source_name: {"muted": bool, "volume_db": float}}
        self._audio_inputs: dict[str, dict] = {}
        # Scene item visibility: {scene_name: {source_name: bool}}
        self._scene_items: dict[str, dict[str, bool]] = {}

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

    @property
    def audio_inputs(self) -> dict[str, dict]:
        return self._audio_inputs

    @property
    def scene_items(self) -> dict[str, dict[str, bool]]:
        return self._scene_items

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

            # Audio inputs
            await self._refresh_audio_inputs()

            # Scene item visibility
            await self._refresh_scene_items()

        except Exception as err:
            _LOGGER.error("Error refreshing OBS state: %s", err)

        self._notify_update()

    async def _refresh_audio_inputs(self) -> None:
        """Refresh audio input list and their mute/volume state."""
        if not self._client:
            return
        try:
            inputs = await self.hass.async_add_executor_job(
                self._client.get_inputs
            )
            new_inputs: dict[str, dict] = {}
            for inp in (inputs.inputs if inputs else []):
                name = inp.input_name
                try:
                    mute_resp = await self.hass.async_add_executor_job(
                        self._client.get_input_mute, name
                    )
                    muted = mute_resp.input_muted if mute_resp else False
                except Exception:
                    muted = False
                try:
                    vol_resp = await self.hass.async_add_executor_job(
                        self._client.get_input_volume, name
                    )
                    vol_db = vol_resp.input_volume_db if vol_resp else 0.0
                except Exception:
                    vol_db = 0.0
                new_inputs[name] = {"muted": muted, "volume_db": vol_db}
            self._audio_inputs = new_inputs
        except Exception as err:
            _LOGGER.debug("Could not refresh audio inputs: %s", err)

    async def _refresh_scene_items(self) -> None:
        """Refresh scene item visibility for all scenes."""
        if not self._client:
            return
        try:
            new_scene_items: dict[str, dict[str, bool]] = {}
            for scene_name in self._scenes:
                try:
                    items = await self.hass.async_add_executor_job(
                        self._client.get_scene_item_list, scene_name
                    )
                    scene_vis: dict[str, bool] = {}
                    for item in (items.scene_items if items else []):
                        source_name = item.get("source_name", "")
                        visible = item.get("scene_item_visible", True)
                        if source_name:
                            scene_vis[source_name] = visible
                    new_scene_items[scene_name] = scene_vis
                except Exception:
                    pass
            self._scene_items = new_scene_items
        except Exception as err:
            _LOGGER.debug("Could not refresh scene items: %s", err)

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
            self.hass.async_create_task(self._refresh_scene_items())

        elif event_type == "SceneItemEnableStateChanged":
            scene_name = data.get("scene_name")
            item_id = data.get("scene_item_id")
            visible = data.get("scene_item_enabled", True)
            # Try to find source name by item_id in our cached data
            if scene_name and scene_name in self._scene_items:
                for src_name, vis in self._scene_items[scene_name].items():
                    # We don't have item_id mapping, so just trigger a refresh
                    break
            self.hass.async_create_task(self._refresh_scene_items())

        elif event_type == "InputMuteStateChanged":
            input_name = data.get("input_name")
            muted = data.get("input_muted", False)
            if input_name and input_name in self._audio_inputs:
                self._audio_inputs[input_name]["muted"] = muted

        elif event_type == "InputVolumeChanged":
            input_name = data.get("input_name")
            vol_db = data.get("input_volume_db", 0.0)
            if input_name:
                if input_name not in self._audio_inputs:
                    self._audio_inputs[input_name] = {"muted": False, "volume_db": vol_db}
                else:
                    self._audio_inputs[input_name]["volume_db"] = vol_db

        elif event_type == "InputCreated":
            self.hass.async_create_task(self._refresh_audio_inputs())

        elif event_type == "InputRemoved":
            input_name = data.get("input_name")
            if input_name and input_name in self._audio_inputs:
                del self._audio_inputs[input_name]

        # Fire HA event
        self.hass.bus.async_fire(
            EVENT_OBS_EVENT,
            {"event_type": event_type, "data": data, "entry_id": self._entry_id},
        )

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

    async def set_mute(self, source: str, muted: bool) -> None:
        await self.hass.async_add_executor_job(
            self._client.set_input_mute, source, muted
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

    async def set_scene_item_enabled(self, scene_name: str, source_name: str, enabled: bool) -> None:
        """Set visibility of a source within a scene."""
        # Find the scene item id for the source in the scene
        items = await self.hass.async_add_executor_job(
            self._client.get_scene_item_list, scene_name
        )
        item_id = None
        for item in (items.scene_items if items else []):
            if item.get("source_name") == source_name:
                item_id = item.get("scene_item_id")
                break
        if item_id is not None:
            await self.hass.async_add_executor_job(
                self._client.set_scene_item_enabled, scene_name, item_id, enabled
            )
            # Update local state
            if scene_name in self._scene_items:
                self._scene_items[scene_name][source_name] = enabled
            self._notify_update()
        else:
            _LOGGER.warning("Source %s not found in scene %s", source_name, scene_name)

    async def get_scene_preview(self, scene_name: str | None = None) -> bytes | None:
        """Get a preview screenshot of the current or specified scene."""
        if not self._client:
            return None
        try:
            if scene_name is None:
                scene_name = self._scene
            if scene_name is None:
                return None
            # OBS WebSocket v5: GetSourceScreenshot
            screenshot = await self.hass.async_add_executor_job(
                self._client.get_source_screenshot,
                scene_name,
                "png",
            )
            # The response has a 'img' field with base64-encoded PNG
            if hasattr(screenshot, 'img'):
                import base64
                return base64.b64decode(screenshot.img)
            elif hasattr(screenshot, 'image_data'):
                import base64
                return base64.b64decode(screenshot.image_data)
        except Exception as err:
            _LOGGER.error("Error getting scene preview: %s", err)
        return None