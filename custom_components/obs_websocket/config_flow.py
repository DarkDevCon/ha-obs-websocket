"""Config flow for OBS WebSocket."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import callback

from .const import DOMAIN, DEFAULT_PORT

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_PASSWORD): str,
    }
)


async def _test_connection(host: str, port: int, password: str | None) -> bool:
    """Test connection to OBS WebSocket."""
    try:
        import obsws_python as obs

        client = obs.ReqClient(
            host=host,
            port=port,
            password=password or "",
            timeout=5,
        )
        client.get_version()
        return True
    except Exception as err:
        _LOGGER.error("OBS WebSocket connection test failed: %s", err)
        return False


class OBSWebSocketConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for OBS WebSocket."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            password = user_input.get(CONF_PASSWORD)

            # Check for duplicate
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            connected = await _test_connection(host, port, password)
            if connected:
                return self.async_create_entry(
                    title=f"OBS {host}:{port}",
                    data=user_input,
                )
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow."""
        return OBSWebSocketOptionsFlow(config_entry)


class OBSWebSocketOptionsFlow(config_entries.OptionsFlow):
    """Options flow for OBS WebSocket."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_PASSWORD,
                        default=self._config_entry.data.get(CONF_PASSWORD, ""),
                    ): str,
                }
            ),
        )