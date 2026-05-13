"""Config flow for Huawei Solar integration."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from collections.abc import Callable
from typing import Any

from huawei_solar import (
    ConnectionException,
    ConnectionInterruptedException,
    HuaweiSolarException,
    InvalidCredentials,
    ReadException,
    create_device_instance,
    create_rtu_client,
    create_sub_device_instance,
    create_tcp_client,
    get_device_infos,
)
from huawei_solar.modbus_client import create_scan_rtu_client, create_scan_tcp_client
from huawei_solar.device import detect_device_type
from huawei_solar.device.base import HuaweiSolarDeviceWithLogin
from huawei_solar.exceptions import DeviceDetectionError
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
    CONF_SCAN_INTERVAL,
    CONF_TYPE,
    CONF_USERNAME,
)
from homeassistant.core import callback
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


async def _auto_slave_discovery(
    client: Any,
    *,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[int, list[int]] | None:
    """Probe unit_ids 0-16 and 100 sequentially via Huawei get_device_infos messages.

    Returns (primary_unit_id, sub_unit_ids) if a device responds, or None if not.
    The caller owns ``client`` and is responsible for connecting/disconnecting it.
    """
    unit_ids_to_scan = [0, 100, *list(range(1, 17))]

    async def _probe(unit_id: int):
        _LOGGER.debug("AUTO: probing unit_id %s via get_device_infos", unit_id)
        try:
            device_infos = await get_device_infos(client.for_unit_id(unit_id))
        except (HuaweiSolarException, ReadException, TimeoutError) as err:
            _LOGGER.debug("AUTO: unit_id %s did not respond: %s", unit_id, err)
            raise
        if not device_infos or device_infos[0].device_id is None:
            _LOGGER.debug("AUTO: unit_id %s returned no valid device info", unit_id)
            raise DeviceException(f"No valid device at unit_id {unit_id}")
        _LOGGER.debug(
            "AUTO: unit_id %s responded: type=%s, model=%s, software_version=%s",
            unit_id,
            device_infos[0].product_type,
            device_infos[0].model,
            device_infos[0].software_version,
        )
        return unit_id, device_infos

    _LOGGER.debug("AUTO: scanning unit_ids %s sequentially", unit_ids_to_scan)
    for i, unit_id in enumerate(unit_ids_to_scan):
        try:
            primary_unit_id, found_device_infos = await _probe(unit_id)
            _LOGGER.info(
                "AUTO: found device at unit_id %s: type=%s, model=%s, software_version=%s",
                primary_unit_id,
                found_device_infos[0].product_type,
                found_device_infos[0].model,
                found_device_infos[0].software_version,
            )
            sub_unit_ids = [
                di.device_id
                for di in found_device_infos[1:]
                if di.device_id is not None
            ]
            for di in found_device_infos[1:]:
                if di.device_id is None:
                    _LOGGER.warning(
                        "AUTO: device with no device_id found. Skipping. "
                        "Product type: %s, model: %s, software version: %s",
                        di.product_type,
                        di.model,
                        di.software_version,
                    )
            if on_progress:
                on_progress(1.0)
        except (
            HuaweiSolarException,
            ReadException,
            DeviceException,
            TimeoutError,
        ):
            pass
        else:
            return primary_unit_id, sub_unit_ids
        if on_progress:
            on_progress((i + 1) / len(unit_ids_to_scan))

    return None


async def _tcp_auto_slave_discovery(
    *,
    host: str,
    port: int,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[int, list[int]] | None:
    """Auto-discovery over TCP. Opens/closes its own connection."""
    client = create_scan_tcp_client(host=host, port=port, unit_id=0)
    try:
        await client.connect()
        return await _auto_slave_discovery(client, on_progress=on_progress)
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()


async def _rtu_auto_slave_discovery(
    *,
    serial_port: str,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[int, list[int]] | None:
    """Auto-discovery over RTU (serial). Opens/closes its own connection."""
    client = create_scan_rtu_client(serial_port, unit_id=0)
    try:
        await client.connect()
        return await _auto_slave_discovery(client, on_progress=on_progress)
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()


async def _scan_slave_discovery(
    client: Any,
    *,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[int, list[int]]:
    """Probe unit_ids 0-16 and 100 sequentially via detect_device_type.

    Returns (primary_unit_id, sub_unit_ids) for all responding devices.
    Raises DeviceException if no device is found.
    The caller owns ``client`` and is responsible for connecting/disconnecting it.
    Does not use Huawei device-discovery Modbus messages, making it compatible
    with modbus proxies.
    """
    unit_ids_to_scan = [0, 100, *list(range(1, 17))]

    async def _probe(unit_id: int) -> tuple[int, str] | None:
        _LOGGER.debug("SCAN: probing unit_id %s via detect_device_type", unit_id)
        try:
            _, model_name = await detect_device_type(client.for_unit_id(unit_id))
            _LOGGER.debug(
                "SCAN: unit_id %s identified as model=%s", unit_id, model_name
            )
            return unit_id, model_name
        except (
            HuaweiSolarException,
            ReadException,
            DeviceDetectionError,
            TimeoutError,
        ) as err:
            _LOGGER.debug("SCAN: unit_id %s did not respond: %s", unit_id, err)
            return None

    found: list[tuple[int, str]] = []
    _LOGGER.debug("SCAN: scanning unit_ids %s sequentially", unit_ids_to_scan)
    for i, unit_id in enumerate(unit_ids_to_scan):
        result = await _probe(unit_id)
        if result is not None:
            found.append(result)
        if on_progress:
            on_progress((i + 1) / len(unit_ids_to_scan))

    if not found:
        _LOGGER.warning(
            "SCAN: no devices found on any of unit_ids %s", unit_ids_to_scan
        )
        raise DeviceException("No devices found")

    _LOGGER.info("SCAN: found %d device(s)", len(found))
    for unit_id, model_name in found:
        _LOGGER.info("SCAN: unit_id %s: model=%s", unit_id, model_name)

    return found[0][0], [uid for uid, _ in found[1:]]


async def _tcp_scan_slave_discovery(
    *,
    host: str,
    port: int,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[int, list[int]]:
    """Scan-discovery over TCP. Opens/closes its own connection."""
    client = create_scan_tcp_client(host=host, port=port, unit_id=0)
    try:
        await client.connect()
        return await _scan_slave_discovery(client, on_progress=on_progress)
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()


async def _rtu_scan_slave_discovery(
    *,
    serial_port: str,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[int, list[int]]:
    """Scan-discovery over RTU (serial). Opens/closes its own connection."""
    client = create_scan_rtu_client(serial_port, unit_id=0)
    try:
        await client.connect()
        return await _scan_slave_discovery(client, on_progress=on_progress)
    finally:
        with contextlib.suppress(Exception):
            await client.disconnect()


async def _connect_to_discovered_devices(
    *,
    host: str,
    port: int,
    primary_unit_id: int,
    sub_unit_ids: list[int],
    elevated_permissions: bool,
) -> dict[str, Any]:
    """Connect to the primary device and verify all sub-devices.

    Returns a dict with slave_ids, model_name, serial_number and has_write_permission.
    """
    client = create_tcp_client(host=host, port=port, unit_id=primary_unit_id)
    try:
        await client.connect()
        device = await create_device_instance(client)

        _LOGGER.info(
            "Successfully connected to primary device with unit_id %s: %s %s with SN %s",
            primary_unit_id,
            type(device).__name__,
            device.model_name,
            device.serial_number,
        )

        has_write_permission = elevated_permissions and (
            not isinstance(device, HuaweiSolarDeviceWithLogin)
            or await device.has_write_permission()
        )

        unit_ids = [primary_unit_id]
        for sub_unit_id in sub_unit_ids:
            try:
                sub_device = await create_sub_device_instance(device, sub_unit_id)
                _LOGGER.info(
                    "Successfully connected to sub device with unit_id %s. %s: %s with SN %s",
                    sub_unit_id,
                    type(sub_device).__name__,
                    sub_device.model_name,
                    sub_device.serial_number,
                )
                unit_ids.append(sub_unit_id)
            except HuaweiSolarException:
                _LOGGER.exception(
                    "Error while connecting to sub device with unit_id %s. Skipping",
                    sub_unit_id,
                )

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
    Raises:
        ConnectionException / ModbusConnectionError: if the TCP connection cannot be established.
        DeviceException: if the TCP connection was established but the device rejected the
            slave ID (connection closed by remote), or a sub-device could not be reached.
    """
    client = create_scan_tcp_client(
        host=host,
        port=port,
        unit_id=unit_ids[0],
    )
    # Separate the TCP connect from the device communication so callers can
    # distinguish "host unreachable" from "wrong slave ID".
    await client.connect()

    try:
        try:
            device = await create_device_instance(client)
        except (ConnectionException, ModbusConnectionError, TimeoutError) as err:
            # TCP connected but device closed the connection → wrong slave ID.
            raise DeviceException(
                f"Device closed connection for unit_id {unit_ids[0]} - possibly wrong slave ID",
                unit_id=unit_ids[0],
            ) from err

        _LOGGER.info(
            "Successfully connected to device %s %s with SN %s",
            type(device).__name__,
            device.model_name,
            device.serial_number,
        )

        has_write_permission = elevated_permissions and (
            not isinstance(device, HuaweiSolarDeviceWithLogin)
            or await device.has_write_permission()
        )

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
            except (
                HuaweiSolarException,
                ConnectionException,
                ModbusConnectionError,
                TimeoutError,
            ) as err:
                _LOGGER.error("Could not connect to sub device %s", unit_id)
                raise DeviceException(
                    f"Could not connect to sub device {unit_id}",
                    unit_id=unit_id,
                ) from err

        return {
            "model_name": device.model_name,
            "serial_number": device.serial_number,
            "has_write_permission": has_write_permission,
        }
    finally:
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

    # Used across the auto/scan/finish discovery steps
    _discovery_task: asyncio.Task | None = None
    _discovered_primary_unit_id: int | None = None
    _discovered_sub_unit_ids: list[int] = []
    _failed_slave_id: int | None = None

    def _reset_discovery_state(self) -> None:
        """Clear all state used by the discovery progress steps."""
        self._discovery_task = None
        self._discovered_primary_unit_id = None
        self._discovered_sub_unit_ids = []
        self._failed_slave_id = None

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
            slave_ids_input = user_input[CONF_SLAVE_IDS].strip().upper()

            if user_input[CONF_PORT] == CONF_MANUAL_PATH:
                if slave_ids_input == "AUTO":
                    # Need the port first; go to manual path step which will
                    # then route to auto-discovery.
                    return await self.async_step_setup_serial_manual_path()
                try:
                    self._slave_ids = parse_unit_ids(user_input[CONF_SLAVE_IDS])
                except UnitIdsParseException:
                    errors["base"] = "invalid_slave_ids"
                else:
                    return await self.async_step_setup_serial_manual_path()
            elif slave_ids_input == "AUTO":
                self._serial_port = await self.hass.async_add_executor_job(
                    usb.get_serial_by_id, user_input[CONF_PORT]
                )
                return await self.async_step_serial_auto_discovery()
            else:
                try:
                    self._slave_ids = parse_unit_ids(user_input[CONF_SLAVE_IDS])
                except UnitIdsParseException:
                    errors["base"] = "invalid_slave_ids"
                else:
                    self._serial_port = await self.hass.async_add_executor_job(
                        usb.get_serial_by_id, user_input[CONF_PORT]
                    )
                    assert isinstance(self._serial_port, str)
                    try:
                        info = await validate_serial_setup(
                            self._serial_port, self._slave_ids
                        )
                    except ConnectionInterruptedException:
                        errors["base"] = "connection_interrupted"
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
                    else "AUTO",
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

            slave_ids_input = user_input[CONF_SLAVE_IDS].strip().upper()
            if slave_ids_input == "AUTO":
                return await self.async_step_serial_auto_discovery()

            try:
                self._slave_ids = parse_unit_ids(user_input[CONF_SLAVE_IDS])
            except UnitIdsParseException:
                errors["base"] = "invalid_slave_ids"
            else:
                try:
                    info = await validate_serial_setup(
                        self._serial_port, self._slave_ids
                    )
                except ConnectionInterruptedException:
                    errors["base"] = "connection_interrupted"
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

        schema = vol.Schema(
            {
                vol.Required(CONF_PORT, default=self._serial_port): str,
                vol.Required(
                    CONF_SLAVE_IDS,
                    default=",".join(map(str, self._slave_ids))
                    if self._slave_ids
                    else "AUTO",
                ): str,
            }
        )
        return self.async_show_form(
            step_id="setup_serial_manual_path", data_schema=schema, errors=errors
        )

    async def async_step_serial_auto_discovery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a progress screen while auto-discovering over serial."""
        assert self._serial_port is not None

        if self._discovery_task is None:
            if not Path(self._serial_port).is_char_device():
                _LOGGER.warning(
                    "AUTO/serial: %s is not a serial device", self._serial_port
                )
                return await self.async_step_cannot_connect_serial()

            self._discovery_task = self.hass.async_create_background_task(
                _rtu_auto_slave_discovery(
                    serial_port=self._serial_port,
                    on_progress=self.async_update_progress,
                ),
                "huawei_solar_serial_auto_discovery",
            )

        if not self._discovery_task.done():
            return self.async_show_progress(
                step_id="serial_auto_discovery",
                progress_action="serial_auto_discovery",
                progress_task=self._discovery_task,
                description_placeholders={"serial_port": self._serial_port},
            )

        task, self._discovery_task = self._discovery_task, None
        try:
            result = task.result()
        except ConnectionInterruptedException:
            _LOGGER.warning(
                "AUTO/serial: connection interrupted on %s", self._serial_port
            )
            return self.async_show_progress_done(
                next_step_id="connection_interrupted_serial"
            )
        except (ConnectionException, ModbusConnectionError, TimeoutError):
            _LOGGER.warning("AUTO/serial: could not open %s", self._serial_port)
            return self.async_show_progress_done(next_step_id="cannot_connect_serial")
        except Exception:
            _LOGGER.exception("Unexpected exception during serial auto discovery")
            return self.async_show_progress_done(next_step_id="cannot_connect_serial")

        if result is None:
            _LOGGER.warning(
                "AUTO/serial: no devices found on %s. Falling back to SCAN method",
                self._serial_port,
            )
            return self.async_show_progress_done(next_step_id="serial_scan_discovery")

        self._discovered_primary_unit_id, self._discovered_sub_unit_ids = result
        return self.async_show_progress_done(next_step_id="serial_finish_setup")

    async def async_step_serial_scan_discovery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a progress screen while scan-discovering over serial."""
        assert self._serial_port is not None

        if self._discovery_task is None:
            if not Path(self._serial_port).is_char_device():
                _LOGGER.warning(
                    "SCAN/serial: %s is not a serial device", self._serial_port
                )
                return await self.async_step_cannot_connect_serial()

            self._discovery_task = self.hass.async_create_background_task(
                _rtu_scan_slave_discovery(
                    serial_port=self._serial_port,
                    on_progress=self.async_update_progress,
                ),
                "huawei_solar_serial_scan_discovery",
            )

        if not self._discovery_task.done():
            return self.async_show_progress(
                step_id="serial_scan_discovery",
                progress_action="serial_scan_discovery",
                progress_task=self._discovery_task,
                description_placeholders={"serial_port": self._serial_port},
            )

        task, self._discovery_task = self._discovery_task, None
        try:
            result = task.result()
        except ConnectionInterruptedException:
            _LOGGER.warning(
                "SCAN/serial: connection interrupted on %s", self._serial_port
            )
            return self.async_show_progress_done(
                next_step_id="connection_interrupted_serial"
            )
        except (ConnectionException, ModbusConnectionError, TimeoutError):
            _LOGGER.warning("SCAN/serial: could not open %s", self._serial_port)
            return self.async_show_progress_done(next_step_id="cannot_connect_serial")
        except DeviceException:
            _LOGGER.warning("SCAN/serial: no devices found on %s", self._serial_port)
            return self.async_show_progress_done(next_step_id="no_device_found_serial")
        except Exception:
            _LOGGER.exception("Unexpected exception during serial scan discovery")
            return self.async_show_progress_done(next_step_id="cannot_connect_serial")

        self._discovered_primary_unit_id, self._discovered_sub_unit_ids = result
        return self.async_show_progress_done(next_step_id="serial_finish_setup")

    async def async_step_serial_finish_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a progress screen while connecting to the discovered serial devices."""
        assert self._serial_port is not None
        assert self._discovered_primary_unit_id is not None

        if self._discovery_task is None:
            unit_ids = [
                self._discovered_primary_unit_id,
                *self._discovered_sub_unit_ids,
            ]
            self._discovery_task = self.hass.async_create_background_task(
                validate_serial_setup(self._serial_port, unit_ids),
                "huawei_solar_serial_finish_setup",
            )

        if not self._discovery_task.done():
            return self.async_show_progress(
                step_id="serial_finish_setup",
                progress_action="serial_finish_setup",
                progress_task=self._discovery_task,
                description_placeholders={"serial_port": self._serial_port},
            )

        task, self._discovery_task = self._discovery_task, None
        try:
            info = task.result()
        except ConnectionInterruptedException:
            _LOGGER.warning(
                "Connection interrupted on %s", self._serial_port
            )
            return self.async_show_progress_done(
                next_step_id="connection_interrupted_serial"
            )
        except (ConnectionException, ModbusConnectionError, TimeoutError):
            _LOGGER.warning(
                "Could not connect to discovered serial device on %s", self._serial_port
            )
            return self.async_show_progress_done(next_step_id="cannot_connect_serial")
        except DeviceException:
            _LOGGER.exception(
                "Error while connecting to discovered serial device on %s",
                self._serial_port,
            )
            return self.async_show_progress_done(next_step_id="no_device_found_serial")
        except Exception:
            _LOGGER.exception(
                "Unexpected exception while connecting to discovered serial devices"
            )
            return self.async_show_progress_done(next_step_id="cannot_connect_serial")

        self._slave_ids = [
            self._discovered_primary_unit_id,
            *self._discovered_sub_unit_ids,
        ]
        self._inverter_info = info
        return self.async_show_progress_done(next_step_id="confirm_setup")

    async def async_step_cannot_connect_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Inform the user the serial port could not be opened, offer to retry."""
        if user_input is None:
            return self.async_show_form(
                step_id="cannot_connect_serial",
                description_placeholders={"serial_port": self._serial_port or ""},
            )
        self._reset_discovery_state()
        return await self.async_step_setup_serial()

    async def async_step_connection_interrupted_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Inform the user the connection was interrupted by another device, offer to retry."""
        if user_input is None:
            return self.async_show_form(
                step_id="connection_interrupted_serial",
                description_placeholders={"serial_port": self._serial_port or ""},
            )
        self._reset_discovery_state()
        return await self.async_step_setup_serial()

    async def async_step_no_device_found_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Inform the user no device responded on the serial port, offer to retry."""
        if user_input is None:
            placeholders: dict[str, str] = {
                "serial_port": self._serial_port or "",
                "slave_id": str(self._failed_slave_id)
                if self._failed_slave_id is not None
                else "unknown",
            }
            return self.async_show_form(
                step_id="no_device_found_serial",
                description_placeholders=placeholders,
            )
        self._reset_discovery_state()
        return await self.async_step_setup_serial()

    async def async_step_setup_network(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle connection parameters when using ModbusTCP."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._host = user_input[CONF_HOST]
            assert self._host is not None
            self._port = user_input[CONF_PORT]
            assert self._port is not None
            self._elevated_permissions = user_input[CONF_ENABLE_PARAMETER_CONFIGURATION]

            slave_ids_input = user_input[CONF_SLAVE_IDS].strip().upper()
            if slave_ids_input == "AUTO":
                return await self.async_step_auto_discovery()

            try:
                self._slave_ids = list(map(int, user_input[CONF_SLAVE_IDS].split(",")))
            except ValueError:
                errors["base"] = "invalid_slave_ids"
            else:
                return await self.async_step_manual_connect()

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

    async def async_step_manual_connect(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a progress screen while connecting to manually specified slave IDs."""
        assert self._host is not None
        assert self._port is not None
        assert self._slave_ids is not None

        if self._discovery_task is None:
            self._discovery_task = self.hass.async_create_background_task(
                validate_network_setup(
                    host=self._host,
                    port=self._port,
                    unit_ids=self._slave_ids,
                    elevated_permissions=self._elevated_permissions,
                ),
                "huawei_solar_manual_connect",
            )

        if not self._discovery_task.done():
            return self.async_show_progress(
                step_id="manual_connect",
                progress_action="manual_connect",
                progress_task=self._discovery_task,
                description_placeholders={
                    "host": self._host,
                    "port": str(self._port),
                    "slave_ids": ", ".join(str(s) for s in self._slave_ids),
                },
            )

        task, self._discovery_task = self._discovery_task, None
        try:
            info = task.result()
        except (ConnectionException, ModbusConnectionError, TimeoutError):
            _LOGGER.warning("Could not connect to %s:%s", self._host, self._port)
            return self.async_show_progress_done(next_step_id="cannot_connect")
        except DeviceException as err:
            _LOGGER.warning(
                "Could not connect to one of the slave devices on %s:%s",
                self._host,
                self._port,
            )
            self._failed_slave_id = err.unit_id
            return self.async_show_progress_done(next_step_id="no_device_found")
        except ConnectionInterruptedException:
            _LOGGER.warning(
                "Connection to %s:%s was interrupted during setup, "
                "probably due to another device connecting at the same time. "
                "The inverter only supports one Modbus connection at a time",
                self._host,
                self._port,
            )
            return self.async_show_progress_done(next_step_id="connection_interrupted")
        except (HuaweiSolarException, ReadException):
            _LOGGER.exception("Error while connecting to %s:%s", self._host, self._port)
            return self.async_show_progress_done(next_step_id="cannot_connect")
        except Exception:  # allowed in config flow
            _LOGGER.exception(
                "Unexpected exception while connecting to %s:%s", self._host, self._port
            )
            return self.async_show_progress_done(next_step_id="cannot_connect")

        self._inverter_info = info
        if self._elevated_permissions and info["has_write_permission"] is False:
            self.context["title_placeholders"] = {"name": info["model_name"]}
            return self.async_show_progress_done(next_step_id="network_login")

        self._username = None
        self._password = None
        return self.async_show_progress_done(next_step_id="confirm_setup")

    async def async_step_auto_discovery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a progress screen while probing via Huawei get_device_infos messages."""
        assert self._host is not None
        assert self._port is not None

        if self._discovery_task is None:
            self._discovery_task = self.hass.async_create_background_task(
                _tcp_auto_slave_discovery(
                    host=self._host,
                    port=self._port,
                    on_progress=self.async_update_progress,
                ),
                "huawei_solar_auto_discovery",
            )

        if not self._discovery_task.done():
            return self.async_show_progress(
                step_id="auto_discovery",
                progress_action="auto_discovery",
                progress_task=self._discovery_task,
                description_placeholders={
                    "host": self._host,
                    "port": str(self._port),
                },
            )

        task, self._discovery_task = self._discovery_task, None
        try:
            result = task.result()
        except ConnectionInterruptedException:
            _LOGGER.warning(
                "AUTO: connection interrupted on %s:%s", self._host, self._port
            )
            return self.async_show_progress_done(next_step_id="connection_interrupted")
        except (ConnectionException, ModbusConnectionError, TimeoutError):
            _LOGGER.warning("AUTO: could not connect to %s:%s", self._host, self._port)
            return self.async_show_progress_done(next_step_id="cannot_connect")
        except Exception:  # allowed in config flow
            _LOGGER.exception("Unexpected exception during auto discovery")
            return self.async_show_progress_done(next_step_id="cannot_connect")

        if result is None:
            _LOGGER.warning(
                "AUTO: no devices found via Huawei discovery messages. "
                "Falling back to SCAN method"
            )
            return self.async_show_progress_done(next_step_id="scan_discovery")

        self._discovered_primary_unit_id, self._discovered_sub_unit_ids = result
        return self.async_show_progress_done(next_step_id="finish_network_setup")

    async def async_step_scan_discovery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a progress screen while probing via detect_device_type."""
        assert self._host is not None
        assert self._port is not None

        if self._discovery_task is None:
            self._discovery_task = self.hass.async_create_background_task(
                _tcp_scan_slave_discovery(
                    host=self._host,
                    port=self._port,
                    on_progress=self.async_update_progress,
                ),
                "huawei_solar_scan_discovery",
            )

        if not self._discovery_task.done():
            return self.async_show_progress(
                step_id="scan_discovery",
                progress_action="scan_discovery",
                progress_task=self._discovery_task,
                description_placeholders={
                    "host": self._host,
                    "port": str(self._port),
                },
            )

        task, self._discovery_task = self._discovery_task, None
        try:
            result = task.result()
        except ConnectionInterruptedException:
            _LOGGER.warning(
                "SCAN: connection interrupted on %s:%s", self._host, self._port
            )
            return self.async_show_progress_done(next_step_id="connection_interrupted")
        except (ConnectionException, ModbusConnectionError, TimeoutError):
            _LOGGER.warning("SCAN: could not connect to %s:%s", self._host, self._port)
            return self.async_show_progress_done(next_step_id="cannot_connect")
        except DeviceException:
            _LOGGER.warning("SCAN: no devices found on %s:%s", self._host, self._port)
            return self.async_show_progress_done(next_step_id="no_device_found")
        except Exception:  # allowed in config flow
            _LOGGER.exception("Unexpected exception during scan discovery")
            return self.async_show_progress_done(next_step_id="cannot_connect")

        self._discovered_primary_unit_id, self._discovered_sub_unit_ids = result
        return self.async_show_progress_done(next_step_id="finish_network_setup")

    async def async_step_finish_network_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show a progress screen while connecting to the discovered devices."""
        assert self._host is not None
        assert self._port is not None
        assert self._discovered_primary_unit_id is not None

        if self._discovery_task is None:
            self._discovery_task = self.hass.async_create_background_task(
                _connect_to_discovered_devices(
                    host=self._host,
                    port=self._port,
                    primary_unit_id=self._discovered_primary_unit_id,
                    sub_unit_ids=self._discovered_sub_unit_ids,
                    elevated_permissions=self._elevated_permissions,
                ),
                "huawei_solar_finish_network_setup",
            )

        if not self._discovery_task.done():
            return self.async_show_progress(
                step_id="finish_network_setup",
                progress_action="finish_network_setup",
                progress_task=self._discovery_task,
                description_placeholders={
                    "host": self._host,
                    "port": str(self._port),
                },
            )

        task, self._discovery_task = self._discovery_task, None
        try:
            info = task.result()
        except (ConnectionException, ModbusConnectionError, TimeoutError):
            _LOGGER.warning(
                "Could not connect to discovered device at %s:%s unit_id %s",
                self._host,
                self._port,
                self._discovered_primary_unit_id,
            )
            return self.async_show_progress_done(next_step_id="cannot_connect")
        except ConnectionInterruptedException:
            _LOGGER.warning(
                "Connection to %s:%s was interrupted during setup, "
                "probably due to another device connecting at the same time. "
                "The inverter only supports one Modbus connection at a time",
                self._host,
                self._port,
            )
            return self.async_show_progress_done(next_step_id="connection_interrupted")
        except (HuaweiSolarException, DeviceException):
            _LOGGER.exception(
                "Error while connecting to discovered device at %s:%s unit_id %s",
                self._host,
                self._port,
                self._discovered_primary_unit_id,
            )
            return self.async_show_progress_done(next_step_id="no_device_found")
        except Exception:  # allowed in config flow
            _LOGGER.exception(
                "Unexpected exception while connecting to discovered devices"
            )
            return self.async_show_progress_done(next_step_id="cannot_connect")

        self._slave_ids = info.pop("slave_ids")
        self._inverter_info = info

        if self._elevated_permissions and info["has_write_permission"] is False:
            self.context["title_placeholders"] = {"name": info["model_name"]}
            return self.async_show_progress_done(next_step_id="network_login")

        self._username = None
        self._password = None
        return self.async_show_progress_done(next_step_id="confirm_setup")

    async def async_step_confirm_setup(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show discovered device info and ask for confirmation before creating the entry."""
        assert self._inverter_info is not None
        if user_input is None:
            return self.async_show_form(
                step_id="confirm_setup",
                description_placeholders={
                    "model_name": self._inverter_info["model_name"],
                    "serial_number": self._inverter_info["serial_number"],
                    "slave_ids": ", ".join(str(sid) for sid in (self._slave_ids or [])),
                },
            )
        return await self._create_or_update_entry(self._inverter_info)

    async def async_step_cannot_connect(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Inform the user that the device could not be reached, offer to retry."""
        if user_input is None:
            return self.async_show_form(
                step_id="cannot_connect",
                description_placeholders={
                    "host": self._host or "",
                    "port": str(self._port or ""),
                },
            )
        self._reset_discovery_state()
        return await self.async_step_setup_network()

    async def async_step_connection_interrupted(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Inform the user the connection was interrupted by another device, offer to retry."""
        if user_input is None:
            return self.async_show_form(
                step_id="connection_interrupted",
                description_placeholders={
                    "host": self._host or "",
                    "port": str(self._port or ""),
                },
            )
        self._reset_discovery_state()
        return await self.async_step_setup_network()

    async def async_step_no_device_found(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Inform the user that no Huawei Solar device responded, offer to retry."""
        if user_input is None:
            placeholders: dict[str, str] = {
                "host": self._host or "",
                "port": str(self._port or ""),
                "slave_id": str(self._failed_slave_id)
                if self._failed_slave_id is not None
                else "unknown",
            }
            return self.async_show_form(
                step_id="no_device_found",
                description_placeholders=placeholders,
            )
        self._reset_discovery_state()
        return await self.async_step_setup_network()

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

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HuaweiSolarOptionsFlowHandler:
        """Get the options flow for this handler."""
        return HuaweiSolarOptionsFlowHandler()


class UnitIdsParseException(Exception):
    """Error while parsing the unit id's."""


class DeviceException(Exception):
    """Error while testing communication with a device."""

    def __init__(self, message: str, unit_id: int | None = None) -> None:
        """Initialize DeviceException."""
        super().__init__(message)
        self.unit_id = unit_id


class HuaweiSolarOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Huawei Solar options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, 30),
                    ): vol.All(vol.Coerce(int), vol.Range(min=5)),
                }
            ),
        )
