"""Diagnostics support for Huawei Solar."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import DATA_DEVICE_DATAS
from .types import (
    HuaweiSolarConfigEntry,
    HuaweiSolarDeviceData,
    HuaweiSolarInverterData,
)

TO_REDACT = {CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HuaweiSolarConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    device_datas: list[HuaweiSolarDeviceData] = entry.runtime_data[DATA_DEVICE_DATAS]

    diagnostics_data = {
        "config_entry_data": async_redact_data(dict(entry.data), TO_REDACT),
    }
    for dd in device_datas:
        if isinstance(dd, HuaweiSolarInverterData):
            diagnostics_data[f"device_{dd.device.client.unit_id}"] = {
                "_type": "SUN2000",
                "model_name": dd.device.model_name,
                "firmware_version": dd.device.firmware_version,
                "software_version": dd.device.software_version,
                "pv_string_count": dd.device.pv_string_count,
                "has_optimizers": dd.device.has_optimizers,
                "battery_type": dd.device.battery_type,
                "battery_1_type": dd.device.battery_1_type,
                "battery_2_type": dd.device.battery_2_type,
                "power_meter_type": dd.device.power_meter_type,
                "supports_capacity_control": dd.device.supports_capacity_control,
            }

            if dd.power_meter_update_coordinator:
                diagnostics_data[
                    f"device_{dd.device.client.unit_id}_power_meter_data"
                ] = dd.power_meter_update_coordinator.data

            if dd.energy_storage_update_coordinator:
                diagnostics_data[f"device_{dd.device.client.unit_id}_battery_data"] = (
                    dd.energy_storage_update_coordinator.data
                )

            if dd.optimizer_update_coordinator:
                diagnostics_data[
                    f"device_{dd.device.client.unit_id}_optimizer_data"
                ] = dd.optimizer_update_coordinator.data
        else:
            diagnostics_data[f"device_{dd.device.client.unit_id}"] = {
                "_type": type(dd.device).__name__,
                "model_name": dd.device.model_name,
                "serial_number": dd.device.serial_number,
            }

        diagnostics_data[f"device_{dd.device.client.unit_id}_data"] = (
            dd.update_coordinator.data
        )

        if dd.configuration_update_coordinator:
            diagnostics_data[f"device_{dd.device.client.unit_id}_config_data"] = (
                dd.configuration_update_coordinator.data
            )

    return diagnostics_data
