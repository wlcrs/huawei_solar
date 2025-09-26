"""The Huawei Solar services."""

from __future__ import annotations

from functools import partial
import logging
import re
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from datetime import datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, async_get_hass, callback
from homeassistant.helpers import device_registry as dr
import homeassistant.helpers.config_validation as cv
from huawei_solar import (
    HuaweiEMMABridge,
    HuaweiSolarBridge,
    HuaweiSUN2000Bridge,
    register_names as rn,
    register_values as rv,
)
from huawei_solar.registers import (
    ChargeDischargePeriod,
    ChargeFlag,
    HUAWEI_LUNA2000_TimeOfUsePeriod,
    LG_RESU_TimeOfUsePeriod,
    PeakSettingPeriod,
)

from .const import (
    CONF_ENABLE_PARAMETER_CONFIGURATION,
    DATA_UPDATE_COORDINATORS,
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
from .update_coordinator import HuaweiSolarUpdateCoordinator

if TYPE_CHECKING:
    from . import HuaweiSolarUpdateCoordinators

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

def validate_emma_device_id(device_id: str) -> str:
    """Validate whether the device_id refers to a 'Connected Emma' device."""
    hass = async_get_hass()

    try:
        _get_emma_bridge(hass, device_id)
    except HuaweiSolarServiceException as err:
        raise vol.Invalid(str(err)) from err
    else:
        return device_id
    
def validate_battery_device_id(device_id: str) -> str:
    """Validate whether the device_id refers to a 'Connected Energy Storage' device."""
    hass = async_get_hass()

    try:
        _get_battery_bridge(hass, device_id)
    except HuaweiSolarServiceException as err:
        raise vol.Invalid(str(err)) from err
    else:
        return device_id


def validate_inverter_device_id(device_id: str) -> str:
    """Validate whether the device_id refers to an 'Inverter' device."""
    hass = async_get_hass()
    try:
        _get_inverter_bridge(hass, device_id)
    except HuaweiSolarServiceException as err:
        raise vol.Invalid(str(err)) from err
    else:
        return device_id

def validate_luna200_tou_string(tou_string) ->bool:
    if not re.fullmatch(HUAWEI_LUNA2000_TOU_PATTERN, tou_string):
        return False
    times = re.findall(r'\d\d:\d\d', tou_string)
    for time_str in times:
        try:
            datetime.strptime(time_str, "%H:%M")
        except ValueError:
            return False    
    return True

INVERTER_DEVICE_SCHEMA = vol.Schema(
    {DATA_DEVICE_ID: vol.All(cv.string, validate_inverter_device_id)}
)

BATTERY_DEVICE_SCHEMA = vol.Schema(
    {DATA_DEVICE_ID: vol.All(cv.string, validate_battery_device_id)}
)
EMMA_DEVICE_SCHEMA = vol.Schema(
    {DATA_DEVICE_ID: vol.All(cv.string, validate_emma_device_id)}
)

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

MAXIMUM_FEED_GRID_POWER_SCHEMA = INVERTER_DEVICE_SCHEMA.extend(
    {
        vol.Required(DATA_POWER): vol.All(vol.Coerce(int), vol.Range(min=-1000)),
    }
)

MAXIMUM_FEED_GRID_POWER_PERCENTAGE_SCHEMA = INVERTER_DEVICE_SCHEMA.extend(
    {
        vol.Required(DATA_POWER_PERCENTAGE): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
    }
)

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
            vol.Match(HUAWEI_LUNA2000_TOU_PATTERN + r"|" + LG_RESU_TOU_PATTERN),
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

_LOGGER = logging.getLogger(__name__)


class HuaweiSolarServiceException(Exception):
    """Exception while executing Huawei Solar Service Call."""


def _parse_days_effective(days_text) -> tuple[bool, bool, bool, bool, bool, bool, bool]:
    days = [False, False, False, False, False, False, False]
    for day in days_text:
        days[int(day) % 7] = True

    return tuple(days)


def _parse_time(value: str):
    hours, minutes = value.split(":")

    minutes_since_midnight = int(hours) * 60 + int(minutes)

    if not 0 <= minutes_since_midnight <= 1440:
        raise ValueError(f"Invalid time '{value}': must be between 00:00 and 23:59")
    return minutes_since_midnight


@callback
def _get_battery_bridge(
    hass: HomeAssistant, device_id: str
) -> tuple[HuaweiSUN2000Bridge, HuaweiSolarUpdateCoordinator]:
    dev_reg = dr.async_get(hass)
    device_entry = dev_reg.async_get(device_id)

    if not device_entry:
        raise HuaweiSolarServiceException("No such device found")

    for entry_data in hass.data[DOMAIN].values():
        hsucs: list[HuaweiSolarUpdateCoordinators] = entry_data[
            DATA_UPDATE_COORDINATORS
        ]
        for uc in hsucs:
            if uc.device_infos["connected_energy_storage"] is None:
                continue

            assert isinstance(uc.bridge, HuaweiSUN2000Bridge)
            assert "identifiers" in uc.device_infos["connected_energy_storage"]
            for ces_identifier in uc.device_infos["connected_energy_storage"][
                "identifiers"
            ]:
                for device_identifier in device_entry.identifiers:
                    if ces_identifier == device_identifier:
                        assert uc.configuration_update_coordinator
                        return uc.bridge, uc.configuration_update_coordinator
    _LOGGER.error("The provided device is not a Connected Energy Storage")
    raise HuaweiSolarServiceException("Not a valid 'Connected Energy Storage' device")

@callback
def _get_emma_bridge(
    hass: HomeAssistant, device_id: str
) -> tuple[HuaweiSUN2000Bridge, HuaweiSolarUpdateCoordinator]:
    dev_reg = dr.async_get(hass)
    device_entry = dev_reg.async_get(device_id)

    if not device_entry:
        raise HuaweiSolarServiceException("No such device found")

    for entry_data in hass.data[DOMAIN].values():
        hsucs: list[HuaweiSolarUpdateCoordinators] = entry_data[
            DATA_UPDATE_COORDINATORS
        ]
        for uc in hsucs:
            if uc.device_infos["emma"] is None:
                continue
            assert isinstance(uc.bridge, HuaweiEMMABridge)

            device_info = uc.device_infos["emma"]
            assert "identifiers" in device_info
            for identifier in device_info["identifiers"]:
                for device_identifier in device_entry.identifiers:
                    if identifier == device_identifier:
                        assert uc.configuration_update_coordinator
                        return uc.bridge, uc.configuration_update_coordinator
    _LOGGER.error("The provided device is not EMMA")
    raise HuaweiSolarServiceException(
        "Not a valid 'EMMA' device"
    )

@callback
def get_battery_bridge(
    hass: HomeAssistant, service_call: ServiceCall
) -> tuple[HuaweiSUN2000Bridge, HuaweiSolarUpdateCoordinator]:
    """Return the HuaweiSolarBridge associated with the battery device_id in the service call."""
    device_id = service_call.data[DATA_DEVICE_ID]
    bridge, uc = _get_battery_bridge(hass, device_id)

    _LOGGER.info(
        "Got the following bridge and update_coordinators in get_battery_bridge: %r, %r",
        bridge,
        uc,
    )

    return bridge, uc


@callback
def _get_battery_or_emma_bridge(
    hass: HomeAssistant, device_id: str
) -> tuple[HuaweiSUN2000Bridge | HuaweiEMMABridge, HuaweiSolarUpdateCoordinator]:
    dev_reg = dr.async_get(hass)
    device_entry = dev_reg.async_get(device_id)

    if not device_entry:
        raise HuaweiSolarServiceException("No such device found")

    for entry_data in hass.data[DOMAIN].values():
        hsucs: list[HuaweiSolarUpdateCoordinators] = entry_data[
            DATA_UPDATE_COORDINATORS
        ]
        for uc in hsucs:
            if (
                uc.device_infos["connected_energy_storage"] is None
                and uc.device_infos["emma"] is None
            ):
                continue

            assert isinstance(uc.bridge, HuaweiSUN2000Bridge | HuaweiEMMABridge)

            device_info = None
            if uc.device_infos["connected_energy_storage"]:
                device_info = uc.device_infos["connected_energy_storage"]
            elif uc.device_infos["emma"]:
                device_info = uc.device_infos["emma"]

            assert "identifiers" in device_info
            for identifier in device_info["identifiers"]:
                for device_identifier in device_entry.identifiers:
                    if identifier == device_identifier:
                        assert uc.configuration_update_coordinator
                        return uc.bridge, uc.configuration_update_coordinator
    _LOGGER.error("The provided device is not a Connected Energy Storage or EMMA")
    raise HuaweiSolarServiceException(
        "Not a valid 'Connected Energy Storage' or 'EMMA' device"
    )


@callback
def get_battery_or_emma_bridge(
    hass: HomeAssistant, service_call: ServiceCall
) -> tuple[HuaweiSUN2000Bridge | HuaweiEMMABridge, HuaweiSolarUpdateCoordinator]:
    """Return the HuaweiSolarBridge associated with the battery device_id in the service call."""
    device_id = service_call.data[DATA_DEVICE_ID]
    bridge, uc = _get_battery_or_emma_bridge(hass, device_id)

    _LOGGER.info(
        "Got the following bridge and update_coordinators in get_battery_or_emma_bridge: %r, %r",
        bridge,
        uc,
    )

    return bridge, uc


@callback
def get_emma_bridge(
    hass: HomeAssistant, service_call: ServiceCall
) -> tuple[HuaweiEMMABridge, HuaweiSolarUpdateCoordinator]:
    """Return the HuaweiSolarBridge associated with the EMMA device_id in the service call."""
    device_id = service_call.data[DATA_DEVICE_ID]
    bridge, uc = _get_emma_bridge(hass, device_id)

    _LOGGER.info(
        "Got the following bridge and update_coordinators in get_emma_bridge: %r, %r",
        bridge,
        uc,
    )

    return bridge, uc


@callback
def _get_inverter_bridge(
    hass: HomeAssistant, device_id: str
) -> tuple[HuaweiSUN2000Bridge, HuaweiSolarUpdateCoordinator]:
    dev_reg = dr.async_get(hass)
    device_entry = dev_reg.async_get(device_id)

    if not device_entry:
        raise HuaweiSolarServiceException("No such device found")
    for entry_data in hass.data[DOMAIN].values():
        hsucs: list[HuaweiSolarUpdateCoordinators] = entry_data[
            DATA_UPDATE_COORDINATORS
        ]
        for uc in hsucs:
            if uc.device_infos["inverter"] is None:
                continue
            assert isinstance(uc.bridge, HuaweiSUN2000Bridge)
            assert "identifiers" in uc.device_infos["inverter"]
            for identifier in uc.device_infos["inverter"]["identifiers"]:
                for device_identifier in device_entry.identifiers:
                    if identifier == device_identifier:
                        assert uc.configuration_update_coordinator
                        return uc.bridge, uc.configuration_update_coordinator

    _LOGGER.error("The provided device is not an inverter")
    raise HuaweiSolarServiceException("Not a valid 'Inverter' device")


@callback
def get_inverter_bridge(
    hass: HomeAssistant, service_call: ServiceCall
) -> tuple[HuaweiSolarBridge, HuaweiSolarUpdateCoordinator]:
    """Return the HuaweiSolarBridge associated with the inverter device_id in the service call."""
    device_id = service_call.data[DATA_DEVICE_ID]
    return _get_inverter_bridge(hass, device_id)


async def _validate_power_value(power: Any, bridge: HuaweiSolarBridge, max_value_key):
    # this already checked by voluptuous:
    assert isinstance(power, int)

    maximum_active_power = (
        await bridge.client.get(max_value_key, bridge.slave_id)
    ).value

    if not power <= maximum_active_power:
        raise ValueError(f"Power cannot be more than {maximum_active_power}W")

    return power


async def forcible_charge(hass: HomeAssistant, service_call: ServiceCall) -> None:
    """Start a forcible charge on the battery."""
    bridge, uc = get_battery_bridge(hass, service_call)
    power = await _validate_power_value(
        service_call.data[DATA_POWER], bridge, rn.STORAGE_MAXIMUM_CHARGE_POWER
    )

    duration = service_call.data[DATA_DURATION]
    if duration > 1440:
        raise ValueError("Maximum duration is 1440 minutes")

    await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_POWER, power)
    await bridge.set(
        rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD,
        duration,
    )
    await bridge.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE,
        rv.StorageForcibleChargeDischargeTargetMode.TIME,
    )
    await bridge.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
        rv.StorageForcibleChargeDischarge.CHARGE,
    )

    await uc.async_refresh()


