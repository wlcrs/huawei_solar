"""The Huawei Solar integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_HOST

from .const import DOMAIN, CONF_SLAVE, DATA_MODBUS_CLIENT

from huawei_solar import HuaweiSolar, ConnectionException

# TODO List the platforms that you want to support.
# For your initial PR, limit it to 1 platform.
PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Huawei Solar from a config entry."""
    # TODO Store an API object for your platforms to access
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_MODBUS_CLIENT: HuaweiSolar(
            host=entry.data[CONF_HOST], slave=entry.data[CONF_SLAVE]
        )
    }

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
"""Huawei Solar integration which connects to the local Modbus TCP endpoint"""