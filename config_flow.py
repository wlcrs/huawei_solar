"""Config flow for Huawei Solar integration."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from huawei_solar import (
    ConnectionException,
    HuaweiSolarException,
    InvalidCredentials,
    ReadException,
    create_device_instance,
    create_rtu_client,
    create_sub_device_instance,
    create_tcp_client,
    get_device_infos,
)
from huawei_solar.device.base import HuaweiSolarDeviceWithLogin
import serial.tools.list_ports
from tmodbus.exceptions import ModbusConnectionError
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import usb
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_TYPE,
    CONF_USERNAME,
)
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_ENABLE_PARAMETER_CONFIGURATION,
    CONF_SLAVE_IDS,
    DEFAULT_PORT,
    DEFAULT_SERIAL_SLAVE_ID,
    DEFAULT_USERNAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CONF_MANUAL_PATH = "Enter Manually"


async def validate_serial_setup(port: str, unit_ids: list[int]) -> dict[str, Any]:
    """Validate the serial device that was passed by the user."""
    client = create_rtu_client(
        port=port,
        unit_id=unit_ids[0],
    )
    try:
        await client.connect()
        device = await create_device_instance(client)

        _LOGGER.info(
            "Successfully connected to device %s %s with SN %s",
            type(device).__name__,
            device.model_name,
            device.serial_number,
        )

        result = {
            "model_name": device.model_name,
            "serial_number": device.serial_number,
        }

        # Also validate the other slave-ids
        for slave_id in unit_ids[1:]:
            try:
                slave_bridge = await create_sub_device_instance(device, slave_id)

                _LOGGER.info(
                    "Successfully connected to sub device %s with ID %s: %s with SN %s",
                    type(slave_bridge).__name__,
                    slave_id,
                    slave_bridge.model_name,
                    slave_bridge.serial_number,
                )
            except HuaweiSolarException as err:
                _LOGGER.error("Could not connect to slave %s", slave_id)
                raise DeviceException(f"Could not connect to slave {slave_id}") from err

        # Return info that you want to store in the config entry.
        return result
    finally:
        # Cleanup this device object explicitly to prevent it from trying to maintain a modbus connection
        with contextlib.suppress(Exception):
            await client.disconnect()


async def validate_network_setup_auto_slave_discovery(
    *,
    host: str,
    port: int,
    elevated_permissions: bool,
) -> dict[str, Any]:
    """Validate that we can connect to the device via the provided host and port. Try to autodiscover the slave ids."""

    client = create_tcp_client(
        host=host,
        port=port,
        unit_id=0,
    )
    try:
        await client.connect()
        device_infos = await get_device_infos(client)
        _LOGGER.info("Received %d device infos", len(device_infos))

        if not device_infos:
            raise DeviceException("No devices found")

        if not device_infos[0].device_id:
            raise DeviceException("Primary device has no device_id")

        # we assume the first device is the primary device
        device = await create_device_instance(
            client.for_unit_id(device_infos[0].device_id)
        )

        _LOGGER.info(
            "Successfully connected to device %s %s with SN %s",
            type(device).__name__,
            device.model_name,
            device.serial_number,
        )

        # Check if we have write access. If this is not the case, we will
        # need to login (and request the username/password from the user to be
        # able to do this).

        has_write_permission = elevated_permissions and (
            not isinstance(device, HuaweiSolarDeviceWithLogin)
            or await device.has_write_permission()
        )

        unit_ids = []
        for device_info in device_infos:
            if device_info.device_id is None:
                _LOGGER.warning(
                    "Device with no device_id found. Skipping. Product type: %s, model: %s, software version: %s",
                    device_info.product_type,
                    device_info.model,
                    device_info.software_version,
                )
                continue

            _LOGGER.info(
                "Device %s was auto-discovered of type %s with model %s and software version %s",
                device_info.device_id,
                device_info.product_type,
                device_info.model,
                device_info.software_version,
            )
            try:
                device = await create_device_instance(
                    client.for_unit_id(device_info.device_id)
                )

                _LOGGER.info(
                    "Successfully connected to sub_device %s %s: %s with SN %s",
                    type(device).__name__,
                    device_info.device_id,
                    device.model_name,
                    device.serial_number,
                )

                unit_ids.append(device_info.device_id)

            except HuaweiSolarException:
                _LOGGER.exception(
                    "Device with ID %s did not respond. Skipping", device_info.device_id
                )

        # Return info that you want to store in the config entry.
        return {
            "slave_ids": unit_ids,
            "model_name": device.model_name,
            "serial_number": device.serial_number,
            "has_write_permission": has_write_permission,
        }
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()


async def validate_network_setup(
    *,
    host: str,
    port: int,
    unit_ids: list[int],
    elevated_permissions: bool,
) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_SETUP_NETWORK_DATA_SCHEMA with values provided by the user.
    """
    client = create_tcp_client(
        host=host,
        port=port,
        unit_id=unit_ids[0],
    )
    try:
        await client.connect()
        device = await create_device_instance(client)

        _LOGGER.info(
            "Successfully connected to device %s %s with SN %s",
            (type(device).__name__),
            device.model_name,
            device.serial_number,
        )

        # Check if we have write access. If this is not the case, we will
        # need to login (and request the username/password from the user to be
        # able to do this).
        has_write_permission = elevated_permissions and (
            not isinstance(device, HuaweiSolarDeviceWithLogin)
            or await device.has_write_permission()
        )
        # Also validate the other slave-ids
        for unit_id in unit_ids[1:]:
            try:
                sub_device = await create_sub_device_instance(device, unit_id)

                _LOGGER.info(
                    "Successfully connected to sub device %s %s: %s with SN %s",
                    type(sub_device).__name__,
                    unit_id,
                    sub_device.model_name,
                    sub_device.serial_number,
                )
            except HuaweiSolarException as err:
                _LOGGER.error("Could not connect to sub device %s", unit_id)
                raise DeviceException(
                    f"Could not connect to sub device {unit_id}"
                ) from err

        return {
            "model_name": device.model_name,
            "serial_number": device.serial_number,
            "has_write_permission": has_write_permission,
        }
    finally:
        # Cleanup this inverter object explicitly to prevent it from trying to maintain a modbus connection
        with contextlib.suppress(Exception):
            await client.disconnect()


