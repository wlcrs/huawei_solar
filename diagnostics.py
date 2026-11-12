"""Diagnostics support for Huawei Solar."""

from __future__ import annotations

from typing import Any

from huawei_solar import register_names as rn

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_UNIQUE_ID, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DATA_DEVICE_DATAS
from .types import (
    HuaweiSolarConfigEntry,
    HuaweiSolarDeviceData,
    HuaweiSolarInverterData,
)

TO_REDACT = {
    CONF_PASSWORD,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
    "previous_unique_id",
    "serial_number",
    rn.CHARGER_ESN,
    rn.MONITORING_BOARD_SN,
    rn.PV_PLANT_ID,
    rn.REGKEY,
    rn.SDONGLE_4G_APN,
    rn.SDONGLE_4G_DIAL_NUMBER,
    rn.SDONGLE_4G_USER_NAME,
    rn.SMARTLOGGER_EQUIPMENT_SERIAL_NUMBER_ESN,
    rn.STORAGE_UNIT_1_BATTERY_PACK_1_SERIAL_NUMBER,
    rn.STORAGE_UNIT_1_BATTERY_PACK_2_SERIAL_NUMBER,
    rn.STORAGE_UNIT_1_BATTERY_PACK_3_SERIAL_NUMBER,
    rn.STORAGE_UNIT_1_BATTERY_PACK_4_SERIAL_NUMBER,
    rn.STORAGE_UNIT_1_SERIAL_NUMBER,
    rn.STORAGE_UNIT_2_BATTERY_PACK_1_SERIAL_NUMBER,
    rn.STORAGE_UNIT_2_BATTERY_PACK_2_SERIAL_NUMBER,
    rn.STORAGE_UNIT_2_BATTERY_PACK_3_SERIAL_NUMBER,
    rn.STORAGE_UNIT_2_SERIAL_NUMBER,
    "storage_unit_2_battery_pack_4_serial_number",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HuaweiSolarConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    device_datas: list[HuaweiSolarDeviceData] = entry.runtime_data[DATA_DEVICE_DATAS]

    diagnostics_data = {
        "config_entry_data": dict(entry.data),
        "entities": {
            entity_entry.entity_id: entity_entry.extended_dict
            for entity_entry in er.async_entries_for_config_entry(
                er.async_get(hass), entry.entry_id
            )
        },
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
                "supports_ess_low_power": dd.device.supports_ess_low_power,
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
            }

        diagnostics_data[f"device_{dd.device.client.unit_id}_data"] = (
            dd.update_coordinator.data
        )

        if dd.configuration_update_coordinator:
            diagnostics_data[f"device_{dd.device.client.unit_id}_config_data"] = (
                dd.configuration_update_coordinator.data
            )

    return async_redact_data(diagnostics_data, TO_REDACT)