async def forcible_discharge(hass: HomeAssistant, service_call: ServiceCall) -> None:
    """Start a forcible charge on the battery."""
    bridge, uc = get_battery_bridge(hass, service_call)
    power = await _validate_power_value(
        service_call.data[DATA_POWER], bridge, rn.STORAGE_MAXIMUM_DISCHARGE_POWER
    )

    duration = service_call.data[DATA_DURATION]
    if duration > 1440:
        raise ValueError("Maximum duration is 1440 minutes")

    await bridge.set(rn.STORAGE_FORCIBLE_DISCHARGE_POWER, power)
    await bridge.set(
        rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD,
        duration,
    )
    await bridge.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE,
        rv.StorageForcibleChargeDischargeTargetMode.TIME,
    )
    await bridge.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
        rv.StorageForcibleChargeDischarge.DISCHARGE,
    )
    await uc.async_refresh()


async def forcible_charge_soc(hass: HomeAssistant, service_call: ServiceCall) -> None:
    """Start a forcible charge on the battery until the target SOC is hit."""
    bridge, uc = get_battery_bridge(hass, service_call)
    target_soc = service_call.data[DATA_TARGET_SOC]
    power = await _validate_power_value(
        service_call.data[DATA_POWER], bridge, rn.STORAGE_MAXIMUM_CHARGE_POWER
    )

    await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_POWER, power)
    await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SOC, target_soc)
    await bridge.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE,
        rv.StorageForcibleChargeDischargeTargetMode.SOC,
    )
    await bridge.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
        rv.StorageForcibleChargeDischarge.CHARGE,
    )

    await uc.async_refresh()


