"""Fake obsws_python module for integration tests.

Mimics the surface of obsws-python used by the coordinator: dynamic
dataclasses built from raw response keys (SimpleNamespace is close enough —
the coordinator only reads snake_case attributes plus camelCase raw dicts).
"""
from __future__ import annotations

import base64
import io
import sys
from types import ModuleType, SimpleNamespace

from PIL import Image


def make_jpeg(width: int = 640, height: int = 360, color=(190, 45, 20)) -> bytes:
    """Deterministic JPEG bytes for snapshot assertions."""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="JPEG", quality=80)
    return buf.getvalue()


class FakeReqClient:
    """Covers every ReqClient method the coordinator calls."""

    def __init__(self, *args, **kwargs):
        self.screenshot_bytes = make_jpeg()
        self.disconnect_count = 0
        # (width, height) of successful get_source_screenshot calls
        self.screenshot_requests: list[tuple[int, ...]] = []
        # When True, screenshots of 640px width come back as unusable
        # garbage — simulating OBS truncated/corrupt large payloads —
        # while the 480px retry succeeds.
        self.fail_large_screenshots = False

    def _screenshot(self, width, height, quality):
        self.screenshot_requests.append((width, height, quality))
        if self.fail_large_screenshots and width >= 640:
            return "zzz!"  # decodes to nothing usable
        return base64.b64encode(self.screenshot_bytes).decode()

    # --- state ---
    def get_current_program_scene(self):
        return SimpleNamespace(current_program_scene_name="MultiView")

    def get_stream_status(self):
        return SimpleNamespace(
            output_active=True,
            output_bytes=123456,
            output_duration=98765,
            output_congestion=0.1,
            output_reconnecting=False,  # legacy-OBS string form also exercised below
            output_skipped_frames=0,
            output_total_frames=1000,
        )

    def get_record_status(self):
        return SimpleNamespace(output_active=False)

    def get_replay_buffer_status(self):
        return SimpleNamespace(output_active=False)

    def get_virtual_cam_status(self):
        return SimpleNamespace(output_active=False)

    def get_scene_list(self):
        return SimpleNamespace(
            scenes=[
                {"sceneIndex": 0, "sceneName": "MultiView"},
                {"sceneIndex": 1, "sceneName": "Sounds"},
            ]
        )

    def get_input_list(self):
        return SimpleNamespace(
            inputs=[{"inputName": "Nistkasten-1", "inputUuid": "u1"}]
        )

    def get_special_inputs(self):
        raise RuntimeError("no special inputs")

    def get_input_mute(self, name):
        return SimpleNamespace(input_muted=False)

    def get_input_volume(self, name):
        return SimpleNamespace(input_volume_db=-15.0)

    def get_scene_item_list(self, scene_name):
        return SimpleNamespace(
            scene_items=[
                {"sourceName": "Kamera", "sceneItemEnabled": True,
                 "sceneItemVisible": True, "sceneItemId": 1},
                {"sourceName": "Feed", "sceneItemEnabled": False,
                 "sceneItemVisible": False, "sceneItemId": 2},
            ]
        )

    def get_stats(self):
        # NOTE: deliberately WITHOUT render_missed_frames — regression guard
        # for the 'GetStatsDataclass has no attribute' fix.
        return SimpleNamespace(
            cpu_usage=15.0,
            memory_usage=2.5,
            available_disk_space=100.0,
            active_fps=60.0,
            average_frame_render_time=0.4,
            render_skipped_frames=1,
            render_total_frames=5000,
            output_skipped_frames=0,
            output_total_frames=5000,
        )

    def get_source_screenshot(self, name, img_format, width, height, quality):
        return SimpleNamespace(image_data=self._screenshot(width, height, quality))

    def disconnect(self):
        self.disconnect_count += 1


class FakeEventClient:
    def __init__(self, *args, **kwargs):
        self.callback = SimpleNamespace(register=lambda fns: None)

    def disconnect(self):
        pass


def install_fake_module() -> ModuleType:
    """Put a fake `obsws_python` into sys.modules (import used inside coordinator)."""
    module = ModuleType("obsws_python")
    module.ReqClient = FakeReqClient
    module.EventClient = FakeEventClient
    module.__path__ = []  # mark as package so submodule imports fail loudly
    sys.modules["obsws_python"] = module
    return module
