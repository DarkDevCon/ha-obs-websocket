# ha-obs-websocket

Home Assistant custom integration for OBS Studio via WebSocket.

## Features

- 🎥 **Scene Monitoring** — current scene sensor + scene list
- 🎬 **Streaming/Recording Control** — switches and buttons for stream, recording, replay buffer, virtual camera
- 🔌 **Event-Driven** — real-time updates via OBS WebSocket events (no polling)
- 🎛️ **Services** — `set_scene`, `start_streaming`, `stop_streaming`, `start_recording`, `stop_recording`, `toggle_mute`
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

### Switches
| Switch | Action |
|--------|--------|
| Streaming | Start/Stop stream |
| Recording | Start/Stop recording |
| Replay Buffer | Start/Stop replay buffer |
| Virtual Camera | Start/Stop virtual cam |

### Buttons
| Button | Action |
|--------|--------|
| Start Stream | Start streaming |
| Stop Stream | Stop streaming |
| Start Recording | Start recording |
| Stop Recording | Stop recording |

### Services
| Service | Description |
|---------|-------------|
| `obs_websocket.set_scene` | Switch to a scene (param: `scene`) |
| `obs_websocket.start_streaming` | Start streaming |
| `obs_websocket.stop_streaming` | Stop streaming |
| `obs_websocket.start_recording` | Start recording |
| `obs_websocket.stop_recording` | Stop recording |
| `obs_websocket.toggle_mute` | Toggle mute on audio source (param: `source`) |

## Development

```bash
git clone https://github.com/DarkDevCon/ha-obs-websocket.git
cd ha-obs-websocket
```

The integration code lives in `custom_components/obs_websocket/`.

## License

MIT