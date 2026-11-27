"""OBS WebSocket Coordinator — manages connection and state."""
from __future__ import annotations

import asyncio
import base64
import logging
import socket
import threading
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.const import UnitOfDataRate, UnitOfInformation

from .const import DOMAIN, EVENT_OBS_EVENT, STATS_FAIL_THRESHOLD

_LOGGER = logging.getLogger(__name__)


# Polling interval for stream/system stats (OBS doesn't push these as events)
STATS_POLL_INTERVAL = 10  # seconds
RECONNECT_INTERVAL = 10  # seconds


def _bool_stat(value: Any) -> bool:
    """Normalize a stats flag that may arrive as bool or legacy 'true'/'false'."""
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _stat(obj: Any, attr: str, default: Any = 0) -> Any:
    """Read an attr from an obsws-python stats dataclass, or return default.

    obsws-python builds these dataclasses dynamically from the raw response
    keys, so which attributes exist depends on the OBS version. Missing
    fields (e.g. renderMissedFrames on older OBS builds) must not abort the
    whole stats refresh.
    """
    return getattr(obj, attr, default)


class _LockedReqClient:
    """Proxy over the obsws-python ReqClient that serializes all calls.

    Every ReqClient request is issued on one shared WebSocket, and
    obsws-python's req() discards any frame that is not its own response.
    Two overlapping requests therefore consume each other's replies and
    surface as 'Timeout while trying to send the request' — which the
    coordinator's refresh paths (scene items, stats) and service calls all
    are: concurrent tasks each offloaded to executor threads.

    A thread-level lock suffices because every call runs on an executor
    thread; no call site had to change. Holding the lock across the socket
    read is safe: requests complete in bounded time (OBS socket timeout=10s).
    """

    def __init__(self, client: Any, lock: threading.Lock) -> None:
        object.__setattr__(self, "_wrapped", client)
        object.__setattr__(self, "_lock", lock)

    def __getattr__(self, name: str):
        target = getattr(object.__getattribute__(self, "_wrapped"), name)
        if not callable(target):
            return target
        lock = object.__getattribute__(self, "_lock")

        def call(*args: Any, **kwargs: Any) -> Any:
            with lock:
                return target(*args, **kwargs)

        return call


def _b64decode_safe(b64: str) -> bytes | None:
    """Base64 decode with padding repair and truncation salvage.

    Handles the real-world OBS screenshot quirks:
    - padded or unpadded base64 (repair the padding),
    - whitespace/newlines embedded by some OBS builds (stripped),
    - data-URL style payloads ("data:image/jpeg;base64,...") (prefix removed),
    - truncated payloads: a data length of 1 (mod 4) cannot exist in complete
      base64 — the response lost its final chars. Salvage drops the orphan
      tail (losing at most the last ~2 image bytes), which JPEG tolerates.
    Returns None if the payload cannot decode to anything usable.
    """
    b64 = b64.strip().replace("\n", "").replace("\r", "").replace(" ", "")
    if not b64:
        return None
    if "," in b64 and "base64" in b64:
        b64 = b64.split(",", 1)[1]
    remaining = len(b64) % 4
    if remaining == 1:
        # Impossible in complete base64 → truncated tail; drop the orphan char
        # and continue (last quad decodes 2 of its 3 bytes).
        b64 = b64[:-1]
        remaining = 0
    if remaining:
        b64 += "=" * (4 - remaining)
    try:
        return base64.b64decode(b64)
    except (ValueError, TypeError) as err:
        _LOGGER.debug("b64 decode failed (len=%d chars): %s", len(b64), err)
        return None


def _looks_like_jpeg(data: bytes | None) -> bool:
    """Cheap JPEG signature check (SOI marker)."""
    return bool(data) and data[:2] == b"\xff\xd8"

# Suppress obsws_python's verbose exception logging for 604 (not available) errors.
# The library logs every OBSSDKRequestError at ERROR level with traceback before
# raising, even for expected conditions like "VirtualCam not available" or
# "input does not support audio". We catch these ourselves, so silence the library.
logging.getLogger("obsws_python").setLevel(logging.CRITICAL)

