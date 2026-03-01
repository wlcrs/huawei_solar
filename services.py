"""The Huawei Solar services."""

from __future__ import annotations

import logging
import re
from typing import Any, Literal, TypedDict, TypeVar

from huawei_solar import (
    EMMADevice,
    HuaweiSolarDevice,
    RegisterName,
    SUN2000Device,
    register_names as rn,
    register_values as rv,
)
from huawei_solar.register_definitions.periods import (
    ChargeDischargePeriod,
    ChargeFlag,
    HUAWEI_LUNA2000_TimeOfUsePeriod,
    LG_RESU_TimeOfUsePeriod,
    PeakSettingPeriod,
)
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_ENABLE_PARAMETER_CONFIGURATION,
    DATA_DEVICE_DATAS,
    DOMAIN,
    SERVICE_FORCIBLE_CHARGE,
    SERVICE_FORCIBLE_CHARGE_SOC,
    SERVICE_FORCIBLE_DISCHARGE,
    SERVICE_FORCIBLE_DISCHARGE_SOC,
    SERVICE_RESET_MAXIMUM_FEED_GRID_POWER,
    SERVICE_SET_CAPACITY_CONTROL_PERIODS,
    SERVICE_SET_DI_ACTIVE_POWER_SCHEDULING,
    SERVICE_SET_FIXED_CHARGE_PERIODS,
    SERVICE_SET_MAXIMUM_FEED_GRID_POWER,
    SERVICE_SET_MAXIMUM_FEED_GRID_POWER_PERCENT,
    SERVICE_SET_TOU_PERIODS,
    SERVICE_SET_ZERO_POWER_GRID_CONNECTION,
    SERVICE_STOP_FORCIBLE_CHARGE,
)
from .types import (
    HuaweiSolarConfigEntry,
    HuaweiSolarDeviceData,
    HuaweiSolarInverterData,
)

ALL_SERVICES = [
    SERVICE_FORCIBLE_CHARGE,
    SERVICE_FORCIBLE_CHARGE_SOC,
    SERVICE_FORCIBLE_DISCHARGE,
    SERVICE_FORCIBLE_DISCHARGE_SOC,
    SERVICE_RESET_MAXIMUM_FEED_GRID_POWER,
    SERVICE_SET_CAPACITY_CONTROL_PERIODS,
    SERVICE_SET_DI_ACTIVE_POWER_SCHEDULING,
    SERVICE_SET_FIXED_CHARGE_PERIODS,
    SERVICE_SET_MAXIMUM_FEED_GRID_POWER,
    SERVICE_SET_MAXIMUM_FEED_GRID_POWER_PERCENT,
    SERVICE_SET_TOU_PERIODS,
    SERVICE_SET_ZERO_POWER_GRID_CONNECTION,
    SERVICE_STOP_FORCIBLE_CHARGE,
]

DATA_DEVICE_ID = "device_id"
DATA_POWER = "power"
DATA_POWER_PERCENTAGE = "power_percentage"
DATA_DURATION = "duration"
DATA_TARGET_SOC = "target_soc"
DATA_PERIODS = "periods"


_LOGGER = logging.getLogger(__name__)


class HuaweiSolarServiceException(Exception):
    """Exception while executing Huawei Solar Service Call."""


#############################################
# Device validation and retrieval functions #
#############################################

T = TypeVar("T", bound=HuaweiSolarDevice)


@callback
def async_get_entry_id_for_service_call(
    call: ServiceCall,
) -> tuple[dr.DeviceEntry, HuaweiSolarConfigEntry]:
    """Get the entry ID related to a service call (by device ID)."""
    device_registry = dr.async_get(call.hass)
    device_id = call.data[ATTR_DEVICE_ID]
    if (device_entry := device_registry.async_get(device_id)) is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_device_id",
            translation_placeholders={"device_id": device_id},
        )

    for entry_id in device_entry.config_entries:
        if (entry := call.hass.config_entries.async_get_entry(entry_id)) is None:
            continue
        if entry.domain == DOMAIN:
            if entry.state is not ConfigEntryState.LOADED:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="entry_not_loaded",
                    translation_placeholders={"entry": entry.title},
                )
            return (device_entry, entry)

    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="config_entry_not_found",
        translation_placeholders={"device_id": device_id},
    )


