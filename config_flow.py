"""Config flow for Huawei Solar integration."""
from __future__ import annotations

import logging
from typing import Any

import homeassistant.helpers.config_validation as cv
import serial.tools.list_ports
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import usb
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_TYPE,
    CONF_USERNAME,
)
from homeassistant.data_entry_flow import FlowResult

from huawei_solar import (
    ConnectionException,
    HuaweiSolarBridge,
    HuaweiSolarException,
    ReadException,
)

from .const import (
    CONF_ENABLE_PARAMETER_CONFIGURATION,
    CONF_SLAVE_IDS,
    DEFAULT_PORT,
    DEFAULT_SERIAL_SLAVE_ID,
    DEFAULT_SLAVE_ID,
    DEFAULT_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_SETUP_NETWORK_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Required(CONF_SLAVE_IDS, default=str(DEFAULT_SLAVE_ID)): str,
        vol.Required(CONF_ENABLE_PARAMETER_CONFIGURATION, default=False): bool,
    }
)

STEP_LOGIN_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME, default=DEFAULT_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

CONF_MANUAL_PATH = "Enter Manually"


async def validate_serial_setup(data: dict[str, Any]) -> dict[str, Any]:
    """Validate the serial device that was passed by the user."""

    bridge = None
    try:
        bridge = await HuaweiSolarBridge.create_rtu(
            port=data[CONF_PORT],
            slave_id=data[CONF_SLAVE_IDS][0],
        )

        _LOGGER.info(
            "Successfully connected to inverter %s with SN %s",
            bridge.model_name,
            bridge.serial_number,
        )

        result = {
            "model_name": bridge.model_name,
            "serial_number": bridge.serial_number,
        }

        # Also validate the other slave-ids
        for slave_id in data[CONF_SLAVE_IDS][1:]:
            try:
                slave_bridge = await HuaweiSolarBridge.create_extra_slave(
                    bridge, slave_id
                )

                _LOGGER.info(
                    "Successfully connected to slave inverter %s: %s with SN %s",
                    slave_id,
                    slave_bridge.model_name,
                    slave_bridge.serial_number,
                )
            except HuaweiSolarException as err:
                _LOGGER.error("Could not connect to slave %s", slave_id)
                raise SlaveException(f"Could not connect to slave {slave_id}") from err

        # Return info that you want to store in the config entry.
        return result

    finally:
        if bridge is not None:
            # Cleanup this inverter object explicitly to prevent it from trying to maintain a modbus connection
            await bridge.stop()