async def validate_network_setup_login(
    *,
    host: str,
    port: int,
    unit_id: int,
    username: str,
    password: str,
) -> bool:
    """Verify the installer username/password and test if it can perform a write-operation."""
    client = create_tcp_client(
        host=host,
        port=port,
        unit_id=unit_id,
    )
    try:
        # these parameters have already been tested in validate_input, so this should work fine!
        await client.connect()
        bridge = await create_device_instance(client)

        assert isinstance(bridge, HuaweiSolarDeviceWithLogin)

        await bridge.login(username, password)

        # verify that we have write-permission now

        return await bridge.has_write_permission()
    except InvalidCredentials:
        return False
    finally:
        if bridge is not None:
            # Cleanup this inverter object explicitly to prevent it from trying to maintain a modbus connection
            await bridge.stop()


def parse_unit_ids(unit_ids: str) -> list[int]:
    """Parse unit ids string into list of ints."""
    try:
        return list(map(int, unit_ids.split(",")))
    except ValueError as err:
        raise UnitIdsParseException from err


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Huawei Solar."""

    # Values entered by user in config flow
    _host: str | None = None
    _port: int | None = None

    _serial_port: str | None = None
    _slave_ids: list[int] | None = None

    _username: str | None = None
    _password: str | None = None

    _elevated_permissions = False

    # Only used in reauth flows:
    _reauth_entry: config_entries.ConfigEntry | None = None
    # Only used in reconfigure flows:
    _reconfigure_entry: config_entries.ConfigEntry | None = None

    # Only used for async_step_network_login
    _inverter_info: dict[str, Any] | None = None

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step when user initializes a integration."""
        return await self.async_step_setup_connection_type()

    def _update_config_data_from_entry_data(self, entry_data: dict[str, Any]) -> None:
        self._host = entry_data.get(CONF_HOST)
        if self._host is None:
            self._serial_port = entry_data.get(CONF_PORT)
        else:
            self._port = entry_data.get(CONF_PORT)

        slave_ids = entry_data.get(CONF_SLAVE_IDS)
        if not isinstance(slave_ids, list):
            assert isinstance(slave_ids, int)
            slave_ids = [slave_ids]
        self._slave_ids = slave_ids

        self._username = entry_data.get(CONF_USERNAME)
        self._password = entry_data.get(CONF_PASSWORD)

        self._elevated_permissions = entry_data.get(
            CONF_ENABLE_PARAMETER_CONFIGURATION, False
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step when user reconfigures the integration."""
        assert "entry_id" in self.context
        self._reconfigure_entry = self.hass.config_entries.async_get_known_entry(
            self.context["entry_id"]
        )
        self._update_config_data_from_entry_data(self._reconfigure_entry.data)  # type: ignore[arg-type]
        await self.hass.config_entries.async_unload(self.context["entry_id"])
        return await self.async_step_setup_connection_type()

    async def async_step_reauth(
        self, config: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Perform reauth upon an login error."""
        assert config is not None
        assert "entry_id" in self.context
        self._reauth_entry = self.hass.config_entries.async_get_known_entry(
            self.context["entry_id"]
        )
        self._update_config_data_from_entry_data(config)
        return await self.async_step_network_login()

    async def async_step_setup_connection_type(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step to let the user choose the connection type."""
        if user_input is not None:
            user_selection = user_input[CONF_TYPE]
            if user_selection == "Serial":
                return await self.async_step_setup_serial()

            return await self.async_step_setup_network()

        list_of_types = ["Serial", "Network"]

        # In case of a reconfigure flow, we already know the current choice.
        current_conn_type = None
        if self._host:
            current_conn_type = "Network"
        elif self._port:
            current_conn_type = "Serial"
        schema = vol.Schema(
            {vol.Required(CONF_TYPE, default=current_conn_type): vol.In(list_of_types)}
        )
        return self.async_show_form(step_id="setup_connection_type", data_schema=schema)

    async def async_step_setup_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle connection parameters when using ModbusRTU."""
        # You always have elevated permissions when connecting over serial
        self._elevated_permissions = True

        errors = {}

        if user_input is not None:
            self._host = None
            try:
                self._slave_ids = parse_unit_ids(user_input[CONF_SLAVE_IDS])
            except UnitIdsParseException:
                errors["base"] = "invalid_slave_ids"
            else:
                if user_input[CONF_PORT] == CONF_MANUAL_PATH:
                    return await self.async_step_setup_serial_manual_path()

                self._serial_port = await self.hass.async_add_executor_job(
                    usb.get_serial_by_id, user_input[CONF_PORT]
                )

                try:
                    assert isinstance(self._serial_port, str)
                    info = await validate_serial_setup(
                        self._serial_port, self._slave_ids
                    )

                except (ConnectionException, ModbusConnectionError):
                    errors["base"] = "cannot_connect"
                except DeviceException:
                    errors["base"] = "slave_cannot_connect"
                except ReadException:
                    errors["base"] = "read_error"
                except Exception:  # allowed in config flow
                    _LOGGER.exception(
                        "Unexpected exception while connecting over serial"
                    )
                    errors["base"] = "unknown"
                else:
                    return await self._create_or_update_entry(info)

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
                vol.Required(CONF_PORT, default=self._port): vol.In(list_of_ports),
                vol.Required(
                    CONF_SLAVE_IDS,
                    default=",".join(map(str, self._slave_ids))
                    if self._slave_ids
                    else str(DEFAULT_SERIAL_SLAVE_ID),
                ): str,
            }
        )
        return self.async_show_form(
            step_id="setup_serial",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_setup_serial_manual_path(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select path manually."""
        errors = {}

        if user_input is not None:
            self._serial_port = user_input[CONF_PORT]
            assert isinstance(self._serial_port, str)

            try:
                self._slave_ids = list(map(int, user_input[CONF_SLAVE_IDS].split(",")))
                info = await validate_serial_setup(self._serial_port, self._slave_ids)
            except UnitIdsParseException:
                errors["base"] = "invalid_slave_ids"
            except (ConnectionException, ModbusConnectionError):
                errors["base"] = "cannot_connect"
            except DeviceException:
                errors["base"] = "slave_cannot_connect"
            except ReadException:
                errors["base"] = "read_error"
            except Exception:  # allowed in config flow
                _LOGGER.exception("Unexpected exception while connecting over serial")
                errors["base"] = "unknown"
            else:
                return await self._create_or_update_entry(info)

        schema = vol.Schema(
            {
                vol.Required(CONF_PORT, default=self._port): str,
                vol.Required(
                    CONF_SLAVE_IDS,
                    default=",".join(map(str, self._slave_ids))
                    if self._slave_ids
                    else str(DEFAULT_SERIAL_SLAVE_ID),
                ): str,
            }
        )
        return self.async_show_form(
            step_id="setup_serial_manual_path", data_schema=schema, errors=errors
        )

    async def async_step_setup_network(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle connection parameters when using ModbusTCP."""
        errors = {}

        if user_input is not None:
            self._host = user_input[CONF_HOST]
            assert self._host is not None
            self._port = user_input[CONF_PORT]
            assert self._port is not None
            self._elevated_permissions = user_input[CONF_ENABLE_PARAMETER_CONFIGURATION]

            info = None
            if user_input[CONF_SLAVE_IDS].lower() == "auto":
                try:
                    info = await validate_network_setup_auto_slave_discovery(
                        host=self._host,
                        port=self._port,
                        elevated_permissions=self._elevated_permissions,
                    )
                    self._slave_ids = info.pop("slave_ids")

                except (ConnectionException, ModbusConnectionError):
                    errors["base"] = "cannot_connect"
                except DeviceException:
                    errors["base"] = "slave_cannot_connect"
                except ReadException:
                    _LOGGER.exception("Read exception while connecting via TCP")
                    errors["base"] = "read_error"
                except Exception:  # allowed in config flow
                    _LOGGER.exception("Unexpected exception while connecting via TCP")
                    errors["base"] = "unknown"
            else:
                try:
                    self._slave_ids = list(
                        map(int, user_input[CONF_SLAVE_IDS].split(","))
                    )
                except ValueError:
                    errors["base"] = "invalid_slave_ids"
                else:
                    try:
                        info = await validate_network_setup(
                            host=self._host,
                            port=self._port,
                            unit_ids=self._slave_ids,
                            elevated_permissions=self._elevated_permissions,
                        )

                    except (ConnectionException, ModbusConnectionError):
                        errors["base"] = "cannot_connect"
                    except DeviceException:
                        errors["base"] = "slave_cannot_connect"
                    except ReadException:
                        _LOGGER.exception("Read exception while connecting via TCP")
                        errors["base"] = "read_error"
                    except Exception:  # allowed in config flow
                        _LOGGER.exception(
                            "Unexpected exception while connecting via TCP"
                        )
                        errors["base"] = "unknown"

            # info will be set when we successfully connected to the inverter
            if info:
                # Check if we need to ask for the login details
                if self._elevated_permissions and info["has_write_permission"] is False:
                    self.context["title_placeholders"] = {"name": info["model_name"]}
                    self._inverter_info = info
                    return await self.async_step_network_login()

                # In case of a reconfigure, the user can have unchecked the elevated permissions checkbox
                self._username = None
                self._password = None

                # Otherwise, we can directly create the device entry!
                return await self._create_or_update_entry(info)

        return self.async_show_form(
            step_id="setup_network",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=self._host): str,
                    vol.Required(
                        CONF_PORT, default=self._port or DEFAULT_PORT
                    ): cv.port,
                    vol.Required(
                        CONF_SLAVE_IDS,
                        default=",".join(map(str, self._slave_ids))
                        if self._slave_ids
                        else "AUTO",
                    ): str,
                    vol.Required(
                        CONF_ENABLE_PARAMETER_CONFIGURATION,
                        default=self._elevated_permissions,
                    ): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_network_login(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle username/password input."""
        assert self._host is not None
        assert self._port is not None
        assert self._slave_ids is not None
        assert self._inverter_info is not None

        errors = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]

            assert self._username is not None
            assert self._password is not None

            try:
                login_success = await validate_network_setup_login(
                    host=self._host,
                    port=self._port,
                    unit_id=self._slave_ids[0],
                    username=self._username,
                    password=self._password,
                )
                if login_success:
                    return await self._create_or_update_entry(self._inverter_info)

                errors["base"] = "invalid_auth"
            except (ConnectionException, ModbusConnectionError):
                errors["base"] = "cannot_connect"
            except DeviceException:
                errors["base"] = "slave_cannot_connect"
            except ReadException:
                _LOGGER.exception(
                    "Could not read from device while validating login parameter"
                )
                errors["base"] = "read_error"
            except Exception:  # allowed in config flow
                _LOGGER.exception(
                    "Unexpected exception while validating login parameters"
                )
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="network_login",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME, default=self._username or DEFAULT_USERNAME
                    ): str,
                    vol.Required(CONF_PASSWORD, default=self._password): str,
                }
            ),
            errors=errors,
        )

    async def _create_or_update_entry(
        self, inverter_info: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """Create the entry, or update the existing one if present."""

        data = {
            CONF_HOST: self._host,
            CONF_PORT: self._serial_port
            if self._serial_port is not None
            else self._port,
            CONF_SLAVE_IDS: self._slave_ids,
            CONF_ENABLE_PARAMETER_CONFIGURATION: self._elevated_permissions,
            CONF_USERNAME: self._username,
            CONF_PASSWORD: self._password,
        }

        if self._reauth_entry:
            self.hass.config_entries.async_update_entry(self._reauth_entry, data=data)
            await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
            return self.async_abort(reason="reauth_successful")

        assert inverter_info
        self.context["title_placeholders"] = {"name": inverter_info["model_name"]}
        if self._reconfigure_entry:
            self.hass.config_entries.async_update_entry(
                self._reconfigure_entry, data=data
            )
            await self.hass.config_entries.async_reload(
                self._reconfigure_entry.entry_id
            )
            return self.async_abort(reason="reconfigure_successful")

        await self.async_set_unique_id(inverter_info["serial_number"])
        self._abort_if_unique_id_configured(updates=data)

        return self.async_create_entry(title=inverter_info["model_name"], data=data)


class UnitIdsParseException(Exception):
    """Error while parsing the unit id's."""


class DeviceException(Exception):
    """Error while testing communication with a device."""