@callback
def _get_device_data(
    call: ServiceCall,
) -> HuaweiSolarDeviceData:
    """Return the HuaweiSolarDeviceData associated with the device_id in the service call."""
    device_entry, entry = async_get_entry_id_for_service_call(call)

    device_datas: list[HuaweiSolarDeviceData] = entry.runtime_data[DATA_DEVICE_DATAS]
    for dd in device_datas:
        if "identifiers" not in dd.device_info:
            continue
        for identifier in dd.device_info["identifiers"]:
            for device_identifier in device_entry.identifiers:
                if identifier == device_identifier:
                    return dd

    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="ha_device_not_found",
        translation_placeholders={"device_id": device_entry.id},
    )


@callback
def _get_device_of_type_data[T](
    call: ServiceCall, device_type: type[T]
) -> HuaweiSolarDeviceData:
    dd = _get_device_data(call)
    if not isinstance(dd.device, device_type):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="wrong_device_type",
            translation_placeholders={
                "device_id": call.data[ATTR_DEVICE_ID],
                "expected_type": device_type.__name__,
                "actual_type": type(dd.device).__name__,
            },
        )
    return dd


@callback
def get_emma_device(call: ServiceCall) -> HuaweiSolarDeviceData:
    """Return the HuaweiEMMABridge associated with the emma device_id in the service call."""
    return _get_device_of_type_data(call, EMMADevice)


EMMA_DEVICE_SCHEMA = vol.Schema({DATA_DEVICE_ID: vol.All(cv.string, str)})


@callback
def _get_battery_device_data(call: ServiceCall) -> HuaweiSolarInverterData:
    """Return the HuaweiSolarDeviceData associated with the device_id in the service call."""
    device_entry, entry = async_get_entry_id_for_service_call(call)

    device_datas: list[HuaweiSolarDeviceData] = entry.runtime_data[DATA_DEVICE_DATAS]
    for dd in device_datas:
        if not isinstance(dd, HuaweiSolarInverterData):
            continue
        if not dd.connected_energy_storage:
            continue
        if "identifiers" not in dd.connected_energy_storage:
            continue
        for identifier in dd.connected_energy_storage["identifiers"]:
            for device_identifier in device_entry.identifiers:
                if identifier == device_identifier:
                    return dd

    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="ha_device_not_found",
        translation_placeholders={"device_id": device_entry.id},
    )


@callback
def get_battery_device_data(call: ServiceCall) -> HuaweiSolarInverterData:
    """Return the HuaweiSolarInverterData associated with the battery device_id in the service call."""
    return _get_battery_device_data(call)


BATTERY_DEVICE_SCHEMA = vol.Schema({DATA_DEVICE_ID: vol.All(cv.string, str)})


@callback
def get_inverter_data(call: ServiceCall) -> HuaweiSolarInverterData:
    """Return the HuaweiSolarBridge associated with the inverter device_id in the service call."""
    dd = _get_device_of_type_data(call, SUN2000Device)
    if not isinstance(dd, HuaweiSolarInverterData):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="wrong_device_type",
            translation_placeholders={
                "device_id": call.data[ATTR_DEVICE_ID],
                "expected_type": "SUN2000",
                "actual_type": type(dd.device).__name__,
            },
        )
    return dd


###################################################
# Service schemas and schema validation functions #
###################################################

INVERTER_DEVICE_SCHEMA = vol.Schema({DATA_DEVICE_ID: vol.All(cv.string, str)})


FORCIBLE_CHARGE_BASE_SCHEMA = BATTERY_DEVICE_SCHEMA.extend(
    {
        vol.Required(DATA_POWER): cv.positive_int,
    }
)

DURATION_SCHEMA = FORCIBLE_CHARGE_BASE_SCHEMA.extend(
    {vol.Required(DATA_DURATION): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440))}
)

SOC_SCHEMA = FORCIBLE_CHARGE_BASE_SCHEMA.extend(
    {
        vol.Required(DATA_TARGET_SOC): vol.All(
            vol.Coerce(float), vol.Range(min=12, max=100)
        )
    }
)

MAXIMUM_FEED_GRID_POWER_SCHEMA = {
    vol.Required(DATA_POWER): vol.All(vol.Coerce(int), vol.Range(min=-1000)),
}


