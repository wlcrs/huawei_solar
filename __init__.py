"""The Huawei Solar integration."""

import logging

from huawei_solar import (
    EMMADevice,
    HuaweiSolarException,
    InvalidCredentials,
    SChargerDevice,
    SDongleDevice,
    SmartLoggerDevice,
    SUN2000Device,
    create_device_instance,
    create_rtu_client,
    create_sub_device_instance,
    create_tcp_client,
    register_values as rv,
)
from huawei_solar.device.base import HuaweiSolarDevice, HuaweiSolarDeviceWithLogin

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_ENABLE_PARAMETER_CONFIGURATION,
    CONF_SLAVE_IDS,
    CONFIGURATION_UPDATE_INTERVAL,
    DATA_DEVICE_DATAS,
    DOMAIN,
    ENERGY_STORAGE_UPDATE_INTERVAL,
    INVERTER_UPDATE_INTERVAL,
    OPTIMIZER_UPDATE_INTERVAL,
    POWER_METER_UPDATE_INTERVAL,
)
from .services import async_setup_services
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

PLATFORMS: list[Platform] = [
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: HuaweiSolarConfigEntry) -> bool:
    """Set up Huawei Solar from a config entry."""

    primary_device = None
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
                port=entry.data[CONF_PORT], unit_id=entry.data[CONF_SLAVE_IDS][0]
            )
        else:
            client = create_tcp_client(
                host=entry.data[CONF_HOST],
                port=entry.data[CONF_PORT],
                unit_id=entry.data[CONF_SLAVE_IDS][0],
            )

        primary_device = await create_device_instance(client)

        if entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION):
            if (
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

        for extra_unit_id in entry.data[CONF_SLAVE_IDS][1:]:
            sub_device = await create_sub_device_instance(primary_device, extra_unit_id)
            sub_device_data = await _setup_device_data(hass, entry, sub_device)

            device_datas.append(sub_device_data)

        entry.runtime_data = {
            DATA_DEVICE_DATAS: device_datas,
        }
    except (HuaweiSolarException, TimeoutError) as err:
        if primary_device is not None:
            await primary_device.stop()

        raise ConfigEntryNotReady from err

    except Exception:
        # always try to stop the bridge, as it will keep retrying
        # in the background otherwise!
        if primary_device is not None:
            await primary_device.stop()
        raise

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_setup_services(hass, entry)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: HuaweiSolarConfigEntry
) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        device_datas: list[HuaweiSolarDeviceData] = entry.runtime_data["device_datas"]
        primary_device = device_datas[0].device
        await primary_device.client.disconnect()

    return unload_ok


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


