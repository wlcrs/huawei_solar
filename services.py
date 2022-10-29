"""The Huawei Solar services."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry

from huawei_solar import HuaweiSolarBridge
from huawei_solar import register_names as rn
from huawei_solar import register_values as rv

from .const import (
    CONF_ENABLE_PARAMETER_CONFIGURATION,
    DOMAIN,
    SERVICE_FORCIBLE_CHARGE,
    SERVICE_FORCIBLE_CHARGE_SOC,
    SERVICE_FORCIBLE_DISCHARGE,
    SERVICE_FORCIBLE_DISCHARGE_SOC,
    SERVICE_RESET_MAXIMUM_FEED_GRID_POWER,
    SERVICE_SET_MAXIMUM_FEED_GRID_POWER,
    SERVICE_SET_MAXIMUM_FEED_GRID_POWER_PERCENT,
    SERVICE_STOP_FORCIBLE_CHARGE,
)

if TYPE_CHECKING:
    from . import HuaweiInverterBridgeDeviceInfos

DATA_DEVICE_ID = "device_id"
DATA_POWER = "power"
DATA_POWER_PERCENTAGE = "power_percentage"
DATA_DURATION = "duration"
DATA_TARGET_SOC = "target_soc"


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


_LOGGER = logging.getLogger(__name__)


class HuaweiSolarServiceException(Exception):
    """Exception while executing Huawei Solar Service Call."""


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

    if entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION, False):
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