MAXIMUM_FEED_GRID_POWER_PERCENTAGE_SCHEMA = {
    vol.Required(DATA_POWER_PERCENTAGE): vol.All(
        vol.Coerce(int), vol.Range(min=0, max=100)
    ),
}


HUAWEI_LUNA2000_TOU_PATTERN = r"([0-2]\d:\d\d-[0-2]\d:\d\d/[1-7]{0,7}/[+-]\n?){0,14}"
LG_RESU_TOU_PATTERN = r"([0-2]\d:\d\d-[0-2]\d:\d\d/\d+\.?\d*\n?){0,14}"

BATTERY_TOU_PERIODS_SCHEMA = BATTERY_DEVICE_SCHEMA.extend(
    {
        vol.Required(DATA_PERIODS): vol.All(
            cv.string,
            vol.Match(HUAWEI_LUNA2000_TOU_PATTERN + r"|" + LG_RESU_TOU_PATTERN),
        )
    }
)

EMMA_TOU_PERIODS_SCHEMA = EMMA_DEVICE_SCHEMA.extend(
    {
        vol.Required(DATA_PERIODS): vol.All(
            cv.string,
            vol.Match(HUAWEI_LUNA2000_TOU_PATTERN),
        )
    }
)

CAPACITY_CONTROL_PERIODS_PATTERN = (
    r"([0-2]\d:\d\d-[0-2]\d:\d\d/[1-7]{1,7}/\d+W\n?){0,14}"
)

CAPACITY_CONTROL_PERIODS_SCHEMA = BATTERY_DEVICE_SCHEMA.extend(
    {
        vol.Required(DATA_PERIODS): vol.All(
            cv.string,
            vol.Match(CAPACITY_CONTROL_PERIODS_PATTERN),
        )
    }
)

FIXED_CHARGE_PERIODS_PATTERN = r"([0-2]\d:\d\d-[0-2]\d:\d\d/\d+W\n?){0,10}"

FIXED_CHARGE_PERIODS_SCHEMA = BATTERY_DEVICE_SCHEMA.extend(
    {
        vol.Required(DATA_PERIODS): vol.All(
            cv.string,
            vol.Match(FIXED_CHARGE_PERIODS_PATTERN),
        )
    }
)


def _parse_days_effective(
    days_text: str,
) -> tuple[bool, bool, bool, bool, bool, bool, bool]:
    days = [False, False, False, False, False, False, False]
    for day in days_text:
        days[int(day) % 7] = True

    return tuple(days)  # type: ignore[return-value]


def _parse_time(value: str) -> int:
    hours, minutes = value.split(":")

    minutes_since_midnight = int(hours) * 60 + int(minutes)

    if not 0 <= minutes_since_midnight <= 1440:
        raise ValueError(f"Invalid time '{value}': must be between 00:00 and 23:59")
    return minutes_since_midnight


async def _validate_power_value(
    power: Any, dd: HuaweiSolarDeviceData, max_value_key: rn.RegisterName
) -> int:
    maximum_active_power = (await dd.device.get(max_value_key)).value

    if not power <= maximum_active_power:
        raise ValueError(f"Power cannot be more than {maximum_active_power}W")

    return power


def _parse_huawei_luna2000_periods(text: str) -> list[HUAWEI_LUNA2000_TimeOfUsePeriod]:
    result = []
    for line in text.split("\n"):
        start_end_time_str, days_effective_str, charge_flag_str = line.split("/")
        start_time_str, end_time_str = start_end_time_str.split("-")

        result.append(
            HUAWEI_LUNA2000_TimeOfUsePeriod(
                _parse_time(start_time_str),
                _parse_time(end_time_str),
                ChargeFlag.CHARGE if charge_flag_str == "+" else ChargeFlag.DISCHARGE,
                _parse_days_effective(days_effective_str),
            )
        )

    return result


def _parse_lg_resu_periods(text: str) -> list[LG_RESU_TimeOfUsePeriod]:
    result = []
    for line in text.split("\n"):
        start_end_time_str, energy_price = line.split("/")
        start_time_str, end_time_str = start_end_time_str.split("-")

        result.append(
            LG_RESU_TimeOfUsePeriod(
                _parse_time(start_time_str),
                _parse_time(end_time_str),
                float(energy_price),
            )
        )

    return result


###################################
# Service handler implementations #
###################################