async def forcible_discharge_soc(
    hass: HomeAssistant, service_call: ServiceCall
) -> None:
    """Start a forcible discharge on the battery until the target SOC is hit."""
    bridge, uc = get_battery_bridge(hass, service_call)
    target_soc = service_call.data[DATA_TARGET_SOC]
    power = await _validate_power_value(
        service_call.data[DATA_POWER], bridge, rn.STORAGE_MAXIMUM_DISCHARGE_POWER
    )

    await bridge.set(rn.STORAGE_FORCIBLE_DISCHARGE_POWER, power)
    await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SOC, target_soc)
    await bridge.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE,
        rv.StorageForcibleChargeDischargeTargetMode.SOC,
    )
    await bridge.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
        rv.StorageForcibleChargeDischarge.DISCHARGE,
    )
    await uc.async_refresh()


async def stop_forcible_charge(hass: HomeAssistant, service_call: ServiceCall) -> None:
    """Stop a forcible charge or discharge."""
    bridge, uc = get_battery_bridge(hass, service_call)
    await bridge.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
        rv.StorageForcibleChargeDischarge.STOP,
    )
    await bridge.set(rn.STORAGE_FORCIBLE_DISCHARGE_POWER, 0)
    await bridge.set(
        rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD,
        0,
    )
    await bridge.set(
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE,
        rv.StorageForcibleChargeDischargeTargetMode.TIME,
    )

    await uc.async_refresh()


