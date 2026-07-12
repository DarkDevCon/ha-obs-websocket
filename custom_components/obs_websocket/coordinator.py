"""OBS WebSocket Coordinator — manages connection and state."""
from __future__ import annotations

import base64
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

        # ReqClient and EventClient constructors do blocking I/O (WebSocket connect + auth)
        self._client = await self.hass.async_add_executor_job(
            lambda: obs.ReqClient(
                host=self._host,
                port=self._port,
                password=self._password or "",
                timeout=10,
            )
        )

        # Get initial state
        await self._refresh_state()

        # EventClient auto-connects and starts listening in __init__
        self._event_client = await self.hass.async_add_executor_job(
            lambda: obs.EventClient(
                host=self._host,
                port=self._port,
                password=self._password or "",
                timeout=10,
            )
        )

        self._event_client.callback.register(
            [
                self.on_current_program_scene_changed,
                self.on_stream_state_changed,
                self.on_record_state_changed,
                self.on_replay_buffer_state_changed,
                self.on_virtualcam_state_changed,
                self.on_scene_list_changed,
                self.on_scene_item_enable_state_changed,
                self.on_input_mute_state_changed,
                self.on_input_volume_changed,
                self.on_input_created,
                self.on_input_removed,
            ]
        )

        _LOGGER.info("Connected to OBS WebSocket at %s:%s", self._host, self._port)

    async def async_disconnect(self) -> None:
        """Disconnect from OBS WebSocket."""
        if self._event_client:
            try:
                await self.hass.async_add_executor_job(self._event_client.disconnect)
            except Exception:
                pass
            self._event_client = None

        if self._client:
            try:
                await self.hass.async_add_executor_job(self._client.disconnect)
            except Exception:
                pass
            self._client = None

        _LOGGER.info("Disconnected from OBS WebSocket")

    async def _refresh_state(self) -> None:
        """Refresh all state from OBS.

        Each section is independent so a failure in one call
        (e.g. get_stream_status) does not prevent others
        (e.g. audio inputs / scenes) from being populated.
        """
        if not self._client:
            return

        # Current scene
        try:
            scene = await self.hass.async_add_executor_job(
                self._client.get_current_program_scene
            )
            self._scene = scene.current_program_scene_name if scene else None
        except Exception as err:
            _LOGGER.error("Error getting current scene: %s", err)

        # Streaming status
        try:
            status = await self.hass.async_add_executor_job(
                self._client.get_stream_status
            )
            self._streaming = bool(status.output_active) if status else False
        except Exception as err:
            _LOGGER.error("Error getting stream status: %s", err)

        # Recording status
        try:
            rec = await self.hass.async_add_executor_job(
                self._client.get_record_status
            )
            self._recording = bool(rec.output_active) if rec else False
        except Exception as err:
            _LOGGER.error("Error getting record status: %s", err)

        # Replay buffer status (not all OBS setups have replay buffer enabled)
        try:
            replay = await self.hass.async_add_executor_job(
                self._client.get_replay_buffer_status
            )
            self._replay_buffer = bool(replay.output_active) if replay else False
        except Exception:
            _LOGGER.debug("Replay buffer not available, skipping")
            self._replay_buffer = False

        # Virtual camera status (not all OBS setups have virtual cam)
        try:
            vcam = await self.hass.async_add_executor_job(
                self._client.get_virtual_cam_status
            )
            self._virtualcam = bool(vcam.output_active) if vcam else False
        except Exception:
            _LOGGER.debug("Virtual cam not available, skipping")
            self._virtualcam = False

        # Scenes list
        try:
            scenes_resp = await self.hass.async_add_executor_job(
                self._client.get_scene_list
            )
            if scenes_resp and scenes_resp.scenes:
                # scenes is a list of raw dicts with camelCase keys
                self._scenes = [s["sceneName"] for s in scenes_resp.scenes]
            else:
                self._scenes = []
        except Exception as err:
            _LOGGER.error("Error getting scene list: %s", err)

        # Audio inputs
        await self._refresh_audio_inputs()

        # Scene item visibility
        await self._refresh_scene_items()

        self._notify_update()

    async def _refresh_audio_inputs(self) -> None:
        """Refresh audio input list and their mute/volume state.

        Combines regular inputs (GetInputList) and special inputs
        (GetSpecialInputs — Desktop Audio, Mic/Aux, etc.) because
        OBS treats them as different categories.
        """
        if not self._client:
            return
        new_inputs: dict[str, dict] = {}

        # 1) Regular inputs
        try:
            inputs = await self.hass.async_add_executor_job(
                self._client.get_input_list
            )
            raw_inputs = inputs.inputs if inputs and hasattr(inputs, "inputs") else []
            if not raw_inputs and inputs:
                raw_inputs = inputs.get("inputs", []) if hasattr(inputs, "get") else []
            for inp in raw_inputs:
                name = inp.get("inputName") if isinstance(inp, dict) else None
                if not name:
                    continue
                await self._fetch_audio_state(name, new_inputs)
        except Exception as err:
            _LOGGER.error("Could not refresh regular inputs: %s", err)

        # 2) Special inputs (Desktop Audio, Mic/Aux, etc.)
        try:
            special = await self.hass.async_add_executor_job(
                self._client.get_special_inputs
            )
            # Response has camelCase keys like desktopDevice1, auxDevice1, etc.
            if special:
                for attr in dir(special):
                    if attr.startswith("_"):
                        continue
                    val = getattr(special, attr, None)
                    if isinstance(val, str) and val:
                        # attr is like 'desktopDevice1', val is the input name
                        await self._fetch_audio_state(val, new_inputs)
        except Exception as err:
            _LOGGER.debug("Could not refresh special inputs: %s", err)

        self._audio_inputs = new_inputs
        _LOGGER.info("Refreshed audio inputs: %s", list(new_inputs.keys()))

    async def _fetch_audio_state(self, name: str, target: dict) -> None:
        """Fetch mute + volume for a single input and add to target dict."""
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
        target[name] = {"muted": muted, "volume_db": vol_db}

    async def _refresh_scene_items(self) -> None:
        """Refresh scene item visibility for all scenes."""
        if not self._client:
            return
        if not self._scenes:
            return
        try:
            new_scene_items: dict[str, dict[str, bool]] = {}
            for scene_name in self._scenes:
                try:
                    items = await self.hass.async_add_executor_job(
                        self._client.get_scene_item_list, scene_name
                    )
                    scene_vis: dict[str, bool] = {}
                    # scene_items is a list of raw dicts with camelCase keys
                    raw_items = items.scene_items if items and hasattr(items, "scene_items") else []
                    if not raw_items and items:
                        raw_items = items.get("scene_items", []) if hasattr(items, "get") else []
                    for item in raw_items:
                        if not isinstance(item, dict):
                            continue
                        source_name = item.get("sourceName", "")
                        visible = item.get("sceneItemVisible", True)
                        if source_name:
                            scene_vis[source_name] = visible
                    new_scene_items[scene_name] = scene_vis
                except Exception as err:
                    _LOGGER.debug("Could not get scene items for %s: %s", scene_name, err)
            self._scene_items = new_scene_items
        except Exception as err:
            _LOGGER.error("Could not refresh scene items: %s", err)

    async def _refresh_scenes(self) -> None:
        if not self._client:
            return
        try:
            scenes_resp = await self.hass.async_add_executor_job(
                self._client.get_scene_list
            )
            if scenes_resp and scenes_resp.scenes:
                self._scenes = [s["sceneName"] for s in scenes_resp.scenes]
            else:
                self._scenes = []
        except Exception as err:
            _LOGGER.error("Error refreshing scenes: %s", err)
        self._notify_update()

    # === Event Callbacks ===
    # obsws-python Callback.trigger() calls functions named on_{snake_case(event)}.
    # Each callback receives a dataclass with snake_case attributes derived from the event data.

    def on_current_program_scene_changed(self, data) -> None:
        """Handle CurrentProgramSceneChanged event."""
        self._scene = data.scene_name
        self._fire_event("CurrentProgramSceneChanged", data)
        self._notify_update()

    def on_stream_state_changed(self, data) -> None:
        """Handle StreamStateChanged event."""
        self._streaming = data.output_active
        self._fire_event("StreamStateChanged", data)
        self._notify_update()

    def on_record_state_changed(self, data) -> None:
        """Handle RecordStateChanged event."""
        self._recording = data.output_active
        self._fire_event("RecordStateChanged", data)
        self._notify_update()

    def on_replay_buffer_state_changed(self, data) -> None:
        """Handle ReplayBufferStateChanged event."""
        self._replay_buffer = data.output_active
        self._fire_event("ReplayBufferStateChanged", data)
        self._notify_update()

    def on_virtualcam_state_changed(self, data) -> None:
        """Handle VirtualcamStateChanged event."""
        self._virtualcam = data.output_active
        self._fire_event("VirtualcamStateChanged", data)
        self._notify_update()

    def on_scene_list_changed(self, data) -> None:
        """Handle SceneListChanged event — trigger async refresh."""
        self.hass.loop.call_soon_threadsafe(
            self.hass.async_create_task, self._refresh_scenes()
        )
        self.hass.loop.call_soon_threadsafe(
            self.hass.async_create_task, self._refresh_scene_items()
        )
        self._fire_event("SceneListChanged", data)

    def on_scene_item_enable_state_changed(self, data) -> None:
        """Handle SceneItemEnableStateChanged event — trigger async refresh."""
        self.hass.loop.call_soon_threadsafe(
            self.hass.async_create_task, self._refresh_scene_items()
        )
        self._fire_event("SceneItemEnableStateChanged", data)

    def on_input_mute_state_changed(self, data) -> None:
        """Handle InputMuteStateChanged event."""
        input_name = data.input_name
        muted = data.input_muted
        if input_name and input_name in self._audio_inputs:
            self._audio_inputs[input_name]["muted"] = muted
        self._fire_event("InputMuteStateChanged", data)
        self._notify_update()

    def on_input_volume_changed(self, data) -> None:
        """Handle InputVolumeChanged event."""
        input_name = data.input_name
        vol_db = data.input_volume_db
        if input_name:
            if input_name not in self._audio_inputs:
                self._audio_inputs[input_name] = {"muted": False, "volume_db": vol_db}
            else:
                self._audio_inputs[input_name]["volume_db"] = vol_db
        self._fire_event("InputVolumeChanged", data)
        self._notify_update()

    def on_input_created(self, data) -> None:
        """Handle InputCreated event — refresh audio inputs."""
        self.hass.loop.call_soon_threadsafe(
            self.hass.async_create_task, self._refresh_audio_inputs()
        )
        self._fire_event("InputCreated", data)

    def on_input_removed(self, data) -> None:
        """Handle InputRemoved event."""
        input_name = data.input_name
        if input_name and input_name in self._audio_inputs:
            del self._audio_inputs[input_name]
        self._fire_event("InputRemoved", data)
        self._notify_update()

    def _fire_event(self, event_type: str, data) -> None:
        """Fire an HA event with the OBS event data.

        Called from OBS WebSocket callback thread — schedule on event loop.
        """
        try:
            if hasattr(data, "__dict__"):
                event_data = {
                    k: v
                    for k, v in data.__dict__.items()
                    if not k.startswith("_") and not callable(v)
                }
            else:
                event_data = {}
        except Exception:
            event_data = {}

        self.hass.loop.call_soon_threadsafe(
            self.hass.bus.async_fire,
            EVENT_OBS_EVENT,
            {"event_type": event_type, "data": event_data, "entry_id": self._entry_id},
        )

    @callback
    def _notify_update(self) -> None:
        """Notify entities of state update.

        If called from the event loop (hass thread), send directly.
        If called from OBS callback thread, schedule on event loop.
        """
        self.async_update_listeners()
        self.hass.loop.call_soon_threadsafe(
            async_dispatcher_send, self.hass, SIGNAL_OBS_UPDATE, self._entry_id
        )

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
            self._client.set_input_volume, source, None, volume_db
        )

    async def set_scene_item_enabled(self, scene_name: str, source_name: str, enabled: bool) -> None:
        """Set visibility of a source within a scene."""
        # Find the scene item id for the source in the scene
        items = await self.hass.async_add_executor_job(
            self._client.get_scene_item_list, scene_name
        )
        item_id = None
        for item in (items.scene_items if items else []):
            if item.get("sourceName") == source_name:
                item_id = item.get("sceneItemId")
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
            _LOGGER.debug("get_scene_preview: no client")
            return None
        try:
            if scene_name is None:
                scene_name = self._scene
            if scene_name is None:
                _LOGGER.debug("get_scene_preview: no current scene")
                return None
            _LOGGER.debug("get_scene_preview: requesting screenshot for '%s'", scene_name)
            # OBS WebSocket v5: GetSourceScreenshot
            # Scenes are sources in OBS, so GetSourceScreenshot works for scenes too.
            # Use jpg with reasonable size for HA preview (640px wide)
            # OBS requires width and height >= 8, 0 might not work
            screenshot = await self.hass.async_add_executor_job(
                self._client.get_source_screenshot,
                scene_name,
                "jpg",
                640,   # width
                360,   # height (16:9 aspect, OBS scales to inner)
                80,    # quality: 80% jpg
            )
            # as_dataclass converts top-level keys to snake_case
            # The response has 'imageData' -> 'image_data'
            if hasattr(screenshot, "image_data"):
                _LOGGER.debug("get_scene_preview: got image (%d bytes)", len(screenshot.image_data))
                return base64.b64decode(screenshot.image_data)
            elif hasattr(screenshot, "img"):
                return base64.b64decode(screenshot.img)
            else:
                _LOGGER.warning("get_scene_preview: unexpected response: %s", type(screenshot))
        except Exception as err:
            _LOGGER.warning("Error getting scene preview for '%s': %s", scene_name, err)
        return None