async def forcible_charge(service_call: ServiceCall) -> None:
    """Start a forcible charge on the battery."""
    dd = get_battery_device_data(service_call)
    power = await _validate_power_value(
        service_call.data[DATA_POWER], dd, rn.STORAGE_MAXIMUM_CHARGE_POWER
    )

    duration = service_call.data[DATA_DURATION]
    if duration > 1440:
        raise ValueError("Maximum duration is 1440 minutes")

    await dd.device.set(rn.STORAGE_FORCIBLE_CHARGE_POWER, power)
    await dd.device.set(
        rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD,
        duration,
    )
    await dd.device.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE,
        rv.StorageForcibleChargeDischargeTargetMode.TIME,
    )
    await dd.device.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
        rv.StorageForcibleChargeDischarge.CHARGE,
    )

    if dd.configuration_update_coordinator:
        await dd.configuration_update_coordinator.async_refresh()


async def forcible_discharge(service_call: ServiceCall) -> None:
    """Start a forcible charge on the battery."""
    dd = get_battery_device_data(service_call)
    power = await _validate_power_value(
        service_call.data[DATA_POWER], dd, rn.STORAGE_MAXIMUM_DISCHARGE_POWER
    )

    duration = service_call.data[DATA_DURATION]
    if duration > 1440:
        raise ValueError("Maximum duration is 1440 minutes")

    await dd.device.set(rn.STORAGE_FORCIBLE_DISCHARGE_POWER, power)
    await dd.device.set(
        rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD,
        duration,
    )
    await dd.device.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE,
        rv.StorageForcibleChargeDischargeTargetMode.TIME,
    )
    await dd.device.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
        rv.StorageForcibleChargeDischarge.DISCHARGE,
    )
    if dd.configuration_update_coordinator:
        await dd.configuration_update_coordinator.async_refresh()


async def forcible_charge_soc(service_call: ServiceCall) -> None:
    """Start a forcible charge on the battery until the target SOC is hit."""
    dd = get_battery_device_data(service_call)
    target_soc = service_call.data[DATA_TARGET_SOC]
    power = await _validate_power_value(
        service_call.data[DATA_POWER], dd, rn.STORAGE_MAXIMUM_CHARGE_POWER
    )

    await dd.device.set(rn.STORAGE_FORCIBLE_CHARGE_POWER, power)
    await dd.device.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SOC, target_soc)
    await dd.device.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE,
        rv.StorageForcibleChargeDischargeTargetMode.SOC,
    )
    await dd.device.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
        rv.StorageForcibleChargeDischarge.CHARGE,
    )
    if dd.configuration_update_coordinator:
        await dd.configuration_update_coordinator.async_refresh()


async def forcible_discharge_soc(service_call: ServiceCall) -> None:
    """Start a forcible discharge on the battery until the target SOC is hit."""
    dd = get_battery_device_data(service_call)
    target_soc = service_call.data[DATA_TARGET_SOC]
    power = await _validate_power_value(
        service_call.data[DATA_POWER], dd, rn.STORAGE_MAXIMUM_DISCHARGE_POWER
    )

    await dd.device.set(rn.STORAGE_FORCIBLE_DISCHARGE_POWER, power)
    await dd.device.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SOC, target_soc)
    await dd.device.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE,
        rv.StorageForcibleChargeDischargeTargetMode.SOC,
    )
    await dd.device.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
        rv.StorageForcibleChargeDischarge.DISCHARGE,
    )
    if dd.configuration_update_coordinator:
        await dd.configuration_update_coordinator.async_refresh()


async def stop_forcible_charge(service_call: ServiceCall) -> None:
    """Stop a forcible charge or discharge."""
    dd = get_battery_device_data(service_call)
    await dd.device.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
        rv.StorageForcibleChargeDischarge.STOP,
    )
    await dd.device.set(rn.STORAGE_FORCIBLE_DISCHARGE_POWER, 0)
    await dd.device.set(
        rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD,
        0,
    )
    await dd.device.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE,
        rv.StorageForcibleChargeDischargeTargetMode.TIME,
    )

    if dd.configuration_update_coordinator:
        await dd.configuration_update_coordinator.async_refresh()


class _PowerControlRegisters(TypedDict):
    MODE_REGISTER: RegisterName
    POWER_WATT_REGISTER: RegisterName
    POWER_PERCENT_REGISTER: RegisterName