async def reset_maximum_feed_grid_power(
    hass: HomeAssistant, service_call: ServiceCall
) -> None:
    """Set Active Power Control to 'Unlimited'."""
    bridge, uc = get_inverter_bridge(hass, service_call)
    await bridge.set(
        rn.ACTIVE_POWER_CONTROL_MODE,
        rv.ActivePowerControlMode.UNLIMITED,
    )
    await bridge.set(rn.MAXIMUM_FEED_GRID_POWER_WATT, 0)
    await bridge.set(
        rn.MAXIMUM_FEED_GRID_POWER_PERCENT,
        0,
    )

    await uc.async_refresh()


async def set_di_active_power_scheduling(
    hass: HomeAssistant, service_call: ServiceCall
) -> None:
    """Set Active Power Control to 'DI active scheduling'."""
    bridge, uc = get_inverter_bridge(hass, service_call)
    await bridge.set(
        rn.ACTIVE_POWER_CONTROL_MODE,
        rv.ActivePowerControlMode.DI_ACTIVE_SCHEDULING,
    )
    await bridge.set(rn.MAXIMUM_FEED_GRID_POWER_WATT, 0)
    await bridge.set(
        rn.MAXIMUM_FEED_GRID_POWER_PERCENT,
        0,
    )

    await uc.async_refresh()


