"""Constants for the OBS WebSocket integration."""
DOMAIN = "obs_websocket"

CONF_HOST = "host"
CONF_PORT = "port"
CONF_PASSWORD = "password"

DEFAULT_PORT = 4455

# Event types
EVENT_OBS_EVENT = "obs_websocket_event"

# Sensor attributes
ATTR_SCENE = "scene"
ATTR_SCENE_NAME = "scene_name"
ATTR_STREAMING = "streaming"
ATTR_RECORDING = "recording"
ATTR_REPLAY_BUFFER = "replay_buffer"
ATTR_VIRTUALCAM = "virtualcam"