PowerControlManagerType = Literal["inverter", "emma"]

POWER_CONTROL_REGISTERS: dict[PowerControlManagerType, _PowerControlRegisters] = {
    "inverter": {
        "MODE_REGISTER": rn.ACTIVE_POWER_CONTROL_MODE,
        "POWER_WATT_REGISTER": rn.MAXIMUM_FEED_GRID_POWER_WATT,
        "POWER_PERCENT_REGISTER": rn.MAXIMUM_FEED_GRID_POWER_PERCENT,
    },
    "emma": {
        "MODE_REGISTER": rn.EMMA_POWER_CONTROL_MODE_AT_GRID_CONNECTION_POINT,
        "POWER_WATT_REGISTER": rn.EMMA_MAXIMUM_FEED_GRID_POWER_WATT,
        "POWER_PERCENT_REGISTER": rn.EMMA_MAXIMUM_FEED_GRID_POWER_PERCENT,
    },
}


@callback
def _get_power_control_data(
    service_call: ServiceCall,
) -> tuple[PowerControlManagerType, HuaweiSolarDeviceData]:
    """Get device data and determine the power control manager type from the device."""
    dd = _get_device_data(service_call)
    if isinstance(dd.device, EMMADevice):
        return ("emma", dd)
    return ("inverter", dd)


async def reset_maximum_feed_grid_power(service_call: ServiceCall) -> None:
    """Set Active Power Control to 'Unlimited'."""
    manager_type, dd = _get_power_control_data(service_call)

    await dd.device.set(
        POWER_CONTROL_REGISTERS[manager_type]["MODE_REGISTER"],
        rv.ActivePowerControlMode.UNLIMITED,
    )
    await dd.device.set(POWER_CONTROL_REGISTERS[manager_type]["POWER_WATT_REGISTER"], 0)
    await dd.device.set(
        POWER_CONTROL_REGISTERS[manager_type]["POWER_PERCENT_REGISTER"],
        0,
    )

    if dd.configuration_update_coordinator:
        await dd.configuration_update_coordinator.async_refresh()


# only available for inverters
async def set_di_active_power_scheduling(service_call: ServiceCall) -> None:
    """Set Active Power Control to 'DI active scheduling'."""
    dd = get_inverter_data(service_call)
    await dd.device.set(
        rn.ACTIVE_POWER_CONTROL_MODE,
        rv.ActivePowerControlMode.DI_ACTIVE_SCHEDULING,
    )
    await dd.device.set(rn.MAXIMUM_FEED_GRID_POWER_WATT, 0)
    await dd.device.set(
        rn.MAXIMUM_FEED_GRID_POWER_PERCENT,
        0,
    )

    if dd.configuration_update_coordinator:
        await dd.configuration_update_coordinator.async_refresh()


async def set_zero_power_grid_connection(service_call: ServiceCall) -> None:
    """Set Active Power Control to 'Zero-Power Grid Connection'."""
    manager_type, dd = _get_power_control_data(service_call)
    await dd.device.set(
        POWER_CONTROL_REGISTERS[manager_type]["MODE_REGISTER"],
        rv.ActivePowerControlMode.ZERO_POWER_GRID_CONNECTION,
    )
    await dd.device.set(POWER_CONTROL_REGISTERS[manager_type]["POWER_WATT_REGISTER"], 0)
    await dd.device.set(
        POWER_CONTROL_REGISTERS[manager_type]["POWER_PERCENT_REGISTER"],
        0,
    )

    if dd.configuration_update_coordinator:
        await dd.configuration_update_coordinator.async_refresh()


async def set_maximum_feed_grid_power(service_call: ServiceCall) -> None:
    """Set Active Power Control to 'Power-limited grid connection' with the given wattage."""
    manager_type, dd = _get_power_control_data(service_call)
    power = await _validate_power_value(service_call.data[DATA_POWER], dd, rn.P_MAX)

    await dd.device.set(
        POWER_CONTROL_REGISTERS[manager_type]["POWER_WATT_REGISTER"], power
    )
    await dd.device.set(
        POWER_CONTROL_REGISTERS[manager_type]["MODE_REGISTER"],
        rv.ActivePowerControlMode.POWER_LIMITED_GRID_CONNECTION_WATT,
    )

    if dd.configuration_update_coordinator:
        await dd.configuration_update_coordinator.async_refresh()