async def set_zero_power_grid_connection(
    hass: HomeAssistant, service_call: ServiceCall
) -> None:
    """Set Active Power Control to 'Zero-Power Grid Connection'."""
    bridge, uc = get_inverter_bridge(hass, service_call)
    await bridge.set(
        rn.ACTIVE_POWER_CONTROL_MODE,
        rv.ActivePowerControlMode.ZERO_POWER_GRID_CONNECTION,
    )
    await bridge.set(rn.MAXIMUM_FEED_GRID_POWER_WATT, 0)
    await bridge.set(
        rn.MAXIMUM_FEED_GRID_POWER_PERCENT,
        0,
    )

    await uc.async_refresh()


async def set_maximum_feed_grid_power(
    hass: HomeAssistant, service_call: ServiceCall
) -> None:
    """Set Active Power Control to 'Power-limited grid connection' with the given wattage."""
    bridge, uc = get_inverter_bridge(hass, service_call)
    power = await _validate_power_value(service_call.data[DATA_POWER], bridge, rn.P_MAX)

    await bridge.set(rn.MAXIMUM_FEED_GRID_POWER_WATT, power)
    await bridge.set(
        rn.ACTIVE_POWER_CONTROL_MODE,
        rv.ActivePowerControlMode.POWER_LIMITED_GRID_CONNECTION_WATT,
    )

    await uc.async_refresh()


async def set_maximum_feed_grid_power_percentage(
    hass: HomeAssistant, service_call: ServiceCall
) -> None:
    """Set Active Power Control to 'Power-limited grid connection' with the given percentage."""
    bridge, uc = get_inverter_bridge(hass, service_call)
    power_percentage = service_call.data[DATA_POWER_PERCENTAGE]

    await bridge.set(rn.MAXIMUM_FEED_GRID_POWER_PERCENT, power_percentage)
    await bridge.set(
        rn.ACTIVE_POWER_CONTROL_MODE,
        rv.ActivePowerControlMode.POWER_LIMITED_GRID_CONNECTION_PERCENT,
    )

    await uc.async_refresh()