async def _setup_inverter_device_data(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device: SUN2000Device,
    connecting_inverter_device_id: tuple[str, str] | None,
) -> HuaweiSolarInverterData:
    device_registry = dr.async_get(hass)

    inverter_device_info = DeviceInfo(
        identifiers={(DOMAIN, device.serial_number)},
        translation_key="inverter",
        manufacturer="Huawei",
        model=device.model_name,
        serial_number=device.serial_number,
        sw_version=device.software_version,
        via_device=connecting_inverter_device_id,  # type: ignore[typeddict-item]
    )

    # Add inverter device to device registery
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device.serial_number)},
        manufacturer="Huawei",
        name=device.model_name,
        model=device.model_name,
        sw_version=device.software_version,
    )

    update_coordinator = HuaweiSolarUpdateCoordinator(
        hass,
        _LOGGER,
        device=device,
        name=f"{device.serial_number}_data_update_coordinator",
        update_interval=INVERTER_UPDATE_INTERVAL,
    )

    # Add power meter device if a power meter is detected
    if device.power_meter_type is not None:
        power_meter_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, f"{device.serial_number}/power_meter"),
            },
            translation_key="power_meter",
            via_device=(DOMAIN, device.serial_number),
        )
        power_meter_update_coordinator = HuaweiSolarUpdateCoordinator(
            hass,
            _LOGGER,
            device=device,
            name=f"{device.serial_number}_power_meter_data_update_coordinator",
            update_interval=POWER_METER_UPDATE_INTERVAL,
        )
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
            via_device=(DOMAIN, device.serial_number),
        )

        energy_storage_update_coordinator = HuaweiSolarUpdateCoordinator(
            hass,
            _LOGGER,
            device=device,
            name=f"{device.serial_number}_battery_data_update_coordinator",
            update_interval=ENERGY_STORAGE_UPDATE_INTERVAL,
        )
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
            via_device=(DOMAIN, device.serial_number),
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
            via_device=(DOMAIN, device.serial_number),
        )
    else:
        battery_2_device_info = None

    # Add optimizer devices if optimizers are detected
    if device.has_optimizers:
        optimizers_device_infos = {}
        try:
            optimizer_system_infos = (
                await device.get_optimizer_system_information_data()
            )
            for optimizer_id, optimizer in optimizer_system_infos.items():
                optimizers_device_infos[optimizer_id] = DeviceInfo(
                    identifiers={(DOMAIN, optimizer.sn)},
                    name=optimizer.sn,
                    manufacturer="Huawei",
                    model=optimizer.model,
                    sw_version=optimizer.software_version,
                    via_device=(DOMAIN, device.serial_number),
                )

            optimizer_update_coordinator = await create_optimizer_update_coordinator(
                hass,
                device,
                optimizers_device_infos,
                OPTIMIZER_UPDATE_INTERVAL,
            )
        except HuaweiSolarException as exception:
            _LOGGER.info(
                "Cannot create optimizer sensor entities as the integration has insufficient permissions. "
                "Consider enabling elevated permissions to get more optimizer data",
                exc_info=exception,
            )
            optimizers_device_infos = {}
            optimizer_update_coordinator = None
        except Exception as exc:  # pylint: disable=broad-except
            _LOGGER.exception(
                "Cannot create optimizer sensor entities due to an unexpected error",
                exc_info=exc,
            )
            optimizers_device_infos = {}
            optimizer_update_coordinator = None
    else:
        optimizers_device_infos = {}
        optimizer_update_coordinator = None

    if entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION, False):
        configuration_update_coordinator = HuaweiSolarUpdateCoordinator(
            hass,
            _LOGGER,
            device=device,
            name=f"{device.serial_number}_config_data_update_coordinator",
            update_interval=CONFIGURATION_UPDATE_INTERVAL,
        )
    else:
        configuration_update_coordinator = None

    return HuaweiSolarInverterData(
        device=device,
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
    )


DEVICE_CLASS_TO_TRANSLATION_KEY: dict[type[HuaweiSolarDevice], str] = {
    EMMADevice: "emma",
    SChargerDevice: "charger",
    SDongleDevice: "sdongle",
    SmartLoggerDevice: "smartlogger",
}


async def _setup_device_data(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device: HuaweiSolarDevice,
) -> HuaweiSolarDeviceData:
    """Create the correct DeviceInfo-objects, which can be used to correctly assign to entities in this integration."""
    if isinstance(device, SUN2000Device):
        return await _setup_inverter_device_data(hass, entry, device, None)

    device_registry = dr.async_get(hass)

    if hasattr(device, "software_version"):
        sw_version = device.software_version

    device_info = DeviceInfo(
        identifiers={(DOMAIN, device.serial_number)},
        translation_key=DEVICE_CLASS_TO_TRANSLATION_KEY[type(device)],
        manufacturer="Huawei",
        model=device.model_name,
        serial_number=device.serial_number,
        sw_version=sw_version,
    )

    # Add device to device registery
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device.serial_number)},
        manufacturer="Huawei",
        name=device.model_name,
        model=device.model_name,
        sw_version=sw_version,
    )

    update_coordinator = HuaweiSolarUpdateCoordinator(
        hass,
        _LOGGER,
        device=device,
        name=f"{device.serial_number}_data_update_coordinator",
        update_interval=INVERTER_UPDATE_INTERVAL,
    )

    if entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION, False):
        configuration_update_coordinator = HuaweiSolarUpdateCoordinator(
            hass,
            _LOGGER,
            device=device,
            name=f"{device.serial_number}_config_data_update_coordinator",
            update_interval=CONFIGURATION_UPDATE_INTERVAL,
        )
    else:
        configuration_update_coordinator = None

    return HuaweiSolarDeviceData(
        device=device,
        device_info=device_info,
        update_coordinator=update_coordinator,
        configuration_update_coordinator=configuration_update_coordinator,
    )
