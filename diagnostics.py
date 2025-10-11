"""Diagnostics support for Huawei Solar."""

from __future__ import annotations

from importlib.metadata import version
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant
from huawei_solar import HuaweiChargerBridge, HuaweiEMMABridge, HuaweiSUN2000Bridge

from . import HuaweiSolarUpdateCoordinators
from .const import DATA_UPDATE_COORDINATORS, DOMAIN

TO_REDACT = {CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinators: list[HuaweiSolarUpdateCoordinators] = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_UPDATE_COORDINATORS]

    diagnostics_data = {
        "config_entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "pymodbus_version": version("pymodbus"),
    }
    for ucs in coordinators:
        if isinstance(ucs.bridge, HuaweiSUN2000Bridge):
            diagnostics_data[
                f"slave_{ucs.bridge.slave_id}"
            ] = await _build_sun2000_bridge_diagnostics_info(ucs.bridge)
        elif isinstance(ucs.bridge, HuaweiEMMABridge):
            diagnostics_data[
                f"slave_{ucs.bridge.slave_id}"
            ] = await _build_emma_bridge_diagnostics_info(ucs.bridge)
        elif isinstance(ucs.bridge, HuaweiChargerBridge):
            diagnostics_data[
                f"slave_{ucs.bridge.slave_id}"
            ] = await _build_charger_bridge_diagnostics_info(ucs.bridge)
        else:
            diagnostics_data[f"slave_{ucs.bridge.slave_id}"] = {
                "_type": "Unknown",
                "model_name": ucs.bridge.model_name,
                "firmware_version": ucs.bridge.firmware_version,
                "software_version": ucs.bridge.software_version,
            }

        diagnostics_data[f"slave_{ucs.bridge.slave_id}_inverter_data"] = (
            ucs.inverter_update_coordinator.data
        )

        if ucs.power_meter_update_coordinator:
            diagnostics_data[f"slave_{ucs.bridge.slave_id}_power_meter_data"] = (
                ucs.power_meter_update_coordinator.data
            )

        if ucs.energy_storage_update_coordinator:
            diagnostics_data[f"slave_{ucs.bridge.slave_id}_battery_data"] = (
                ucs.energy_storage_update_coordinator.data
            )

        if ucs.configuration_update_coordinator:
            diagnostics_data[f"slave_{ucs.bridge.slave_id}_config_data"] = (
                ucs.configuration_update_coordinator.data
            )

        if ucs.optimizer_update_coordinator:
            diagnostics_data[f"slave_{ucs.bridge.slave_id}_optimizer_data"] = (
                ucs.optimizer_update_coordinator.data
            )

    return diagnostics_data


async def _build_sun2000_bridge_diagnostics_info(
    bridge: HuaweiSUN2000Bridge,
) -> dict[str, Any]:
    return {
        "_type": "SUN2000",
        "model_name": bridge.model_name,
        "firmware_version": bridge.firmware_version,
        "software_version": bridge.software_version,
        "pv_string_count": bridge.pv_string_count,
        "has_optimizers": bridge.has_optimizers,
        "battery_type": bridge.battery_type,
        "battery_1_type": bridge.battery_1_type,
        "battery_2_type": bridge.battery_2_type,
        "power_meter_type": bridge.power_meter_type,
        "supports_capacity_control": bridge.supports_capacity_control,
    }


async def _build_emma_bridge_diagnostics_info(
    bridge: HuaweiEMMABridge,
) -> dict[str, Any]:
    return {
        "_type": "EMMA",
        "model_name": bridge.model_name,
        "software_version": bridge.software_version,
    }


async def _build_charger_bridge_diagnostics_info(
    bridge: HuaweiChargerBridge,
) -> dict[str, Any]:
    return {
        "_type": "SCharger",
        "model_name": bridge.model_name,
        "software_version": bridge.software_version,
    }