async def validate_network_setup(data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_SETUP_NETWORK_DATA_SCHEMA with values provided by the user.
    """

    bridge = None
    try:
        bridge = await HuaweiSolarBridge.create(
            host=data[CONF_HOST],
            port=data[CONF_PORT],
            slave_id=data[CONF_SLAVE_IDS][0],
        )

        _LOGGER.info(
            "Successfully connected to inverter %s with SN %s",
            bridge.model_name,
            bridge.serial_number,
        )

        result = {
            "model_name": bridge.model_name,
            "serial_number": bridge.serial_number,
        }
        if data[CONF_ENABLE_PARAMETER_CONFIGURATION]:
            # Check if we have write access. If this is not the case, we will
            # need to login (and request the username/password from the user to be
            # able to do this).
            result["has_write_permission"] = await bridge.has_write_permission()

        # Also validate the other slave-ids
        for slave_id in data[CONF_SLAVE_IDS][1:]:
            try:
                slave_bridge = await HuaweiSolarBridge.create_extra_slave(
                    bridge, slave_id
                )

                _LOGGER.info(
                    "Successfully connected to slave inverter %s: %s with SN %s",
                    slave_id,
                    slave_bridge.model_name,
                    slave_bridge.serial_number,
                )
            except HuaweiSolarException as err:
                _LOGGER.error("Could not connect to slave %s", slave_id)
                raise SlaveException(f"Could not connect to slave {slave_id}") from err

        # Return info that you want to store in the config entry.
        return result

    finally:
        if bridge is not None:
            # Cleanup this inverter object explicitly to prevent it from trying to maintain a modbus connection
            await bridge.stop()


async def validate_network_setup_login(
    host: str, port: int, slave_id: int, login_data: dict[str, Any]
) -> bool:
    """Verify the installer username/password and test if it can perform a write-operation."""
    bridge = None
    try:
        # these parameters have already been tested in validate_input, so they should work fine!
        bridge = await HuaweiSolarBridge.create(
            host=host,
            port=port,
            slave_id=slave_id,
        )

        await bridge.login(login_data[CONF_USERNAME], login_data[CONF_PASSWORD])

        # verify that we have write-permission now

        return await bridge.has_write_permission()

    finally:
        if bridge is not None:
            # Cleanup this inverter object explicitly to prevent it from trying to maintain a modbus connection
            await bridge.stop()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Huawei Solar."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow."""

        self._host: str | None = None
        self._port: int | None = None
        self._slave_ids: list[int] | None = None
        self._enable_parameter_configuration = False

        self._inverter_info: dict | None = None

        self._username: str | None = None
        self._password: str | None = None

        # Only used in reauth flows:
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step when user initializes a integration."""
        if user_input is not None:
            user_selection = user_input[CONF_TYPE]
            if user_selection == "Serial":
                return await self.async_step_setup_serial()

            return await self.async_step_setup_network()

        list_of_types = ["Serial", "Network"]

        schema = vol.Schema({vol.Required(CONF_TYPE): vol.In(list_of_types)})
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_setup_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handles connection parameters when using ModbusRTU."""

        # Parameter configuration is always possible over serial connection
        self._enable_parameter_configuration = True

        errors = {}

        if user_input is not None:

            user_selection = user_input[CONF_PORT]
            if user_selection == CONF_MANUAL_PATH:
                self._slave_ids = user_input[CONF_SLAVE_IDS]
                return await self.async_step_setup_serial_manual_path()

            user_input[CONF_PORT] = await self.hass.async_add_executor_job(
                usb.get_serial_by_id, user_input[CONF_PORT]
            )

            try:
                user_input[CONF_SLAVE_IDS] = list(
                    map(int, user_input[CONF_SLAVE_IDS].split(","))
                )
            except ValueError:
                errors["base"] = "invalid_slave_ids"
            else:

                try:
                    info = await validate_serial_setup(user_input)

                except ConnectionException:
                    errors["base"] = "cannot_connect"
                except SlaveException:
                    errors["base"] = "slave_cannot_connect"
                except ReadException:
                    errors["base"] = "read_error"
                except Exception as exception:  # pylint: disable=broad-except
                    _LOGGER.exception(exception)
                    errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id(info["serial_number"])
                    self._abort_if_unique_id_configured(
                        updates={
                            CONF_HOST: None,
                            CONF_PORT: user_input[CONF_PORT],
                            CONF_SLAVE_IDS: user_input[CONF_SLAVE_IDS],
                        }
                    )

                    self._port = user_input[CONF_PORT]
                    self._slave_ids = user_input[CONF_SLAVE_IDS]

                    self._inverter_info = info
                    self.context["title_placeholders"] = {"name": info["model_name"]}

                    # We can directly make the new entry
                    return await self._create_entry()

        ports = await self.hass.async_add_executor_job(serial.tools.list_ports.comports)
        list_of_ports = {
            port.device: usb.human_readable_device_name(
                port.device,
                port.serial_number,
                port.manufacturer,
                port.description,
                port.vid,
                port.pid,
            )
            for port in ports
        }

        list_of_ports[CONF_MANUAL_PATH] = CONF_MANUAL_PATH

        schema = vol.Schema(
            {
                vol.Required(CONF_PORT): vol.In(list_of_ports),
                vol.Required(CONF_SLAVE_IDS, default=str(DEFAULT_SERIAL_SLAVE_ID)): str,
            }
        )
        return self.async_show_form(
            step_id="setup_serial",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_setup_serial_manual_path(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select path manually."""
        errors = {}

        if user_input is not None:

            try:
                user_input[CONF_SLAVE_IDS] = list(
                    map(int, user_input[CONF_SLAVE_IDS].split(","))
                )
            except ValueError:
                errors["base"] = "invalid_slave_ids"
            else:
                try:
                    info = await validate_serial_setup(user_input)

                except ConnectionException:
                    errors["base"] = "cannot_connect"
                except SlaveException:
                    errors["base"] = "slave_cannot_connect"
                except ReadException:
                    errors["base"] = "read_error"
                except Exception as exception:  # pylint: disable=broad-except
                    _LOGGER.exception(exception)
                    errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id(info["serial_number"])
                    self._abort_if_unique_id_configured(
                        updates={
                            CONF_HOST: None,
                            CONF_PORT: user_input[CONF_PORT],
                            CONF_SLAVE_IDS: user_input[CONF_SLAVE_IDS],
                        }
                    )

                    self._port = user_input[CONF_PORT]
                    self._slave_ids = user_input[CONF_SLAVE_IDS]

                    self._inverter_info = info
                    self.context["title_placeholders"] = {"name": info["model_name"]}

                    # We can directly make the new entry
                    return await self._create_entry()

        schema = vol.Schema(
            {
                vol.Required(CONF_PORT): str,
                vol.Required(CONF_SLAVE_IDS, default=self._slave_ids): str,
            }
        )
        return self.async_show_form(
            step_id="setup_serial_manual_path", data_schema=schema, errors=errors
        )

    async def async_step_setup_network(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handles connection parameters when using ModbusTCP."""

        errors = {}

        if user_input is not None:
            try:
                user_input[CONF_SLAVE_IDS] = list(
                    map(int, user_input[CONF_SLAVE_IDS].split(","))
                )
            except ValueError:
                errors["base"] = "invalid_slave_ids"
            else:

                try:
                    info = await validate_network_setup(user_input)

                except ConnectionException:
                    errors["base"] = "cannot_connect"
                except SlaveException:
                    errors["base"] = "slave_cannot_connect"
                except ReadException as exception:
                    _LOGGER.exception(exception)
                    errors["base"] = "read_error"
                except Exception as exception:  # pylint: disable=broad-except
                    _LOGGER.exception(exception)
                    errors["base"] = "unknown"
                else:
                    await self.async_set_unique_id(info["serial_number"])
                    self._abort_if_unique_id_configured()

                    self._host = user_input[CONF_HOST]
                    self._port = user_input[CONF_PORT]
                    self._slave_ids = user_input[CONF_SLAVE_IDS]
                    self._enable_parameter_configuration = user_input[
                        CONF_ENABLE_PARAMETER_CONFIGURATION
                    ]

                    self._inverter_info = info
                    self.context["title_placeholders"] = {"name": info["model_name"]}

                    # Check if we need to ask for the login details
                    if (
                        self._enable_parameter_configuration
                        # This can also be None, in which case login is not supported.
                        and info["has_write_permission"] is not None
                        and info["has_write_permission"] is False
                    ):
                        return await self.async_step_network_login()

                    # Otherwise, we can directly create the device entry!
                    return await self._create_entry()

        return self.async_show_form(
            step_id="setup_network",
            data_schema=STEP_SETUP_NETWORK_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_network_login(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle username/password input."""
        assert self._host is not None
        assert self._port is not None
        assert self._slave_ids is not None

        errors = {}

        if user_input is not None:
            try:
                login_success = await validate_network_setup_login(
                    self._host, self._port, self._slave_ids[0], user_input
                )
                if login_success:
                    self._username = user_input[CONF_USERNAME]
                    self._password = user_input[CONF_PASSWORD]

                    return await self._create_entry()

                errors["base"] = "invalid_auth"

            except ConnectionException:
                errors["base"] = "cannot_connect"
            except SlaveException:
                errors["base"] = "slave_cannot_connect"
            except ReadException as exception:
                _LOGGER.exception(exception)
                errors["base"] = "read_error"
            except Exception as exception:  # pylint: disable=broad-except
                _LOGGER.exception(exception)
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="network_login", data_schema=STEP_LOGIN_DATA_SCHEMA, errors=errors
        )

    async def _create_entry(self):
        """Create the entry."""
        assert self._port is not None
        assert self._slave_ids is not None

        data = {
            CONF_HOST: self._host,
            CONF_PORT: self._port,
            CONF_SLAVE_IDS: self._slave_ids,
            CONF_ENABLE_PARAMETER_CONFIGURATION: self._enable_parameter_configuration,
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
        }

        if self._reauth_entry:
            self.hass.config_entries.async_update_entry(self._reauth_entry, data=data)
            await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        return self.async_create_entry(
            title=self._inverter_info["model_name"], data=data
        )

    async def async_step_reauth(
        self, config: dict[str, Any] | None = None
    ) -> FlowResult:
        """Perform reauth upon an login error."""
        assert config is not None

        self._host = config.get(CONF_HOST)
        self._port = config.get(CONF_PORT)
        self._slave_ids = config.get(CONF_SLAVE_IDS)
        self._enable_parameter_configuration = config.get(
            CONF_ENABLE_PARAMETER_CONFIGURATION, False
        )

        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_network_login()


class SlaveException(Exception):
    """Error while testing communication with a slave."""
