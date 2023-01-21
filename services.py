"""The Huawei Solar services."""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry

from huawei_solar import HuaweiSolarBridge
from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.registers import (
    ChargeDischargePeriod,
    ChargeFlag,
    HUAWEI_LUNA2000_TimeOfUsePeriod,
    LG_RESU_TimeOfUsePeriod,
    PeakSettingPeriod,
)

from .const import (
    CONF_ENABLE_PARAMETER_CONFIGURATION,
    DOMAIN,
    SERVICE_FORCIBLE_CHARGE,
    SERVICE_FORCIBLE_CHARGE_SOC,
    SERVICE_FORCIBLE_DISCHARGE,
    SERVICE_FORCIBLE_DISCHARGE_SOC,
    SERVICE_RESET_MAXIMUM_FEED_GRID_POWER,
    SERVICE_SET_CAPACITY_CONTROL_PERIODS,
    SERVICE_SET_FIXED_CHARGE_PERIODS,
    SERVICE_SET_MAXIMUM_FEED_GRID_POWER,
    SERVICE_SET_MAXIMUM_FEED_GRID_POWER_PERCENT,
    SERVICE_SET_TOU_PERIODS,
    SERVICE_STOP_FORCIBLE_CHARGE,
)

if TYPE_CHECKING:
    from . import HuaweiInverterBridgeDeviceInfos

DATA_DEVICE_ID = "device_id"
DATA_POWER = "power"
DATA_POWER_PERCENTAGE = "power_percentage"
DATA_DURATION = "duration"
DATA_TARGET_SOC = "target_soc"
DATA_PERIODS = "periods"

DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(DATA_DEVICE_ID): cv.string,
    }
)