async def set_maximum_feed_grid_power_percentage(service_call: ServiceCall) -> None:
    """Set Active Power Control to 'Power-limited grid connection' with the given percentage."""
    manager_type, dd = _get_power_control_data(service_call)
    power_percentage = service_call.data[DATA_POWER_PERCENTAGE]

    await dd.device.set(
        POWER_CONTROL_REGISTERS[manager_type]["POWER_PERCENT_REGISTER"],
        power_percentage,
    )
    await dd.device.set(
        POWER_CONTROL_REGISTERS[manager_type]["MODE_REGISTER"],
        rv.ActivePowerControlMode.POWER_LIMITED_GRID_CONNECTION_PERCENT,
    )

    if dd.configuration_update_coordinator:
        await dd.configuration_update_coordinator.async_refresh()


async def set_battery_tou_periods(
    service_call: ServiceCall,
) -> None:
    """Set the TOU periods of the battery."""

    dd = get_battery_device_data(service_call)

    if dd.device.battery_type == rv.StorageProductModel.HUAWEI_LUNA2000:
        if not re.fullmatch(
            HUAWEI_LUNA2000_TOU_PATTERN, service_call.data[DATA_PERIODS]
        ):
            raise ValueError(
                f"Invalid periods: validation failed for '{service_call.data[DATA_PERIODS]}' as LUNA2000 TOU periods"
            )
        await dd.device.set(
            rn.STORAGE_HUAWEI_LUNA2000_TIME_OF_USE_CHARGING_AND_DISCHARGING_PERIODS,
            _parse_huawei_luna2000_periods(service_call.data[DATA_PERIODS]),
        )
    elif dd.device.battery_type == rv.StorageProductModel.LG_RESU:
        if not re.fullmatch(LG_RESU_TOU_PATTERN, service_call.data[DATA_PERIODS]):
            raise ValueError(
                f"Invalid periods: validation failed for '{service_call.data[DATA_PERIODS]}' as LG RESU TOU periods"
            )
        await dd.device.set(
            rn.STORAGE_LG_RESU_TIME_OF_USE_PRICE_PERIODS,
            _parse_lg_resu_periods(service_call.data[DATA_PERIODS]),
        )

    if dd.configuration_update_coordinator:
        await dd.configuration_update_coordinator.async_refresh()


async def set_emma_tou_periods(
    service_call: ServiceCall,
) -> None:
    """Set the TOU periods of a battery controlled by an EMMA."""

    dd = get_emma_device(service_call)

    if not re.fullmatch(HUAWEI_LUNA2000_TOU_PATTERN, service_call.data[DATA_PERIODS]):
        raise ValueError(
            f"Invalid periods: validation failed for '{service_call.data[DATA_PERIODS]}' as TOU periods"
        )
    await dd.device.set(
        rn.EMMA_TOU_PERIODS,
        _parse_huawei_luna2000_periods(service_call.data[DATA_PERIODS]),
    )

    if dd.configuration_update_coordinator:
        await dd.configuration_update_coordinator.async_refresh()


def _parse_capacity_control_periods(text: str) -> list[PeakSettingPeriod]:
    result = []
    for line in text.split("\n"):
        start_end_time_str, days_str, wattage_str = line.split("/")
        start_time_str, end_time_str = start_end_time_str.split("-")

        result.append(
            PeakSettingPeriod(
                _parse_time(start_time_str),
                _parse_time(end_time_str),
                int(wattage_str[:-1]),
                _parse_days_effective(days_str),
            )
        )
    return result


async def set_capacity_control_periods(service_call: ServiceCall) -> None:
    """Set the Capacity Control Periods of the battery."""

    dd = get_battery_device_data(service_call)

    if not re.fullmatch(
        CAPACITY_CONTROL_PERIODS_PATTERN, service_call.data[DATA_PERIODS]
    ):
        raise ValueError(
            f"Invalid periods: could not validate '{service_call.data[DATA_PERIODS]}' as capacity control periods"
        )

    await dd.device.set(
        rn.STORAGE_CAPACITY_CONTROL_PERIODS,
        _parse_capacity_control_periods(service_call.data[DATA_PERIODS]),
    )

    if dd.configuration_update_coordinator:
        await dd.configuration_update_coordinator.async_refresh()


