"""The Huawei Solar integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import DOMAIN, CONF_SLAVE, DATA_MODBUS_CLIENT, DEFAULT_PORT

from huawei_solar import AsyncHuaweiSolar, ConnectionException

PLATFORMS: list[str] = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Huawei Solar from a config entry."""

    inverter = AsyncHuaweiSolar(
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        slave=entry.data[CONF_SLAVE]
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {DATA_MODBUS_CLIENT: inverter}

    # Fix for previously added entries which were missing a proper title

    model_name = (await inverter.get("model_name")).value

    if model_name != entry.title:
        hass.config_entries.async_update_entry(entry, title=model_name)

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        client = await hass.data[DOMAIN][entry.entry_id][DATA_MODBUS_CLIENT].client
        client.stop()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


"""Huawei Solar integration which connects to the local Modbus TCP endpoint"""
