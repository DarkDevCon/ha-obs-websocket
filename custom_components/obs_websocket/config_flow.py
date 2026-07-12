"""Config flow for OBS WebSocket."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, DEFAULT_PORT

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Optional(CONF_PASSWORD): str,
    }
)


async def _test_connection(
    hass: HomeAssistant, host: str, port: int, password: str | None
) -> bool:
    """Test connection to OBS WebSocket."""
    try:
        import obsws_python as obs

        # ReqClient constructor does blocking I/O — run in executor
        client = await hass.async_add_executor_job(
            obs.ReqClient,
            host,
            port,
            password or "",
            5,  # timeout
        )
        await hass.async_add_executor_job(client.get_version)
        await hass.async_add_executor_job(client.disconnect)
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

            connected = await _test_connection(self.hass, host, port, password)
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
            # Test the new password if provided
            new_password = user_input.get(CONF_PASSWORD)
            if new_password:
                host = self._config_entry.data[CONF_HOST]
                port = self._config_entry.data.get(CONF_PORT, DEFAULT_PORT)
                connected = await _test_connection(self.hass, host, port, new_password)
                if not connected:
                    return self.async_show_form(
                        step_id="init",
                        data_schema=self._build_options_schema(),
                        errors={"base": "cannot_connect"},
                    )

            # Update the config entry data with the new password
            new_data = dict(self._config_entry.data)
            if new_password is not None:
                new_data[CONF_PASSWORD] = new_password
            self.hass.config_entries.async_update_entry(
                self._config_entry, data=new_data
            )

            # Trigger a reload of the config entry
            await self.hass.config_entries.async_reload(self._config_entry.entry_id)

            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self._build_options_schema(),
        )

    def _build_options_schema(self) -> vol.Schema:
        """Build the options schema."""
        return vol.Schema(
            {
                vol.Optional(
                    CONF_PASSWORD,
                    default=self._config_entry.data.get(CONF_PASSWORD, ""),
                ): str,
            }
        )