"""Config flow for Huawei Solar integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError

from homeassistant.const import CONF_HOST,CONF_PORT
from .const import (
    DOMAIN,
    CONF_BATTERY,
    CONF_OPTIMIZERS,
    CONF_SLAVE,
    ATTR_MODEL_NAME,
    ATTR_SERIAL_NUMBER,
)

from huawei_solar import AsyncHuaweiSolar, ConnectionException

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 502

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, DEFAULT_PORT):int,
        vol.Optional(CONF_OPTIMIZERS, default=False): bool,
        vol.Optional(CONF_BATTERY, default=False): bool,
        vol.Optional(CONF_SLAVE, default=0): int,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """

    inverter = AsyncHuaweiSolar(host=data[CONF_HOST], port=data.get(CONF_PORT, DEFAULT_PORT) slave=data[CONF_SLAVE])

    try:
        model_name = (await inverter.get(ATTR_MODEL_NAME)).value
        serial_number = (await inverter.get(ATTR_SERIAL_NUMBER)).value

        # Return info that you want to store in the config entry.
        return dict(model_name=model_name, serial_number=serial_number)
    except ConnectionException as ex:
        raise CannotConnect from ex
    finally:
        # Cleanup this inverter object explicitely to prevent it from trying to maintain a modbus connection
        if inverter._client:
            inverter._client.stop()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Huawei Solar."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            info = await validate_input(self.hass, user_input)

            await self.async_set_unique_id(info["serial_number"])
            self._abort_if_unique_id_configured()
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
        else:
            return self.async_create_entry(title=info["model_name"], data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
