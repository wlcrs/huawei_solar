"""The Huawei Solar services."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from huawei_solar import HuaweiSolarBridge, register_names as rn, register_values as rv
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_ENABLE_PARAMETER_CONFIGURATION,
    DOMAIN,
    SERVICE_FORCIBLE_CHARGE,
    SERVICE_FORCIBLE_CHARGE_SOC,
    SERVICE_FORCIBLE_DISCHARGE,
    SERVICE_FORCIBLE_DISCHARGE_SOC,
    SERVICE_STOP_FORCIBLE_CHARGE,
)

if TYPE_CHECKING:
    from . import HuaweiInverterBridgeDeviceInfos

DATA_DEVICE_ID = "device_id"
DATA_POWER = "power"
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

    async def forcible_charge(service_call: ServiceCall) -> None:
        """Start a forcible charge on the battery."""
        duration = service_call.data[DATA_DURATION]
        power = service_call.data[DATA_POWER]

        bridge = get_battery_bridge(service_call)

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
        duration = service_call.data[DATA_DURATION]
        power = service_call.data[DATA_POWER]
        bridge = get_battery_bridge(service_call)

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

        target_soc = service_call.data[DATA_TARGET_SOC]
        power = service_call.data[DATA_POWER]
        bridge = get_battery_bridge(service_call)

        await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_POWER, power)
        await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SOC, target_soc)
        await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE, 1)
        await bridge.set(
            rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
            rv.StorageForcibleChargeDischarge.CHARGE,
        )

    async def forcible_discharge_soc(service_call: ServiceCall) -> None:
        """Start a forcible discharge on the battery until the target SOC is hit."""

        target_soc = service_call.data[DATA_TARGET_SOC]
        power = service_call.data[DATA_POWER]
        bridge = get_battery_bridge(service_call)

        await bridge.set(rn.STORAGE_FORCIBLE_DISCHARGE_POWER, power)
        await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SOC, target_soc)
        await bridge.set(rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE, 1)
        await bridge.set(
            rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
            rv.StorageForcibleChargeDischarge.DISCHARGE,
        )

    async def stop_forcible_charge(service_call: ServiceCall) -> None:
        """Start a forcible discharge on the battery until the target SOC is hit."""

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
