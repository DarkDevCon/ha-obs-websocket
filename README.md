# ha-obs-websocket

Home Assistant custom integration for OBS Studio via WebSocket.

## Features

- 🎥 **Scene Selector** — Dropdown to switch between scenes
- 🎬 **Streaming/Recording Control** — switches and buttons for stream, recording, replay buffer, virtual camera
- 🔊 **Volume Sliders** — per audio source, in dB (-60 to 0)
- 🔇 **Mute Switches** — per audio source
- 👁️ **Source Visibility Toggles** — show/hide sources per scene
- 📸 **Scene Preview** — live camera entity with screenshot of current scene
- 📊 **Sensors** — current scene, streaming/recording/replay/virtualcam status, scene count
- 🔌 **Event-Driven** — real-time updates via OBS WebSocket events (no polling)
- 🎛️ **Services** — `set_scene`, `start_streaming`, `stop_streaming`, `start_recording`, `stop_recording`, `toggle_mute`
- 🌐 **Multi-Instance** — connect to multiple OBS Studio instances simultaneously
- 🌐 **Multi-Language** — English + German UI strings

## Requirements

- OBS Studio 28+ (includes WebSocket server)
- WebSocket server enabled in OBS: Tools → WebSocket Server Settings
- Home Assistant 2024.x+

## Installation

### HACS (recommended)
1. Add this repo as a Custom Repository in HACS
2. Install "OBS Studio WebSocket"
3. Restart Home Assistant

### Manual
1. Copy `custom_components/obs_websocket/` to your HA `custom_components/` directory
2. Restart Home Assistant

## Configuration

1. In Home Assistant: Settings → Devices & Services → Add Integration
2. Search for "OBS Studio WebSocket"
3. Enter:
   - **Host**: IP address of your OBS machine (e.g. `192.168.1.100`)
   - **Port**: `4455` (default)
   - **Password**: Your OBS WebSocket password (Tools → WebSocket Server Settings in OBS)
4. **Repeat** for additional OBS instances — each gets its own device entry

## Entities

### Sensors
| Sensor | Description |
|--------|-------------|
| Current Scene | Active scene name + scene list |
| Streaming | on/off |
| Recording | on/off |
| Replay Buffer | on/off |
| Virtual Camera | on/off |
| Scene Count | Number of scenes |

### Select
| Select | Description |
|--------|-------------|
| Scene | Dropdown with all available scenes |

### Switches
| Switch | Action |
|--------|--------|
| Streaming | Start/Stop stream |
| Recording | Start/Stop recording |
| Replay Buffer | Start/Stop replay buffer |
| Virtual Camera | Start/Stop virtual cam |
| Mute: {source} | Mute/unmute per audio source (auto-created) |
| Visible: {source} ({scene}) | Show/hide source per scene (auto-created) |

### Number (Sliders)
| Number | Description |
|--------|-------------|
| Volume: {source} | Volume in dB per audio source (auto-created, -60 to 0) |

### Camera
| Camera | Description |
|--------|-------------|
| Scene Preview | Live screenshot of current scene (refreshes every 10s) |

### Buttons
| Button | Action |
|--------|--------|
| Start Stream | Start streaming |
| Stop Stream | Stop streaming |
| Start Recording | Start recording |
| Stop Recording | Stop recording |

### Services
| Service | Parameters | Description |
|---------|-----------|-------------|
| `obs_websocket.set_scene` | `scene` (req), `entry_id` (opt) | Switch to a scene |
| `obs_websocket.start_streaming` | `entry_id` (opt) | Start streaming |
| `obs_websocket.stop_streaming` | `entry_id` (opt) | Stop streaming |
| `obs_websocket.start_recording` | `entry_id` (opt) | Start recording |
| `obs_websocket.stop_recording` | `entry_id` (opt) | Stop recording |
| `obs_websocket.toggle_mute` | `source` (req), `entry_id` (opt) | Toggle mute on audio source |

> **Multi-Instance:** `entry_id` is optional. If omitted, services apply to all or the first matching instance.

## Development

```bash
git clone https://github.com/DarkDevCon/ha-obs-websocket.git
cd ha-obs-websocket
```

The integration code lives in `custom_components/obs_websocket/`.

## License

MIT