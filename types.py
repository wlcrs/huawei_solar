"""Typing for the Huawei Solar integration."""

from dataclasses import dataclass
from typing import TypedDict, cast

from huawei_solar import HuaweiSolarDevice, RegisterName, SUN2000Device

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription

from .update_coordinator import (
    HuaweiSolarOptimizerUpdateCoordinator,
    HuaweiSolarUpdateCoordinator,
)


@dataclass
class HuaweiSolarDeviceData:
    """Runtime data for the Huawei Solar integration."""

    device: HuaweiSolarDevice
    device_info: DeviceInfo
    update_coordinator: HuaweiSolarUpdateCoordinator
    configuration_update_coordinator: HuaweiSolarUpdateCoordinator | None


@dataclass
class HuaweiSolarInverterData(HuaweiSolarDeviceData):
    """Runtime data for the Huawei Solar integration for SUN2000 inverter devices."""

    device: SUN2000Device

    power_meter: DeviceInfo | None
    connected_energy_storage: DeviceInfo | None
    battery_1: DeviceInfo | None
    battery_2: DeviceInfo | None
    optimizer_device_infos: dict[int, DeviceInfo] | None

    power_meter_update_coordinator: HuaweiSolarUpdateCoordinator | None
    energy_storage_update_coordinator: HuaweiSolarUpdateCoordinator | None
    optimizer_update_coordinator: HuaweiSolarOptimizerUpdateCoordinator | None


type HuaweiSolarConfigEntry = ConfigEntry[HuaweiSolarData]


class HuaweiSolarData(TypedDict):
    """Data for each Huawei Solar config entry."""

    device_datas: list[HuaweiSolarDeviceData]


class HuaweiSolarEntity(Entity):
    """Huawei Solar Entity."""

    _attr_has_entity_name = True


class HuaweiSolarEntityDescription(EntityDescription):
    """Huawei Solar Entity Description."""

    @property
    def register_name(self) -> RegisterName:
        """Return the register name."""
        return cast("RegisterName", self.key)


class HuaweiSolarEntityContext(TypedDict):
    """Context for Huawei Solar Entities."""

    register_names: list[RegisterName]