FORCIBLE_CHARGE_BASE_SCHEMA = DEVICE_SCHEMA.extend(
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

MAXIMUM_FEED_GRID_POWER_SCHEMA = DEVICE_SCHEMA.extend(
    {
        vol.Required(DATA_POWER): vol.All(vol.Coerce(int), vol.Range(min=-1000)),
    }
)

MAXIMUM_FEED_GRID_POWER_PERCENTAGE_SCHEMA = DEVICE_SCHEMA.extend(
    {
        vol.Required(DATA_POWER_PERCENTAGE): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
    }
)

HUAWEI_LUNA2000_TOU_PATTERN = r"([0-2]\d:\d\d-[0-2]\d:\d\d/[1-7]{1,7}/[+-]\n?){0,14}"
LG_RESU_TOU_PATTERN = r"([0-2]\d:\d\d-[0-2]\d:\d\d/\d+\.?\d*\n?){0,14}"

TOU_PERIODS_SCHEMA = DEVICE_SCHEMA.extend(
    {
        vol.Required(DATA_PERIODS): vol.All(
            cv.string,
            vol.Match((HUAWEI_LUNA2000_TOU_PATTERN + r"|" + LG_RESU_TOU_PATTERN)),
        )
    }
)

CAPACITY_CONTROL_PERIODS_PATTERN = (
    r"([0-2]\d:\d\d-[0-2]\d:\d\d/[1-7]{1,7}/\d+W\n?){0,14}"
)

CAPACITY_CONTROL_PERIODS_SCHEMA = DEVICE_SCHEMA.extend(
    {
        vol.Required(DATA_PERIODS): vol.All(
            cv.string,
            vol.Match(CAPACITY_CONTROL_PERIODS_PATTERN),
        )
    }
)

FIXED_CHARGE_PERIODS_PATTERN = r"([0-2]\d:\d\d-[0-2]\d:\d\d/\d+W\n?){0,10}"

FIXED_CHARGE_PERIODS_SCHEMA = DEVICE_SCHEMA.extend(
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


def _parse_days_effective(days_text):
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


async def async_setup_services(
    hass: HomeAssistant,
    entry: ConfigEntry,
    bridges_with_device_infos: list[
        tuple[HuaweiSolarBridge, HuaweiInverterBridgeDeviceInfos]
    ],
):
    """Huawei Solar Services Setup."""

    def get_battery_bridge(service_call: ServiceCall):
        dev_reg = device_registry.async_get(hass)
        device_entry = dev_reg.async_get(service_call.data[DATA_DEVICE_ID])

        if not device_entry:
            raise HuaweiSolarServiceException("No such device found")

        for bridge, device_infos in bridges_with_device_infos:
            if device_infos["connected_energy_storage"] is None:
                continue

            for ces_identifier in device_infos["connected_energy_storage"][
                "identifiers"
            ]:
                for device_identifier in device_entry.identifiers:
                    if ces_identifier == device_identifier:
                        return bridge

        _LOGGER.error("The provided device is not a Connected Energy Storage")
        raise HuaweiSolarServiceException(
            "Not a valid 'Connected Energy Storage' device"
        )

    def get_inverter_bridge(service_call: ServiceCall):
        dev_reg = device_registry.async_get(hass)
        device_entry = dev_reg.async_get(service_call.data[DATA_DEVICE_ID])

        if not device_entry:
            raise HuaweiSolarServiceException("No such device found")

        for bridge, device_infos in bridges_with_device_infos:

            for identifier in device_infos["inverter"]["identifiers"]:
                for device_identifier in device_entry.identifiers:
                    if identifier == device_identifier:
                        return bridge

        _LOGGER.error("The provided device is not an inverter")
        raise HuaweiSolarServiceException("Not a valid 'Inverter' device")

    async def _validate_power_value(
        power: Any, bridge: HuaweiSolarBridge, max_value_key
    ):
        # these are already checked by voluptuous:
        assert isinstance(power, int)
        assert power >= 0

        maximum_active_power = (
            await bridge.client.get(max_value_key, bridge.slave_id)
        ).value

        if not (0 <= power <= maximum_active_power):
            raise ValueError(f"Power must be between 0 and {maximum_active_power}")

        return power

    async def forcible_charge(service_call: ServiceCall) -> None:
        """Start a forcible charge on the battery."""
        bridge = get_battery_bridge(service_call)
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
        await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE, 0)
        await bridge.set(
            rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
            rv.StorageForcibleChargeDischarge.CHARGE,
        )

    async def forcible_discharge(service_call: ServiceCall) -> None:
        """Start a forcible charge on the battery."""
        bridge = get_battery_bridge(service_call)
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
        await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE, 0)
        await bridge.set(
            rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
            rv.StorageForcibleChargeDischarge.DISCHARGE,
        )

    async def forcible_charge_soc(service_call: ServiceCall) -> None:
        """Start a forcible charge on the battery until the target SOC is hit."""

        bridge = get_battery_bridge(service_call)
        target_soc = service_call.data[DATA_TARGET_SOC]
        power = await _validate_power_value(
            service_call.data[DATA_POWER], bridge, rn.STORAGE_MAXIMUM_CHARGE_POWER
        )

        await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_POWER, power)
        await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SOC, target_soc)
        await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE, 1)
        await bridge.set(
            rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
            rv.StorageForcibleChargeDischarge.CHARGE,
        )

    async def forcible_discharge_soc(service_call: ServiceCall) -> None:
        """Start a forcible discharge on the battery until the target SOC is hit."""

        bridge = get_battery_bridge(service_call)
        target_soc = service_call.data[DATA_TARGET_SOC]
        power = await _validate_power_value(
            service_call.data[DATA_POWER], bridge, rn.STORAGE_MAXIMUM_DISCHARGE_POWER
        )

        await bridge.set(rn.STORAGE_FORCIBLE_DISCHARGE_POWER, power)
        await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SOC, target_soc)
        await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE, 1)
        await bridge.set(
            rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
            rv.StorageForcibleChargeDischarge.DISCHARGE,
        )

    async def stop_forcible_charge(service_call: ServiceCall) -> None:
        """Stops a forcible charge or discharge."""

        bridge = get_battery_bridge(service_call)
        await bridge.set(
            rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
            rv.StorageForcibleChargeDischarge.STOP,
        )
        await bridge.set(rn.STORAGE_FORCIBLE_DISCHARGE_POWER, 0)
        await bridge.set(
            rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD,
            0,
        )
        await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE, 0)

    async def reset_maximum_feed_grid_power(service_call: ServiceCall) -> None:
        """Sets Active Power Control to 'Power-limited grid connection' with the given wattage."""

        bridge = get_inverter_bridge(service_call)
        await bridge.set(
            rn.ACTIVE_POWER_CONTROL_MODE,
            rv.ActivePowerControlMode.UNLIMITED,
        )
        await bridge.set(rn.MAXIMUM_FEED_GRID_POWER_WATT, 0)
        await bridge.set(
            rn.MAXIMUM_FEED_GRID_POWER_PERCENT,
            0,
        )

    async def set_maximum_feed_grid_power(service_call: ServiceCall) -> None:
        """Sets Active Power Control to 'Power-limited grid connection' with the given wattage."""

        bridge = get_inverter_bridge(service_call)
        power = await _validate_power_value(
            service_call.data[DATA_POWER], bridge, rn.P_MAX
        )

        await bridge.set(rn.MAXIMUM_FEED_GRID_POWER_WATT, power)
        await bridge.set(
            rn.ACTIVE_POWER_CONTROL_MODE,
            rv.ActivePowerControlMode.POWER_LIMITED_GRID_CONNECTION_WATT,
        )

    async def set_maximum_feed_grid_power_percentage(service_call: ServiceCall) -> None:
        """Sets Active Power Control to 'Power-limited grid connection' with the given percentage."""

        bridge = get_inverter_bridge(service_call)
        power_percentage = service_call.data[DATA_POWER_PERCENTAGE]

        await bridge.set(rn.MAXIMUM_FEED_GRID_POWER_PERCENT, power_percentage)
        await bridge.set(
            rn.ACTIVE_POWER_CONTROL_MODE,
            rv.ActivePowerControlMode.POWER_LIMITED_GRID_CONNECTION_PERCENT,
        )

    async def set_tou_periods(service_call: ServiceCall) -> None:
        def _parse_huawei_luna2000_periods(
            text,
        ) -> list[HUAWEI_LUNA2000_TimeOfUsePeriod]:
            result = []
            for line in text.split("\n"):
                start_end_time_str, days_effective_str, charge_flag_str = line.split(
                    "/"
                )
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

        bridge = get_battery_bridge(service_call)

        if bridge.battery_type == rv.StorageProductModel.HUAWEI_LUNA2000:
            if not re.fullmatch(
                HUAWEI_LUNA2000_TOU_PATTERN, service_call.data[DATA_PERIODS]
            ):
                raise ValueError("Invalid periods")
            await bridge.set(
                rn.STORAGE_TIME_OF_USE_CHARGING_AND_DISCHARGING_PERIODS,
                _parse_huawei_luna2000_periods(service_call.data[DATA_PERIODS]),
            )
        elif bridge.battery_type == rv.StorageProductModel.LG_RESU:
            if not re.fullmatch(LG_RESU_TOU_PATTERN, service_call.data[DATA_PERIODS]):
                raise ValueError("Invalid periods")
            await bridge.set(
                rn.STORAGE_TIME_OF_USE_CHARGING_AND_DISCHARGING_PERIODS,
                _parse_lg_resu_periods(service_call.data[DATA_PERIODS]),
            )

    async def set_capacity_control_periods(service_call: ServiceCall) -> None:
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

        bridge = get_battery_bridge(service_call)

        if not re.fullmatch(
            CAPACITY_CONTROL_PERIODS_PATTERN, service_call.data[DATA_PERIODS]
        ):
            raise ValueError("Invalid periods")

        await bridge.set(
            rn.STORAGE_CAPACITY_CONTROL_PERIODS,
            _parse_periods(service_call.data[DATA_PERIODS]),
        )

    async def set_fixed_charge_periods(service_call: ServiceCall) -> None:
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

        bridge = get_battery_bridge(service_call)

        if not re.fullmatch(
            FIXED_CHARGE_PERIODS_PATTERN, service_call.data[DATA_PERIODS]
        ):
            raise ValueError("Invalid periods")

        await bridge.set(
            rn.STORAGE_FIXED_CHARGING_AND_DISCHARGING_PERIODS,
            _parse_periods(service_call.data[DATA_PERIODS]),
        )

    if not entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION, False):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_MAXIMUM_FEED_GRID_POWER,
        reset_maximum_feed_grid_power,
        schema=DEVICE_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MAXIMUM_FEED_GRID_POWER,
        set_maximum_feed_grid_power,
        schema=MAXIMUM_FEED_GRID_POWER_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_MAXIMUM_FEED_GRID_POWER_PERCENT,
        set_maximum_feed_grid_power_percentage,
        schema=MAXIMUM_FEED_GRID_POWER_PERCENTAGE_SCHEMA,
    )

    if any(
        bridge.battery_type != rv.StorageProductModel.NONE
        for bridge, _ in bridges_with_device_infos
    ):
        hass.services.async_register(
            DOMAIN, SERVICE_FORCIBLE_CHARGE, forcible_charge, schema=DURATION_SCHEMA
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_FORCIBLE_DISCHARGE,
            forcible_discharge,
            schema=DURATION_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN, SERVICE_FORCIBLE_CHARGE_SOC, forcible_charge_soc, schema=SOC_SCHEMA
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
            schema=DEVICE_SCHEMA,
        )

        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_TOU_PERIODS,
            set_tou_periods,
            schema=TOU_PERIODS_SCHEMA,
        )

        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_FIXED_CHARGE_PERIODS,
            set_fixed_charge_periods,
            schema=FIXED_CHARGE_PERIODS_SCHEMA,
        )

        if any(
            bridge.supports_capacity_control for bridge, _ in bridges_with_device_infos
        ):
            hass.services.async_register(
                DOMAIN,
                SERVICE_SET_CAPACITY_CONTROL_PERIODS,
                set_capacity_control_periods,
                schema=CAPACITY_CONTROL_PERIODS_SCHEMA,
            )