def _parse_fixed_charge_periods(text: str) -> list[ChargeDischargePeriod]:
    result = []
    for line in text.split("\n"):
        start_end_time_str, wattage_str = line.split("/")
        start_time_str, end_time_str = start_end_time_str.split("-")

        result.append(
            ChargeDischargePeriod(
                _parse_time(start_time_str),
                _parse_time(end_time_str),
                int(wattage_str[:-1]),
            )
        )
    return result


async def set_fixed_charge_periods(service_call: ServiceCall) -> None:
    """Set the fixed charging periods of the battery."""
    dd = get_battery_device_data(service_call)

    if not re.fullmatch(FIXED_CHARGE_PERIODS_PATTERN, service_call.data[DATA_PERIODS]):
        raise ValueError(
            f"Invalid periods: could not validate '{service_call.data[DATA_PERIODS]}' as fixed charging periods"
        )

    await dd.device.set(
        rn.STORAGE_FIXED_CHARGING_AND_DISCHARGING_PERIODS,
        _parse_fixed_charge_periods(service_call.data[DATA_PERIODS]),
    )

    if dd.configuration_update_coordinator:
        await dd.configuration_update_coordinator.async_refresh()


async def set_tou_periods(service_call: ServiceCall) -> None:
    """Set the TOU periods (dispatches to battery or EMMA handler based on device type)."""
    dd = _get_device_data(service_call)
    if isinstance(dd.device, EMMADevice):
        await set_emma_tou_periods(service_call)
    else:
        await set_battery_tou_periods(service_call)


async def async_setup_services(
    hass: HomeAssistant,
    entry: HuaweiSolarConfigEntry,
) -> None:
    """Huawei Solar Services Setup."""
    if not entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION, False):
        return

    # Guard: only register services once across all config entries.
    # Handlers resolve the correct device at call time via device_id,
    # so the services work regardless of which entry registered them.
    if hass.services.has_service(DOMAIN, SERVICE_RESET_MAXIMUM_FEED_GRID_POWER):
        return

    # Power control services (work with both inverters and EMMA devices).
    # The handler auto-detects the device type and uses the correct registers.
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_MAXIMUM_FEED_GRID_POWER,
        reset_maximum_feed_grid_power,
        schema=INVERTER_DEVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ZERO_POWER_GRID_CONNECTION,
        set_zero_power_grid_connection,
        schema=INVERTER_DEVICE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MAXIMUM_FEED_GRID_POWER,
        set_maximum_feed_grid_power,
        schema=INVERTER_DEVICE_SCHEMA.extend(MAXIMUM_FEED_GRID_POWER_SCHEMA),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MAXIMUM_FEED_GRID_POWER_PERCENT,
        set_maximum_feed_grid_power_percentage,
        schema=INVERTER_DEVICE_SCHEMA.extend(MAXIMUM_FEED_GRID_POWER_PERCENTAGE_SCHEMA),
    )
    # DI active scheduling is inverter-only; the handler validates the device type.
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DI_ACTIVE_POWER_SCHEDULING,
        set_di_active_power_scheduling,
        schema=INVERTER_DEVICE_SCHEMA,
    )

    # Battery services. Handlers validate that the target device has a battery.
    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCIBLE_CHARGE,
        forcible_charge,
        schema=DURATION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCIBLE_DISCHARGE,
        forcible_discharge,
        schema=DURATION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCIBLE_CHARGE_SOC,
        forcible_charge_soc,
        schema=SOC_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FORCIBLE_DISCHARGE_SOC,
        forcible_discharge_soc,
        schema=SOC_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_FORCIBLE_CHARGE,
        stop_forcible_charge,
        schema=BATTERY_DEVICE_SCHEMA,
    )

    # TOU periods — dispatcher determines battery vs EMMA format at call time.
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_TOU_PERIODS,
        set_tou_periods,
        schema=BATTERY_TOU_PERIODS_SCHEMA,
    )

    # Period-based configuration services.
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_FIXED_CHARGE_PERIODS,
        set_fixed_charge_periods,
        schema=FIXED_CHARGE_PERIODS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CAPACITY_CONTROL_PERIODS,
        set_capacity_control_periods,
        schema=CAPACITY_CONTROL_PERIODS_SCHEMA,
    )
