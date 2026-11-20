"""The Huawei Solar integration."""

import logging
from datetime import datetime
from typing import cast

from tmodbus.exceptions import IllegalFunctionError

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import ChildDeviceInfo, DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
from huawei_solar import (
    ConnectionException,
    ConnectionInterruptedException,
    EMMADevice,
    HuaweiSolarException,
    InvalidCredentials,
    MeterDevice,
    ReadException,
    RegisterName,
    SChargerDevice,
    SDongleDevice,
    SmartAcGunDevice,
    SmartGuardDevice,
    SmartLoggerDevice,
    SUN2000Device,
    create_device_instance,
    create_rtu_client,
    create_sub_device_instance,
    create_tcp_client,
)
from huawei_solar import (
    register_values as rv,
)
from huawei_solar.device.base import HuaweiSolarDevice, HuaweiSolarDeviceWithLogin
from huawei_solar.modbus_pdu import PermissionDeniedError

from .const import (
    CONF_BAUDRATE,
    CONF_ENABLE_PARAMETER_CONFIGURATION,
    CONF_SLAVE_IDS,
    CONFIGURATION_UPDATE_INTERVAL,
    DEFAULT_BAUDRATE,
    DOMAIN,
    ENERGY_STORAGE_UPDATE_INTERVAL,
    INVERTER_UPDATE_INTERVAL,
    OPTIMIZER_UPDATE_INTERVAL,
    POWER_METER_UPDATE_INTERVAL,
    SUB_DEVICE_RETRY_INTERVAL,
)
from .number import get_number_registers
from .select import get_select_registers
from .sensor import (
    get_configuration_sensor_registers,
    get_device_sensor_registers,
    get_energy_storage_sensor_registers,
    get_inverter_sensor_registers,
    get_power_meter_sensor_registers,
)
from .services import async_setup_services
from .switch import get_switch_registers
from .types import (
    HuaweiSolarConfigEntry,
    HuaweiSolarDeviceData,
    HuaweiSolarInverterData,
)
from .update_coordinator import (
    HuaweiSolarUpdateCoordinator,
    create_optimizer_update_coordinator,
)

_LOGGER = logging.getLogger(__name__)