async def set_tou_periods(hass: HomeAssistant, service_call: ServiceCall) -> None:
    """Set the TOU periods of the battery."""

    def _parse_huawei_luna2000_periods(
            text,
        ) -> list[HUAWEI_LUNA2000_TimeOfUsePeriod]:
            result = []
            for line in text.split("\n"):
                start_end_time_str, days_effective_str, charge_flag_str = line.split("/")
                start_time_str, end_time_str = start_end_time_str.split("-")

                result.append(
                    HUAWEI_LUNA2000_TimeOfUsePeriod(
                        _parse_time(start_time_str),
                        _parse_time(end_time_str),
                        ChargeFlag.CHARGE
                        if charge_flag_str == "+"
                        else ChargeFlag.DISCHARGE,
                        _parse_days_effective(days_effective_str),
                    )
                )

            return result

    def _parse_lg_resu_periods(text) -> list[LG_RESU_TimeOfUsePeriod]:
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

    try:
        bridge, uc = get_battery_or_emma_bridge(hass, service_call)
        if isinstance(bridge, HuaweiEMMABridge):
#          if not re.fullmatch(
#               HUAWEI_LUNA2000_TOU_PATTERN , service_call.data[DATA_PERIODS]
#           ):
            if not validate_luna200_tou_string(service_call.data[DATA_PERIODS]):
                raise ValueError(
                    f"Invalid periods: validation failed for '{service_call.data[DATA_PERIODS]}' as TOU periods"
                )
            await bridge.set(
                rn.EMMA_TOU_PERIODS,
                _parse_huawei_luna2000_periods(service_call.data[DATA_PERIODS]),
            )
        elif bridge.battery_type == rv.StorageProductModel.HUAWEI_LUNA2000:
#           if not re.fullmatch(
#               HUAWEI_LUNA2000_TOU_PATTERN, service_call.data[DATA_PERIODS]
#           ):
            if not validate_luna200_tou_string(service_call.data[DATA_PERIODS]):
                raise ValueError(
                    f"Invalid periods: validation failed for '{service_call.data[DATA_PERIODS]}' as LUNA2000 TOU periods"
                )
            await bridge.set(
                rn.STORAGE_HUAWEI_LUNA2000_TIME_OF_USE_CHARGING_AND_DISCHARGING_PERIODS,
                _parse_huawei_luna2000_periods(service_call.data[DATA_PERIODS]),
            )
        elif bridge.battery_type == rv.StorageProductModel.LG_RESU:
            if not re.fullmatch(LG_RESU_TOU_PATTERN, service_call.data[DATA_PERIODS]):
                raise ValueError(
                    f"Invalid periods: validation failed for '{service_call.data[DATA_PERIODS]}' as LG RESU TOU periods"
                )
            await bridge.set(
                rn.STORAGE_LG_RESU_TIME_OF_USE_CHARGING_AND_DISCHARGING_PERIODS,
                _parse_lg_resu_periods(service_call.data[DATA_PERIODS]),
            )

        await uc.async_refresh()
    except ValueError as err:
        raise vol.Invalid(str(err)) from err


async def set_capacity_control_periods(
    hass: HomeAssistant, service_call: ServiceCall
) -> None:
    """Set the Capacity Control Periods of the battery."""

    def _parse_periods(text) -> list[PeakSettingPeriod]:
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

    bridge, uc = get_battery_bridge(hass, service_call)

    _LOGGER.info(
        "Got the following bridge and update_coordinators in set_capacity_control_periods: %r, %r",
        bridge,
        uc,
    )

    if not re.fullmatch(
        CAPACITY_CONTROL_PERIODS_PATTERN, service_call.data[DATA_PERIODS]
    ):
        raise ValueError(
            f"Invalid periods: could not validate '{service_call.data[DATA_PERIODS]}' as capacity control periods"
        )

    await bridge.set(
        rn.STORAGE_CAPACITY_CONTROL_PERIODS,
        _parse_periods(service_call.data[DATA_PERIODS]),
    )

    await uc.async_refresh()