SIGNAL_OBS_UPDATE = f"{DOMAIN}_update"


class OBSWebSocketCoordinator(DataUpdateCoordinator):
    """Coordinator for OBS WebSocket connection."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        host: str,
        port: int,
        password: str | None,
        entry_id: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=None,  # Event-driven, not polling
        )
        self._host = host
        self._port = port
        self._password = password
        self._entry_id = entry_id
        self._client = None
        self._event_client = None
        self._client_lock: threading.Lock = threading.Lock()
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

        # Stream stats
        self._stats_fail_count: int = 0
        self._stream_bytes: int = 0
        self._stream_duration: int = 0  # milliseconds
        self._stream_skipped_frames: int = 0
        self._stream_total_frames: int = 0
        self._stream_congestion: float = 0.0
        self._stream_reconnecting: bool = False

        # System stats (GetStats)
        self._cpu_usage: float = 0.0
        self._memory_usage: float = 0.0  # MB
        self._active_fps: float = 0.0
        self._render_skipped_frames: int = 0
        self._render_total_frames: int = 0
        self._available_disk_space: float = 0.0  # MB
        self._avg_frame_render_time: float = 0.0  # ms
        self._render_missed_frames: int = 0

        # Stats polling task
        self._stats_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None


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

    # === Stream Stats ===

    @property
    def stream_bytes(self) -> int:
        return self._stream_bytes

    @property
    def stream_duration(self) -> int:
        return self._stream_duration

    @property
    def stream_skipped_frames(self) -> int:
        return self._stream_skipped_frames

    @property
    def stream_total_frames(self) -> int:
        return self._stream_total_frames

    @property
    def stream_congestion(self) -> float:
        return self._stream_congestion

    @property
    def stream_reconnecting(self) -> bool:
        return self._stream_reconnecting

    # === System Stats ===

    @property
    def cpu_usage(self) -> float:
        return self._cpu_usage

    @property
    def memory_usage(self) -> float:
        return self._memory_usage

    @property
    def active_fps(self) -> float:
        return self._active_fps

    @property
    def render_skipped_frames(self) -> int:
        return self._render_skipped_frames

    @property
    def render_total_frames(self) -> int:
        return self._render_total_frames

    @property
    def available_disk_space(self) -> float:
        return self._available_disk_space

    @property
    def avg_frame_render_time(self) -> float:
        return self._avg_frame_render_time

    @property
    def render_missed_frames(self) -> int:
        return self._render_missed_frames

    async def async_connect(self, skip_initial_refresh: bool = False) -> None:
        """Connect to OBS WebSocket."""
        import obsws_python as obs

        # ReqClient and EventClient constructors do blocking I/O (WebSocket connect + auth)
        raw_client = await self.hass.async_add_executor_job(
            lambda: obs.ReqClient(
                host=self._host,
                port=self._port,
                password=self._password or "",
                timeout=10,
            )
        )
        # Serialize all requests: they share one WebSocket and overlapping
        # calls would consume each other's responses (see _LockedReqClient).
        self._client = _LockedReqClient(raw_client, self._client_lock)

        # Get initial state (unless deferred to after entity setup)
        if not skip_initial_refresh:
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

        # Start stats polling (OBS doesn't push stats as events)
        self._stats_task = self.hass.async_create_background_task(
            self._stats_loop(), "obs_stats_poll"
        )
        self.last_update_success = True

    async def _cleanup_clients(self) -> None:
        """Tear down client objects without logging noisy disconnect errors."""
        if self._stats_task:
            self._stats_task.cancel()
            self._stats_task = None

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

    def _is_connection_error(self, err: Exception) -> bool:
        """Return True when an exception indicates a broken OBS connection."""
        # obsws-python 1.8.0+ wraps Connection-Errors in OBSSDKError /
        # OBSSDKRequestError / OBSSDKTimeoutError — they inherit from
        # Exception (NOT OSError), so they fall through isinstance() checks
        # below. Match them defensively.
        try:
            from obsws_python.error import (  # type: ignore
                OBSSDKError,
                OBSSDKRequestError,
                OBSSDKTimeoutError,
            )

            if isinstance(
                err, (OBSSDKError, OBSSDKRequestError, OBSSDKTimeoutError)
            ):
                return True
        except ImportError:
            pass

        if isinstance(
            err,
            (
                BrokenPipeError,
                ConnectionError,
                ConnectionResetError,
                socket.timeout,
                TimeoutError,
                OSError,
            ),
        ):
            return True

        message = str(err).lower()
        return any(
            text in message
            for text in (
                "broken pipe",
                "connection refused",
                "connection reset",
                "timed out",
                "socket is already closed",
                "connection is already closed",
                "not connected",
                "failed to connect",
                "request failed",
                "stream is closed",
                "websocket is closed",
                "already closed",
            )
        )

    def _schedule_reconnect(self) -> None:
        """Start reconnect loop if none is running."""
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = self.hass.async_create_background_task(
            self._async_reconnect_loop(), "obs_reconnect"
        )

    async def _handle_connection_loss(self, context: str, err: Exception) -> None:
        """Mark coordinator disconnected and trigger reconnect attempts."""
        _LOGGER.warning(
            "Lost OBS WebSocket connection to %s:%s during %s: %s",
            self._host,
            self._port,
            context,
            err,
        )
        await self._cleanup_clients()
        self.last_update_success = False
        self._stream_reconnecting = False
        self._notify_update()
        self._schedule_reconnect()

    async def _async_reconnect_loop(self) -> None:
        """Reconnect to OBS until successful or unloaded."""
        try:
            while True:
                try:
                    _LOGGER.info(
                        "Attempting OBS WebSocket reconnect to %s:%s",
                        self._host,
                        self._port,
                    )
                    await self.async_connect(skip_initial_refresh=True)
                    await self._refresh_state()
                    self.last_update_success = True
                    self._notify_update()
                    _LOGGER.info(
                        "Reconnected to OBS WebSocket at %s:%s",
                        self._host,
                        self._port,
                    )
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as err:
                    await self._cleanup_clients()
                    self.last_update_success = False
                    self._notify_update()
                    _LOGGER.warning(
                        "OBS WebSocket reconnect to %s:%s failed: %s",
                        self._host,
                        self._port,
                        err,
                    )
                    await asyncio.sleep(RECONNECT_INTERVAL)
        finally:
            self._reconnect_task = None

    async def _async_control_call(self, action: str, func, *args):
        """Execute an OBS control call with friendly HA errors.

        If a connection error occurs (BrokenPipeError, OBSSDKRequestError, …)
        we cancel any background reconnect, reconnect inline and retry the
        call once. This way the first click after an OBS-side disconnect goes
        through instead of having to click again.
        """
        if not self._client:
            self._schedule_reconnect()
            raise HomeAssistantError(
                f"OBS Studio at {self._host}:{self._port} is disconnected. Reconnect was scheduled."
            )

        try:
            return await self.hass.async_add_executor_job(func, *args)
        except Exception as err:
            if not self._is_connection_error(err):
                raise HomeAssistantError(
                    f"OBS action '{action}' failed: {err}"
                ) from err

            # Connection error — try inline reconnect + retry once
            await self._handle_connection_loss(action, err)

            # Cancel any background reconnect loop to avoid racing
            if self._reconnect_task and not self._reconnect_task.done():
                self._reconnect_task.cancel()
                try:
                    await self._reconnect_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._reconnect_task = None

            _LOGGER.info(
                "Inline reconnect to OBS %s:%s after failed '%s'",
                self._host,
                self._port,
                action,
            )
            try:
                await self.async_connect(skip_initial_refresh=True)
                await self._refresh_state()
            except Exception as reconnect_err:
                self._schedule_reconnect()
                raise HomeAssistantError(
                    f"OBS Studio at {self._host}:{self._port} is disconnected. "
                    f"Inline reconnect failed: {reconnect_err}"
                ) from err

            # Retry the original action on the freshly reconnected client
            try:
                return await self.hass.async_add_executor_job(func, *args)
            except Exception as retry_err:
                if self._is_connection_error(retry_err):
                    await self._handle_connection_loss(f"{action} (retry)", retry_err)
                    self._schedule_reconnect()
                    raise HomeAssistantError(
                        f"OBS Studio at {self._host}:{self._port} is disconnected after retry."
                    ) from retry_err
                raise HomeAssistantError(
                    f"OBS action '{action}' failed on retry: {retry_err}"
                ) from retry_err

    async def async_disconnect(self) -> None:
        """Disconnect from OBS WebSocket."""
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        await self._cleanup_clients()

        _LOGGER.info("Disconnected from OBS WebSocket")

    async def refresh_state(self) -> None:
        """Public wrapper for _refresh_state."""
        await self._refresh_state()

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
            if self._is_connection_error(err):
                await self._handle_connection_loss("refreshing current scene", err)
                return
            _LOGGER.error("Error getting current scene: %s", err)

        # Streaming status
        try:
            status = await self.hass.async_add_executor_job(
                self._client.get_stream_status
            )
            self._streaming = bool(status.output_active) if status else False
        except Exception as err:
            if self._is_connection_error(err):
                await self._handle_connection_loss("refreshing stream status", err)
                return
            _LOGGER.error("Error getting stream status: %s", err)

        # Recording status
        try:
            rec = await self.hass.async_add_executor_job(
                self._client.get_record_status
            )
            self._recording = bool(rec.output_active) if rec else False
        except Exception as err:
            if self._is_connection_error(err):
                await self._handle_connection_loss("refreshing record status", err)
                return
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
            if self._is_connection_error(err):
                await self._handle_connection_loss("refreshing scene list", err)
                return
            _LOGGER.error("Error getting scene list: %s", err)

        # Audio inputs
        await self._refresh_audio_inputs()

        # Scene item visibility
        await self._refresh_scene_items()

        # Mark as successfully updated so CoordinatorEntity.available returns True
        self.last_update_success = True

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
        target[name] = {"muted": muted, "volume_db": round(vol_db, 1)}

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

    async def _stats_loop(self) -> None:
        """Poll OBS for stream and system stats every STATS_POLL_INTERVAL seconds.

        Reconnect only after STATS_FAIL_THRESHOLD consecutive poll failures —
        a single OBS timeout (encoder/GPU stall, short freeze) must not tear
        down a connection that recovers on the next poll.
        """
        while True:
            try:
                await asyncio.sleep(STATS_POLL_INTERVAL)
                await self._refresh_stream_stats()
                await self._refresh_system_stats()
                self._notify_update()
                self._stats_fail_count = 0
            except asyncio.CancelledError:
                raise
            except Exception as err:
                if not self._is_connection_error(err):
                    _LOGGER.debug("Stats poll error: %s", err)
                    continue
                self._stats_fail_count += 1
                if self._stats_fail_count < STATS_FAIL_THRESHOLD:
                    _LOGGER.warning(
                        "OBS stats poll to %s:%s failed with a connection error "
                        "(%s of %s): %s — polling again before reconnecting",
                        self._host,
                        self._port,
                        self._stats_fail_count,
                        STATS_FAIL_THRESHOLD,
                        err,
                    )
                    continue
                self._stats_fail_count = 0
                await self._handle_connection_loss("refreshing stats", err)

    async def _refresh_stream_stats(self) -> None:
        """Refresh stream statistics from OBS GetStreamStatus."""
        if not self._client:
            return
        try:
            status = await self.hass.async_add_executor_job(
                self._client.get_stream_status
            )
            if not status:
                return
            self._streaming = _bool_stat(_stat(status, "output_active", False))
            self._stream_bytes = _stat(status, "output_bytes") or 0
            self._stream_duration = _stat(status, "output_duration") or 0
            self._stream_congestion = _stat(status, "output_congestion") or 0.0
            self._stream_reconnecting = _bool_stat(
                _stat(status, "output_reconnecting", False)
            )
            self._stream_skipped_frames = _stat(status, "output_skipped_frames") or 0
            self._stream_total_frames = _stat(status, "output_total_frames") or 0
        except Exception as err:
            if self._is_connection_error(err):
                # Let _stats_loop decide when to actually reconnect
                raise
            _LOGGER.debug("Could not refresh stream stats: %s", err)

    async def _refresh_system_stats(self) -> None:
        """Refresh system statistics from OBS GetStats."""
        if not self._client:
            return
        try:
            stats = await self.hass.async_add_executor_job(
                self._client.get_stats
            )
            if not stats:
                return
            self._cpu_usage = _stat(stats, "cpu_usage") or 0.0
            self._memory_usage = _stat(stats, "memory_usage") or 0.0
            self._active_fps = _stat(stats, "active_fps") or 0.0
            self._render_skipped_frames = _stat(stats, "render_skipped_frames") or 0
            self._render_total_frames = _stat(stats, "render_total_frames") or 0
            self._available_disk_space = _stat(stats, "available_disk_space") or 0.0
            self._avg_frame_render_time = (
                _stat(stats, "average_frame_render_time") or 0.0
            )
            # renderMissedFrames is not returned by all OBS versions
            self._render_missed_frames = _stat(stats, "render_missed_frames") or 0
        except Exception as err:
            if self._is_connection_error(err):
                # Let _stats_loop decide when to actually reconnect
                raise
            _LOGGER.debug("Could not refresh system stats: %s", err)

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
        # hass.create_task is thread-safe, safe to call from the obsws
        # event callback thread directly.
        self.hass.create_task(self._refresh_scenes(), name="obs_refresh_scenes")
        self.hass.create_task(
            self._refresh_scene_items(), name="obs_refresh_scene_items"
        )
        self._fire_event("SceneListChanged", data)

    def on_scene_item_enable_state_changed(self, data) -> None:
        """Handle SceneItemEnableStateChanged event — trigger async refresh."""
        self.hass.create_task(
            self._refresh_scene_items(), name="obs_refresh_scene_items"
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
                self._audio_inputs[input_name] = {"muted": False, "volume_db": round(vol_db, 1)}
            else:
                self._audio_inputs[input_name]["volume_db"] = round(vol_db, 1)
        self._fire_event("InputVolumeChanged", data)
        self._notify_update()

    def on_input_created(self, data) -> None:
        """Handle InputCreated event — refresh audio inputs."""
        self.hass.create_task(
            self._refresh_audio_inputs(), name="obs_refresh_audio_inputs"
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
        self.hass.loop.call_soon_threadsafe(self.async_update_listeners)
        self.hass.loop.call_soon_threadsafe(
            async_dispatcher_send, self.hass, SIGNAL_OBS_UPDATE, self._entry_id
        )

    # === Control Methods ===

    async def set_scene(self, scene_name: str) -> None:
        await self._async_control_call(
            "set_scene", lambda: self._client.set_current_program_scene(scene_name)
        )

    async def start_streaming(self) -> None:
        await self._async_control_call("start_streaming", lambda: self._client.start_stream())

    async def stop_streaming(self) -> None:
        await self._async_control_call("stop_streaming", lambda: self._client.stop_stream())

    async def start_recording(self) -> None:
        await self._async_control_call("start_recording", lambda: self._client.start_record())

    async def stop_recording(self) -> None:
        await self._async_control_call("stop_recording", lambda: self._client.stop_record())

    async def toggle_mute(self, source: str) -> None:
        await self._async_control_call(
            "toggle_mute", lambda: self._client.toggle_input_mute(source)
        )

    async def set_mute(self, source: str, muted: bool) -> None:
        await self._async_control_call(
            "set_mute", lambda: self._client.set_input_mute(source, muted)
        )

    async def start_replay_buffer(self) -> None:
        await self._async_control_call(
            "start_replay_buffer", lambda: self._client.start_replay_buffer()
        )

    async def stop_replay_buffer(self) -> None:
        await self._async_control_call(
            "stop_replay_buffer", lambda: self._client.stop_replay_buffer()
        )

    async def start_virtualcam(self) -> None:
        await self._async_control_call(
            "start_virtualcam", lambda: self._client.start_virtual_cam()
        )

    async def stop_virtualcam(self) -> None:
        await self._async_control_call(
            "stop_virtualcam", lambda: self._client.stop_virtual_cam()
        )

    async def get_input_volume(self, source: str) -> dict:
        return await self._async_control_call(
            "get_input_volume", lambda: self._client.get_input_volume(source)
        )

    async def set_input_volume(self, source: str, volume_db: float) -> None:
        await self._async_control_call(
            "set_input_volume",
            lambda: self._client.set_input_volume(source, None, volume_db),
        )

    async def set_scene_item_enabled(self, scene_name: str, source_name: str, enabled: bool) -> None:
        """Set visibility of a source within a scene."""
        # Find the scene item id for the source in the scene
        items = await self._async_control_call(
            "get_scene_item_list", lambda: self._client.get_scene_item_list(scene_name)
        )
        item_id = None
        for item in (items.scene_items if items else []):
            if item.get("sourceName") == source_name:
                item_id = item.get("sceneItemId")
                break
        if item_id is not None:
            await self._async_control_call(
                "set_scene_item_enabled",
                lambda: self._client.set_scene_item_enabled(scene_name, item_id, enabled),
            )
            # Update local state
            if scene_name in self._scene_items:
                self._scene_items[scene_name][source_name] = enabled
            self._notify_update()
        else:
            _LOGGER.warning("Source %s not found in scene %s", source_name, scene_name)

    # Screenshot attempts, largest first. If OBS truncates the base64 payload
    # of a big screenshot (seen in the wild: ~94 KB JPEG cut mid-payload),
    # smaller formats are significantly less likely to be cut. On truncation
    # the salvage decoder may still return a partial (tail-less) image, which
    # is accepted — retries only happen when nothing usable came back.
    _PREVIEW_SIZES: tuple[tuple[int, int, int], ...] = (
        (640, 360, 80),
        (480, 270, 60),
        (320, 180, 40),
    )

    async def get_scene_preview(self, scene_name: str | None = None) -> bytes | None:
        """Get a preview screenshot of the current or specified scene.

        Tries progressively smaller JPEG sizes; returns the first payload that
        decodes to a valid JPEG.
        """
        if not self._client:
            _LOGGER.debug("get_scene_preview: no client")
            return None
        try:
            if scene_name is None:
                scene_name = self._scene
            if scene_name is None:
                _LOGGER.debug("get_scene_preview: no current scene")
                return None

            for attempt, (width, height, quality) in enumerate(self._PREVIEW_SIZES):
                screenshot = await self.hass.async_add_executor_job(
                    self._client.get_source_screenshot,
                    scene_name,
                    "jpg",
                    width,
                    height,
                    quality,
                )
                # as_dataclass converts top-level keys to snake_case:
                # 'imageData' -> 'image_data'
                b64_data: str | None = None
                if hasattr(screenshot, "image_data"):
                    b64_data = screenshot.image_data
                elif hasattr(screenshot, "img"):
                    b64_data = screenshot.img
                elif screenshot is not None:
                    _LOGGER.warning(
                        "get_scene_preview: unexpected response: %s", type(screenshot)
                    )
                    continue

                if not b64_data:
                    continue

                image = _b64decode_safe(b64_data)
                if image and _looks_like_jpeg(image):
                    if attempt:
                        _LOGGER.debug(
                            "get_scene_preview: '%s' ok on retry %d (%dx%d q%d)",
                            scene_name, attempt, width, height, quality,
                        )
                    return image
                has_next = attempt + 1 < len(self._PREVIEW_SIZES)
                retry_info = (
                    " — retrying smaller "
                    + "%dx%d q%d" % self._PREVIEW_SIZES[attempt + 1]
                    if has_next
                    else " — all sizes exhausted"
                )
                _LOGGER.warning(
                    "Error getting scene preview for '%s': payload of %d chars did "
                    "not decode to a JPEG (len%%4=%d)%s",
                    scene_name,
                    len(b64_data),
                    len(b64_data.replace("\n", "").replace("\r", "").replace(" ", "")) % 4,
                    retry_info,
                )
            return None
        except Exception as err:
            _LOGGER.warning("Error getting scene preview for '%s': %s", scene_name, err)
            return None
        return None
