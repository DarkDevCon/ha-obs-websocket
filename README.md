# ha-obs-websocket

<p align="center">
  <img src="custom_components/obs_websocket/icon.png" width="128" alt="OBS Studio WebSocket Logo">
</p>

Home Assistant custom integration for OBS Studio via WebSocket.

## Features

- 🎥 **Scene Selector** — Dropdown to switch between scenes
- 🎬 **Streaming & Recording Control** — Switches for stream, recording, replay buffer, virtual camera
- 🔊 **Volume Sliders** — Per audio source in dB (-60 to 0), rounded to 1 decimal place — *disabled by default, enable in entity registry*
- 👁️ **Source Visibility Toggles** — Show/hide sources per scene — *disabled by default, enable in entity registry*
- 📊 **Sensors** — Current scene, streaming/recording/replay/virtualcam status, scene count
- 🔌 **Event-Driven** — Real-time updates via OBS WebSocket events (no polling)
- 🎛️ **Services** — `set_scene`, `start_streaming`, `stop_streaming`, `start_recording`, `stop_recording`, `toggle_mute`
- 🌐 **Multi-Instance** — Connect to multiple OBS Studio instances simultaneously
- 🌐 **Multi-Language** — English + German UI strings

## Requirements

- OBS Studio 28+ (includes WebSocket server)
- WebSocket server enabled in OBS: Tools → WebSocket Server Settings
- Home Assistant 2024.x+
- Python package `obsws-python` (auto-installed by HACS/HA)

## Installation

### HACS (recommended)
1. Add this repo as a Custom Repository in HACS (category: Integration)
2. Install "OBS Studio WebSocket"
3. Restart Home Assistant

### Manual
1. Copy `custom_components/obs_websocket/` to your HA `custom_components/` directory
2. Restart Home Assistant

## Configuration

1. In Home Assistant: **Settings → Devices & Services → Add Integration**
2. Search for **"OBS Studio WebSocket"**
3. Enter:
   - **Host** — IP address of your OBS machine (e.g. `192.168.1.100`)
   - **Port** — `4455` (default)
   - **Password** — Your OBS WebSocket password (Tools → WebSocket Server Settings in OBS)
4. **Repeat** for additional OBS instances — each gets its own device entry

## Entities

### Sensors
| Entity | Description |
|--------|-------------|
| Current Scene | Active scene name + scene list as attribute |
| Streaming | on / off |
| Recording | on / off |
| Replay Buffer | on / off |
| Virtual Camera | on / off |
| Scene Count | Number of scenes |

### Select
| Entity | Description |
|--------|-------------|
| Scene | Dropdown with all available scenes |

### Switches
| Entity | Description |
|--------|-------------|
| Streaming | Start / stop stream |
| Recording | Start / stop recording |
| Replay Buffer | Start / stop replay buffer |
| Virtual Camera | Start / stop virtual camera |
| Visible: {source} ({scene}) | Show/hide a source in a specific scene *(disabled by default)* |

### Number (Volume Sliders)
| Entity | Description |
|--------|-------------|
| Volume: {source} | Volume in dB per audio source (-60 to 0, step 0.5) *(disabled by default)* |

> Volume values are rounded to 1 decimal place for clean display.

### Services
| Service | Parameters | Description |
|---------|-----------|-------------|
| `obs_websocket.set_scene` | `scene` (req), `entry_id` (opt) | Switch to a scene |
| `obs_websocket.start_streaming` | `entry_id` (opt) | Start streaming |
| `obs_websocket.stop_streaming` | `entry_id` (opt) | Stop streaming |
| `obs_websocket.start_recording` | `entry_id` (opt) | Start recording |
| `obs_websocket.stop_recording` | `entry_id` (opt) | Stop recording |
| `obs_websocket.toggle_mute` | `source` (req), `entry_id` (opt) | Toggle mute on an audio source |

> **Multi-Instance:** `entry_id` is optional. If omitted, services apply to all or the first matching instance.

## Disabled Entities

Volume sliders and source visibility switches are created with `entity_category=config` and **disabled by default** to avoid clutter. Enable them in:

**Settings → Integrations → OBS Studio WebSocket → Entities**

## Technical Notes

- **Event-driven:** The coordinator uses OBS WebSocket events for real-time state updates — no polling interval. All OBS callbacks are thread-safe via `call_soon_threadsafe`.
- **Audio inputs:** Regular inputs (GetInputList) and special inputs (GetSpecialInputs — Desktop Audio, Mic/Aux) are combined.
- **Multi-instance:** Each config entry creates its own coordinator and device. Services route by `entry_id` or broadcast to all instances.

## Development

```bash
git clone https://github.com/DarkDevCon/ha-obs-websocket.git
cd ha-obs-websocket
```

The integration code lives in `custom_components/obs_websocket/`.

### Structure
| File | Purpose |
|------|---------|
| `coordinator.py` | WebSocket connection, state management, event callbacks |
| `entity.py` | Base entity class |
| `sensor.py` | Sensor entities (scene, stream, recording, etc.) |
| `switch.py` | Switch entities (stream, recording, replay, virtualcam, visibility) |
| `select.py` | Scene selector dropdown |
| `number.py` | Volume slider entities |
| `config_flow.py` | Config flow (host, port, password) |
| `const.py` | Constants (domain, config keys, signal names) |

## License

MIT