async def set_fixed_charge_periods(
    hass: HomeAssistant, service_call: ServiceCall
) -> None:
    """Set the fixed charging periods of the battery."""

    def _parse_periods(text) -> list[ChargeDischargePeriod]:
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

    bridge, uc = get_battery_bridge(hass, service_call)

    if not re.fullmatch(FIXED_CHARGE_PERIODS_PATTERN, service_call.data[DATA_PERIODS]):
        raise ValueError(
            f"Invalid periods: could not validate '{service_call.data[DATA_PERIODS]}' as fixed charging periods"
        )

    await bridge.set(
        rn.STORAGE_FIXED_CHARGING_AND_DISCHARGING_PERIODS,
        _parse_periods(service_call.data[DATA_PERIODS]),
    )

    await uc.async_refresh()


async def async_setup_services(
    hass: HomeAssistant,
    entry: ConfigEntry,
):
    """Huawei Solar Services Setup."""
    if not entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION, False):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_MAXIMUM_FEED_GRID_POWER,
        partial(reset_maximum_feed_grid_power, hass),
        schema=INVERTER_DEVICE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DI_ACTIVE_POWER_SCHEDULING,
        partial(set_di_active_power_scheduling, hass),
        schema=INVERTER_DEVICE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_ZERO_POWER_GRID_CONNECTION,
        partial(set_zero_power_grid_connection, hass),
        schema=INVERTER_DEVICE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MAXIMUM_FEED_GRID_POWER,
        partial(set_maximum_feed_grid_power, hass),
        schema=MAXIMUM_FEED_GRID_POWER_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MAXIMUM_FEED_GRID_POWER_PERCENT,
        partial(set_maximum_feed_grid_power_percentage, hass),
        schema=MAXIMUM_FEED_GRID_POWER_PERCENTAGE_SCHEMA,
    )

    hsucs: list[HuaweiSolarUpdateCoordinators] = hass.data[DOMAIN][entry.entry_id][
        DATA_UPDATE_COORDINATORS
    ]

    if any(
        isinstance(uc.bridge, HuaweiSUN2000Bridge)
        and uc.bridge.battery_type != rv.StorageProductModel.NONE
        for uc in hsucs
    ):
        hass.services.async_register(
            DOMAIN,
            SERVICE_FORCIBLE_CHARGE,
            partial(forcible_charge, hass),
            schema=DURATION_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_FORCIBLE_DISCHARGE,
            partial(forcible_discharge, hass),
            schema=DURATION_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_FORCIBLE_CHARGE_SOC,
            partial(forcible_charge_soc, hass),
            schema=SOC_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_FORCIBLE_DISCHARGE_SOC,
            partial(forcible_discharge_soc, hass),
            schema=SOC_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_STOP_FORCIBLE_CHARGE,
            partial(stop_forcible_charge, hass),
            schema=BATTERY_DEVICE_SCHEMA,
        )

        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_TOU_PERIODS,
            partial(set_tou_periods, hass),
            schema=BATTERY_TOU_PERIODS_SCHEMA,
        )

        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_FIXED_CHARGE_PERIODS,
            partial(set_fixed_charge_periods, hass),
            schema=FIXED_CHARGE_PERIODS_SCHEMA,
        )

    if any(
        isinstance(uc.bridge, HuaweiSUN2000Bridge)
        and uc.bridge.supports_capacity_control
        for uc in hsucs
    ):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_CAPACITY_CONTROL_PERIODS,
            partial(set_capacity_control_periods, hass),
            schema=CAPACITY_CONTROL_PERIODS_SCHEMA,
        )

    if any(isinstance(uc.bridge, HuaweiEMMABridge) for uc in hsucs):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_TOU_PERIODS,
            partial(set_tou_periods, hass),
            schema=EMMA_TOU_PERIODS_SCHEMA,
        )


async def async_cleanup_services(hass: HomeAssistant):
    """Cleanup all Huawei Solar service (if all config entries unloaded)."""
    if len(hass.data[DOMAIN]) == 1:
        for service in ALL_SERVICES:
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)
