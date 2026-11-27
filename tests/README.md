# Tests

End-to-end tests for the OBS WebSocket integration against a real
HomeAssistant runtime with fake `obsws_python` clients (no OBS needed).

## Setup

```bash
pip install --target /tmp/ha-test-env \
    pytest-homeassistant-custom-component==0.13.375 pytest==8.4.2
```

Run the suite (works on the PHACC-pinned HA 2026.10.4 AND on HA 2026.11.x):

```bash
PYTHONPATH=/tmp/ha-test-env python3 tests/run_pytest.py -q
```

To test against a specific HA version, install it as the last step — the
env keeps both stacks and `homeassistant` wins at import time:

```bash
pip install --target /tmp/ha-test-env2 --no-deps \
    pytest-homeassistant-custom-component==0.13.375
pip install --target /tmp/ha-test-env2 homeassistant==2026.11.3 \
    pytest==8.4.2
```

(Installing PHACC and `homeassistant==2026.11.3` in ONE pip call fails:
PHACC pins `homeassistant==2026.10.4` exactly. Use the two-step above.)

## Why `tests/run_pytest.py`?

Use it instead of plain `pytest` on HA >= 2026.11. It applies two shims,
both `hasattr`-guarded no-ops on 2026.10:

1. **`httpx2.alias_httpx()`** — HA 2026.11 replaced httpx with httpx2 and
   aliases it during the `homeassistant` import. PHACC's pytest
   entry-point (`pytest11`) imports httpx-dependent modules before any
   conftest runs, so the alias must be installed even earlier. (A manual
   alternative is patching the env's `plugins.py` to `import
   homeassistant` before `import respx`.)
2. **`_clear_logger_overwrites`** — HA 2026.11.3 *moved* it from
   `homeassistant.components.logger` to
   `homeassistant.components.logger.helpers` (it was not removed).
   PHACC's stale import path is patched at runtime. (Manual alternative:
   fix the import block in the env's `common.py`.)

Once a PHACC release targeting HA 2026.11 ships, the runner can retire.

## What is covered

- Full integration setup incl. the image platform (fake OBS clients)
- Coordinator-driven screenshot refresh fills the image cache
- `GET /api/image_proxy/<entity>?token=...` serves the exact JPEG bytes
- 5-second periodic pull via the entity timer (`async_fire_time_changed`)
- Truncated base64 payloads (remainder 1 mod 4) are salvaged — plus
  decoder unit tests outside HA (see commit `e73586e`)
- Retry ladder: unusable large screenshots fall back to smaller sizes
- `GetStats` fake deliberately omits `render_missed_frames` (regression
  guard for OBS builds that don't send it)
