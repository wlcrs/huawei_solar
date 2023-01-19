"""Diagnostics support for Velbus."""
from __future__ import annotations

from itertools import zip_longest
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from huawei_solar import HuaweiSolarBridge

from . import (
    HuaweiSolarUpdateCoordinator,
    HuaweiSolarConfigurationUpdateCoordinator,
    HuaweiSolarOptimizerUpdateCoordinator,
)
from .const import (
    DATA_UPDATE_COORDINATORS,
    DOMAIN,
    DATA_CONFIGURATION_UPDATE_COORDINATORS,
    DATA_OPTIMIZER_UPDATE_COORDINATORS,
)

TO_REDACT = {CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    coordinators: list[HuaweiSolarUpdateCoordinator] = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_UPDATE_COORDINATORS]

    config_coordinators: list[HuaweiSolarConfigurationUpdateCoordinator] = hass.data[
        DOMAIN
    ][entry.entry_id][DATA_CONFIGURATION_UPDATE_COORDINATORS]

    optimizer_coordinators: list[HuaweiSolarOptimizerUpdateCoordinator] = hass.data[
        DOMAIN
    ][entry.entry_id][DATA_OPTIMIZER_UPDATE_COORDINATORS]

    diagnostics_data = {
        "config_entry_data": async_redact_data(dict(entry.data), TO_REDACT)
    }
    for coordinator, config_coordinator, optimizer_coordinator in zip_longest(
        coordinators, config_coordinators, optimizer_coordinators
    ):
        diagnostics_data[
            f"slave_{coordinator.bridge.slave_id}"
        ] = await _build_bridge_diagnostics_info(coordinator.bridge)

        diagnostics_data[f"slave_{coordinator.bridge.slave_id}_data"] = coordinator.data

        if config_coordinator:
            diagnostics_data[
                f"slave_{coordinator.bridge.slave_id}_config_data"
            ] = config_coordinator.data

        if optimizer_coordinator:
            diagnostics_data[
                f"slave_{coordinator.bridge.slave_id}_optimizer_data"
            ] = optimizer_coordinator.data

    return diagnostics_data


async def _build_bridge_diagnostics_info(bridge: HuaweiSolarBridge) -> dict[str, Any]:

    diagnostics_data = {
        "model_name": bridge.model_name,
        "pv_string_count": bridge.pv_string_count,
        "has_optimizers": bridge.has_optimizers,
        "battery_type": bridge.battery_type,
        "battery_1_type": bridge.battery_1_type,
        "battery_2_type": bridge.battery_2_type,
        "power_meter_type": bridge.power_meter_type,
        "supports_capacity_control": bridge.supports_capacity_control,
    }

    return diagnostics_data