_MIGRATED_UNIQUE_ID_SUFFIXES: dict[str, str] = {
    "phase_a_voltage_built_in_energy_sensor": "phase_a_voltage_built_in_energy",
    "phase_b_voltage_built_in_energy_sensor": "phase_b_voltage_built_in_energy",
    "phase_c_voltage_built_in_energy_sensor": "phase_c_voltage_built_in_energy",
    "line_voltage_a_b_built_in_energy_sensor": "line_voltage_a_b_built_in_energy",
    "line_voltage_b_c_built_in_energy_sensor": "line_voltage_b_c_built_in_energy",
    "line_voltage_c_a_built_in_energy_sensor": "line_voltage_c_a_built_in_energy",
    "phase_a_current_built_in_energy_sensor": "phase_a_current_built_in_energy",
    "phase_b_current_built_in_energy_sensor": "phase_b_current_built_in_energy",
    "phase_c_current_built_in_energy_sensor": "phase_c_current_built_in_energy",
    "active_power_built_in_energy_sensor": "active_power_built_in_energy",
    "power_factor_built_in_energy_sensor": "power_factor_built_in_energy",
    "apparent_power_built_in_energy_sensor": "apparent_power_built_in_energy",
    "phase_a_active_power_built_in_energy_sensor": "phase_a_active_power_built_in_energy",
    "phase_b_active_power_built_in_energy_sensor": "phase_b_active_power_built_in_energy",
    "phase_c_active_power_built_in_energy_sensor": "phase_c_active_power_built_in_energy",
    "total_active_energy_built_in_energy_sensor": "total_active_energy_built_in_energy",
    "total_negative_active_energy_built_in_energy_sensor": "total_negative_active_energy_built_in_energy",
    "total_positive_active_energy_built_in_energy_sensor": "total_positive_active_energy_built_in_energy",
    "phase_a_voltage_external_energy_sensor": "phase_a_voltage_external_energy",
    "phase_b_voltage_external_energy_sensor": "phase_b_voltage_external_energy",
    "phase_c_voltage_external_energy_sensor": "phase_c_voltage_external_energy",
    "line_voltage_a_b_external_energy_sensor": "line_voltage_a_b_external_energy",
    "line_voltage_b_c_external_energy_sensor": "line_voltage_b_c_external_energy",
    "line_voltage_c_a_external_energy_sensor": "line_voltage_c_a_external_energy",
    "phase_a_current_external_energy_sensor": "phase_a_current_external_energy",
    "phase_b_current_external_energy_sensor": "phase_b_current_external_energy",
    "phase_c_current_external_energy_sensor": "phase_c_current_external_energy",
    "active_power_external_energy_sensor": "active_power_external_energy",
    "power_factor_external_energy_sensor": "power_factor_external_energy",
    "apparent_power_external_energy_sensor": "apparent_power_external_energy",
    "phase_a_active_power_external_energy_sensor": "phase_a_active_power_external_energy",
    "phase_b_active_power_external_energy_sensor": "phase_b_active_power_external_energy",
    "phase_c_active_power_external_energy_sensor": "phase_c_active_power_external_energy",
    "total_active_energy_external_energy_sensor": "total_active_energy_external_energy",
    "total_negative_active_energy_external_energy_sensor": "total_negative_active_energy_external_energy",
    "total_positive_active_energy_external_energy_sensor": "total_positive_active_energy_external_energy",
    "charger_phase_a_voltage_sensor": "charger_phase_a_voltage",
    "charger_phase_b_voltage_sensor": "charger_phase_b_voltage",
    "charger_phase_c_voltage_sensor": "charger_phase_c_voltage",
    "charger_total_energy_charged_sensor": "charger_total_energy_charged",
    "charger_temperature_sensor": "charger_temperature",
}

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entry data and entity unique IDs."""
    if entry.version > 1 or entry.minor_version > 2:
        return False

    if entry.version == 1 and entry.minor_version < 2:
        entity_registry = er.async_get(hass)

        for entity_entry in er.async_entries_for_config_entry(
            entity_registry, entry.entry_id
        ):
            for old_suffix, new_suffix in _MIGRATED_UNIQUE_ID_SUFFIXES.items():
                old_unique_id_suffix = f"_{old_suffix}"
                if not entity_entry.unique_id.endswith(old_unique_id_suffix):
                    continue

                new_unique_id = (
                    f"{entity_entry.unique_id[: -len(old_suffix)]}{new_suffix}"
                )
                try:
                    entity_registry.async_update_entity(
                        entity_entry.entity_id,
                        new_unique_id=new_unique_id,
                    )
                except ValueError:
                    _LOGGER.warning(
                        "Skipping unique_id migration for %s from %s to %s because the target already exists",
                        entity_entry.entity_id,
                        entity_entry.unique_id,
                        new_unique_id,
                    )
                else:
                    _LOGGER.debug(
                        "Migrated unique_id for %s from %s to %s",
                        entity_entry.entity_id,
                        entity_entry.unique_id,
                        new_unique_id,
                    )
                break

        hass.config_entries.async_update_entry(entry, minor_version=2)

    return True


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Huawei Solar component."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HuaweiSolarConfigEntry) -> bool:
    """Set up Huawei Solar from a config entry."""

    client = None
    primary_device = None
    try:
        try:
            # Multiple inverters can be connected to each other via a daisy chain,
            # via an internal modbus-network (ie. not the same modbus network that we are
            # using to talk to the inverter).
            #
            # Each inverter receives it's own 'slave id' in that case.
            # The inverter that we use as 'gateway' will then forward the request to
            # the proper inverter.

            #               ┌─────────────┐
            #               │  EXTERNAL   │
            #               │ APPLICATION │
            #               └──────┬──────┘
            #                      │
            #                 ┌────┴────┐
            #                 │PRIMARY  │
            #                 │INVERTER │
            #                 └────┬────┘
            #       ┌──────────────┼───────────────┐
            #       │              │               │
            #  ┌────┴────┐     ┌───┴─────┐    ┌────┴────┐
            #  │ SLAVE X │     │ SLAVE Y │    │SLAVE ...│
            #  └─────────┘     └─────────┘    └─────────┘

            if entry.data[CONF_HOST] is None:
                client = create_rtu_client(
                    port=entry.data[CONF_PORT],
                    baudrate=entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
                    unit_id=entry.data[CONF_SLAVE_IDS][0],
                )
            else:
                client = create_tcp_client(
                    host=entry.data[CONF_HOST],
                    port=entry.data[CONF_PORT],
                    unit_id=entry.data[CONF_SLAVE_IDS][0],
                )

            primary_device = await create_device_instance(client)

            if entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION) and (
                isinstance(primary_device, HuaweiSolarDeviceWithLogin)
                and entry.data.get(CONF_USERNAME)
                and entry.data.get(CONF_PASSWORD)
            ):
                try:
                    await primary_device.login(
                        entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
                    )
                except InvalidCredentials as err:
                    raise ConfigEntryAuthFailed from err

            primary_device_data = await _setup_device_data(
                hass,
                entry,
                primary_device,
            )

            device_datas: list[HuaweiSolarDeviceData] = [primary_device_data]
            skipped_unit_ids: list[int] = []

            # Sorted, so that an SCharger is always set up before the SmartAcGun(s)
            # that follow it, whatever order the slave IDs were entered in.
            for extra_unit_id in sorted(entry.data[CONF_SLAVE_IDS][1:]):
                try:
                    sub_device = await create_sub_device_instance(
                        primary_device, extra_unit_id
                    )
                except (ConnectionException, ConnectionInterruptedException):
                    # The connection to the primary device is broken: retry the whole setup.
                    raise
                except (HuaweiSolarException, TimeoutError) as err:
                    # A sub-device that does not respond (e.g. an EV charger on a circuit
                    # without power) must not prevent the primary device and the other
                    # sub-devices from being set up.
                    _LOGGER.warning(
                        "Cannot set up the device at unit_id %s, continuing without it. "
                        "The integration will be reloaded once the device responds again. "
                        "If the device was removed, reconfigure the integration without "
                        "this unit_id. Error: %r",
                        extra_unit_id,
                        err,
                    )
                    skipped_unit_ids.append(extra_unit_id)
                    continue
                if isinstance(sub_device, MeterDevice) and not isinstance(
                    primary_device, SmartLoggerDevice
                ):
                    _LOGGER.warning(
                        "Skipping meter device at unit_id %s: meters are only supported when connected via a SmartLogger",
                        extra_unit_id,
                    )
                    continue
                parent_device_id: str | None = None
                if isinstance(sub_device, SmartAcGunDevice):
                    # Link the connector to the SCharger with the highest unit ID below
                    # its own: the connector(s) of an SCharger follow it in unit ID.
                    parent_device_id = next(
                        (
                            dd.ha_device_id
                            for dd in reversed(device_datas)
                            if isinstance(dd.device, SChargerDevice)
                        ),
                        None,
                    )

                sub_device_data = await _setup_device_data(
                    hass,
                    entry,
                    sub_device,
                    parent_device_id=parent_device_id,
                    via_device_id=primary_device_data.ha_device_id
                    if parent_device_id is None
                    else None,
                )

                device_datas.append(sub_device_data)

            entry.runtime_data = device_datas

            if skipped_unit_ids:
                _async_track_skipped_sub_devices(
                    hass, entry, primary_device, skipped_unit_ids
                )
        except ConnectionInterruptedException as err:
            host = entry.data.get(CONF_HOST) or entry.data.get(CONF_PORT)
            raise ConfigEntryNotReady(
                f"Connection to the inverter at {host} was interrupted, probably by another device. "
                "The inverter only supports one Modbus connection at a time."
            ) from err
        except ConnectionException as err:
            host = entry.data.get(CONF_HOST) or entry.data.get(CONF_PORT)
            raise ConfigEntryNotReady(
                f"Cannot connect to the inverter at {host}. "
                "Verify the address and that the device is reachable. "
                "If the IP address has changed, reconfigure the integration."
            ) from err
        except TimeoutError as err:
            raise ConfigEntryNotReady(
                "The inverter is not responding to requests. "
                "It may be starting up or temporarily busy."
            ) from err
        except HuaweiSolarException as err:
            raise ConfigEntryNotReady(
                f"Failed to communicate with the inverter: {err}"
            ) from err
    except BaseException:
        # Always try to stop the device/client, as it may otherwise keep
        # background connections or retry loops alive.
        if primary_device is not None:
            await primary_device.stop()
        elif client is not None:
            await client.disconnect()
        raise

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


@callback
def _async_track_skipped_sub_devices(
    hass: HomeAssistant,
    entry: HuaweiSolarConfigEntry,
    primary_device: HuaweiSolarDevice,
    unit_ids: list[int],
) -> None:
    """Reload the config entry once a skipped sub-device responds again."""

    async def _async_check_skipped_sub_devices(_now: datetime) -> None:
        for unit_id in unit_ids:
            try:
                await create_sub_device_instance(primary_device, unit_id)
            except (HuaweiSolarException, TimeoutError) as err:
                _LOGGER.debug(
                    "Device at unit_id %s still does not respond: %r", unit_id, err
                )
                continue
            _LOGGER.info(
                "Device at unit_id %s responds again, reloading the integration",
                unit_id,
            )
            hass.config_entries.async_schedule_reload(entry.entry_id)
            return

    entry.async_on_unload(
        async_track_time_interval(
            hass,
            _async_check_skipped_sub_devices,
            SUB_DEVICE_RETRY_INTERVAL,
            name="Huawei Solar skipped sub-device check",
            cancel_on_shutdown=True,
        )
    )


async def async_unload_entry(
    hass: HomeAssistant, entry: HuaweiSolarConfigEntry
) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        device_datas: list[HuaweiSolarDeviceData] = entry.runtime_data
        for device_data in reversed(device_datas):
            await device_data.device.stop()

    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: HuaweiSolarConfigEntry,
    device_entry: dr.DeviceEntry | dr.ChildDeviceEntry,
) -> bool:
    """Allow removing a device if it is no longer active in this config entry."""
    if config_entry.state is not ConfigEntryState.LOADED:
        return False

    active_identifiers: set[tuple[str, str]] = set()
    for dd in config_entry.runtime_data:
        active_identifiers.update(dd.device_info.get("identifiers", ()))
        if isinstance(dd, HuaweiSolarInverterData):
            for device_info in (
                dd.power_meter,
                dd.connected_energy_storage,
                dd.battery_1,
                dd.battery_2,
            ):
                if device_info is not None:
                    active_identifiers.update(device_info.get("identifiers", ()))
            if dd.optimizer_update_coordinator and dd.optimizer_device_infos:
                for opt_device_info in dd.optimizer_device_infos.values():
                    active_identifiers.update(opt_device_info.get("identifiers", ()))

    return active_identifiers.isdisjoint(device_entry.identifiers)


def _battery_product_model_to_manufacturer(spm: rv.StorageProductModel) -> str | None:
    if spm == rv.StorageProductModel.HUAWEI_LUNA2000:
        return "Huawei"
    if spm == rv.StorageProductModel.LG_RESU:
        return "LG Chem"
    return None


def _battery_product_model_to_model(spm: rv.StorageProductModel) -> str | None:
    if spm == rv.StorageProductModel.HUAWEI_LUNA2000:
        return "LUNA 2000"
    if spm == rv.StorageProductModel.LG_RESU:
        return "RESU"
    return None


def _get_configuration_registers(
    device: HuaweiSolarDevice, *, has_write_permission: bool = False
) -> set[RegisterName]:
    """Get all registers for configuration update coordinator."""
    return (
        get_number_registers(device)
        | get_select_registers(device)
        | get_switch_registers(device)
        | get_configuration_sensor_registers(
            device, has_write_permission=has_write_permission
        )
    )


async def _async_create_common_device_setup(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device: HuaweiSolarDevice,
    device_info: DeviceInfo | ChildDeviceInfo,
    initial_registers: set[RegisterName],
) -> tuple[
    dr.DeviceEntry | dr.ChildDeviceEntry,
    bool,
    HuaweiSolarUpdateCoordinator,
    HuaweiSolarUpdateCoordinator | None,
]:
    """Register device, check write permission, and create main & config coordinators."""
    device_registry = dr.async_get(hass)

    if "parent_device_id" in device_info:
        ha_device: dr.DeviceEntry | dr.ChildDeviceEntry = (
            device_registry.async_get_or_create_child_from_info(
                config_entry_id=entry.entry_id,
                device_info=cast(ChildDeviceInfo, device_info),
            )
        )
    else:
        ha_device = device_registry.async_get_or_create_from_info(
            config_entry_id=entry.entry_id,
            device_info=cast(DeviceInfo, device_info),
        )

    has_write_permission = False
    if entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION, False):
        if isinstance(device, HuaweiSolarDeviceWithLogin):
            try:
                has_write_permission = await device.has_write_permission()
            except HuaweiSolarException:
                _LOGGER.debug(
                    "Failed to check write permission for %s", device.serial_number
                )
        else:
            has_write_permission = True

    update_coordinator = HuaweiSolarUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        device=device,
        name=f"{device.serial_number}_data_update_coordinator",
        update_interval=INVERTER_UPDATE_INTERVAL,
        initial_registers=initial_registers,
    )
    await update_coordinator.async_config_entry_first_refresh()

    if entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION, False):
        configuration_update_coordinator = HuaweiSolarUpdateCoordinator(
            hass,
            _LOGGER,
            config_entry=entry,
            device=device,
            name=f"{device.serial_number}_config_data_update_coordinator",
            update_interval=CONFIGURATION_UPDATE_INTERVAL,
            initial_registers=_get_configuration_registers(
                device, has_write_permission=has_write_permission
            ),
        )
        await configuration_update_coordinator.async_config_entry_first_refresh()
    else:
        configuration_update_coordinator = None

    return (
        ha_device,
        has_write_permission,
        update_coordinator,
        configuration_update_coordinator,
    )


async def _setup_inverter_device_data(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device: SUN2000Device,
    *,
    via_device_id: str | None = None,
) -> HuaweiSolarInverterData:
    inverter_device_info = DeviceInfo(
        identifiers={(DOMAIN, device.serial_number)},
        translation_key="inverter",
        manufacturer="Huawei",
        model=device.model_name,
        serial_number=device.serial_number,
        sw_version=device.software_version,
        via_device_id=via_device_id,
    )

    (
        ha_device,
        has_write_permission,
        update_coordinator,
        configuration_update_coordinator,
    ) = await _async_create_common_device_setup(
        hass, entry, device, inverter_device_info, get_inverter_sensor_registers(device)
    )

    # Add power meter device if a power meter is detected
    if device.power_meter_type is not None:
        power_meter_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, f"{device.serial_number}/power_meter"),
            },
            translation_key="power_meter",
            via_device_id=ha_device.id,
        )
        power_meter_update_coordinator = HuaweiSolarUpdateCoordinator(
            hass,
            _LOGGER,
            config_entry=entry,
            device=device,
            name=f"{device.serial_number}_power_meter_data_update_coordinator",
            update_interval=POWER_METER_UPDATE_INTERVAL,
            initial_registers=get_power_meter_sensor_registers(device),
        )
        await power_meter_update_coordinator.async_config_entry_first_refresh()
    else:
        power_meter_device_info = None
        power_meter_update_coordinator = None

    # Add battery device if a battery is detected
    if device.battery_type != rv.StorageProductModel.NONE:
        battery_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, f"{device.serial_number}/connected_energy_storage"),
            },
            translation_key="connected_energy_storage",
            model="Batteries",
            manufacturer=inverter_device_info.get("manufacturer"),
            via_device_id=ha_device.id,
        )

        energy_storage_update_coordinator = HuaweiSolarUpdateCoordinator(
            hass,
            _LOGGER,
            config_entry=entry,
            device=device,
            name=f"{device.serial_number}_battery_data_update_coordinator",
            update_interval=ENERGY_STORAGE_UPDATE_INTERVAL,
            initial_registers=get_energy_storage_sensor_registers(device),
        )
        await energy_storage_update_coordinator.async_config_entry_first_refresh()
    else:
        battery_device_info = None
        energy_storage_update_coordinator = None

    if device.battery_1_type != rv.StorageProductModel.NONE:
        battery_1_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, f"{device.serial_number}/battery_1"),
            },
            translation_key="battery_1",
            manufacturer=_battery_product_model_to_manufacturer(device.battery_1_type),
            model=_battery_product_model_to_model(device.battery_1_type),
            via_device_id=ha_device.id,
        )
    else:
        battery_1_device_info = None

    if device.battery_2_type != rv.StorageProductModel.NONE:
        battery_2_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, f"{device.serial_number}/battery_2"),
            },
            translation_key="battery_2",
            manufacturer=_battery_product_model_to_manufacturer(device.battery_2_type),
            model=_battery_product_model_to_model(device.battery_2_type),
            via_device_id=ha_device.id,
        )
    else:
        battery_2_device_info = None

    optimizers_device_infos = {}
    optimizer_update_coordinator = None

    # Add optimizer devices if optimizers are detected
    if device.has_optimizers and (
        # Optimizers are not accessible when connected through a SmartLogger
        not isinstance(device.primary_device, SmartLoggerDevice)
    ):
        try:
            optimizer_system_infos = (
                await device.get_optimizer_system_information_data()
            )

            optimizers_device_infos = {
                optimizer_id: DeviceInfo(
                    identifiers={(DOMAIN, optimizer.sn)},
                    name=optimizer.sn,
                    manufacturer="Huawei",
                    model=optimizer.model,
                    sw_version=optimizer.software_version,
                    via_device_id=ha_device.id,
                )
                for optimizer_id, optimizer in optimizer_system_infos.items()
            }

            optimizer_update_coordinator = await create_optimizer_update_coordinator(
                hass,
                device,
                entry,
                optimizers_device_infos,
                OPTIMIZER_UPDATE_INTERVAL,
            )
        except ConfigEntryNotReady:
            raise
        except ReadException as exception:
            if exception.modbus_exception_code == PermissionDeniedError.error_code:
                _LOGGER.info(
                    "Cannot create optimizer sensor entities as the integration has insufficient permissions. "
                    "Consider enabling elevated permissions to get more optimizer data",
                    exc_info=exception,
                )
            elif exception.modbus_exception_code == IllegalFunctionError.error_code:
                # The device rejected the file transfer function code itself.
                # Retrying the setup can never succeed, so continue without
                # optimizer entities instead of leaving the entry in setup_retry.
                _LOGGER.info(
                    "Cannot create optimizer sensor entities: the device rejected the "
                    "optimizer file transfer request with 'illegal function'. This "
                    "happens when the connection passes through a Modbus proxy or "
                    "gateway that does not forward Huawei's vendor-specific function "
                    "codes. Continuing without optimizer entities",
                    exc_info=exception,
                )
            else:
                raise ConfigEntryNotReady(
                    "Cannot create optimizer sensor entities due to a read error."
                ) from exception
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.exception(
                "Cannot create optimizer sensor entities due to an unexpected error",
                exc_info=exc,
            )

    if entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION, False):
        configuration_update_coordinator = HuaweiSolarUpdateCoordinator(
            hass,
            _LOGGER,
            config_entry=entry,
            device=device,
            name=f"{device.serial_number}_config_data_update_coordinator",
            update_interval=CONFIGURATION_UPDATE_INTERVAL,
            initial_registers=_get_configuration_registers(
                device, has_write_permission=has_write_permission
            ),
        )
        await configuration_update_coordinator.async_config_entry_first_refresh()
    else:
        configuration_update_coordinator = None

    return HuaweiSolarInverterData(
        device=device,
        ha_device_id=ha_device.id,
        device_info=inverter_device_info,
        update_coordinator=update_coordinator,
        power_meter=power_meter_device_info,
        power_meter_update_coordinator=power_meter_update_coordinator,
        connected_energy_storage=battery_device_info,
        energy_storage_update_coordinator=energy_storage_update_coordinator,
        optimizer_device_infos=optimizers_device_infos,
        optimizer_update_coordinator=optimizer_update_coordinator,
        battery_1=battery_1_device_info,
        battery_2=battery_2_device_info,
        configuration_update_coordinator=configuration_update_coordinator,
        has_write_permission=has_write_permission,
    )


DEVICE_CLASS_TO_TRANSLATION_KEY: dict[type[HuaweiSolarDevice], str] = {
    EMMADevice: "emma",
    MeterDevice: "power_meter",
    SChargerDevice: "charger",
    SDongleDevice: "sdongle",
    SmartAcGunDevice: "charger_connector",
    SmartGuardDevice: "smartguard",
    SmartLoggerDevice: "smartlogger",
}


async def _setup_device_data(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device: HuaweiSolarDevice,
    *,
    parent_device_id: str | None = None,
    via_device_id: str | None = None,
) -> HuaweiSolarDeviceData:
    """Create the correct DeviceInfo-objects, which can be used to correctly assign to entities in this integration."""
    if isinstance(device, SUN2000Device):
        return await _setup_inverter_device_data(
            hass, entry, device, via_device_id=via_device_id
        )

    translation_key = DEVICE_CLASS_TO_TRANSLATION_KEY[type(device)]

    if parent_device_id is not None:
        device_info: DeviceInfo | ChildDeviceInfo = ChildDeviceInfo(
            identifiers={(DOMAIN, device.serial_number)},
            parent_device_id=parent_device_id,
            translation_key=translation_key,
        )
    else:
        device_info = DeviceInfo(
            identifiers={(DOMAIN, device.serial_number)},
            translation_key=translation_key,
            manufacturer="Huawei",
            model=device.model_name,
            serial_number=device.serial_number,
            sw_version=getattr(device, "software_version", None),
            via_device_id=via_device_id,
        )

    (
        ha_device,
        has_write_permission,
        update_coordinator,
        configuration_update_coordinator,
    ) = await _async_create_common_device_setup(
        hass, entry, device, device_info, get_device_sensor_registers(device)
    )

    return HuaweiSolarDeviceData(
        device=device,
        ha_device_id=ha_device.id,
        device_info=device_info,
        update_coordinator=update_coordinator,
        configuration_update_coordinator=configuration_update_coordinator,
        has_write_permission=has_write_permission,
    )
