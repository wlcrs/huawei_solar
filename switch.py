"""This component provides switch entities for Huawei Solar."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Generic, TypeVar

from huawei_solar import HuaweiSolarBridge, register_names as rn, register_values as rv

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HuaweiSolarUpdateCoordinator
from .const import DATA_UPDATE_COORDINATORS, DOMAIN

_LOGGER = logging.getLogger(__name__)


T = TypeVar("T")


@dataclass
class HuaweiSolarSwitchEntityDescription(Generic[T], SwitchEntityDescription):
    """Huawei Solar Number Entity Description."""


ENERGY_STORAGE_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSwitchEntityDescription, ...] = (
    HuaweiSolarSwitchEntityDescription(
        key=rn.STORAGE_CHARGE_FROM_GRID_FUNCTION,
        name="Charge From Grid",
        icon="mdi:battery-charging-50",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Huawei Solar Switch Entities Setup."""

    update_coordinators = hass.data[DOMAIN][entry.entry_id][
        DATA_UPDATE_COORDINATORS
    ]  # type: list[HuaweiSolarUpdateCoordinator]

    entities_to_add: list[SwitchEntity] = []

    for update_coordinator in update_coordinators:
        bridge = update_coordinator.bridge
        device_infos = update_coordinator.device_infos

        if not bridge.has_write_access:
            _LOGGER.info(
                "Skipping slave %s, as we have no write access there", bridge.slave_id
            )
            continue

        if bridge.battery_1_type != rv.StorageProductModel.NONE:
            assert device_infos["connected_energy_storage"]

            for entity_description in ENERGY_STORAGE_SWITCH_DESCRIPTIONS:
                entities_to_add.append(
                    await HuaweiSolarSwitchEntity.create(
                        bridge,
                        entity_description,
                        device_infos["connected_energy_storage"],
                    )
                )
        else:
            _LOGGER.debug(
                "No battery detected on slave %s. Skipping energy storage number entities",
                bridge.slave_id,
            )

    async_add_entities(entities_to_add)


class HuaweiSolarSwitchEntity(SwitchEntity):
    """Huawei Solar Switch Entity."""

    entity_description: HuaweiSolarSwitchEntityDescription

    def __init__(
        self,
        bridge: HuaweiSolarBridge,
        description: HuaweiSolarSwitchEntityDescription,
        device_info: DeviceInfo,
        initial_value: bool,
    ) -> None:
        """Huawei Solar Switch Entity constructor.

        Do not use directly. Use `.create` instead!
        """
        self.bridge = bridge
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{bridge.serial_number}_{description.key}"
        self._attr_is_on = initial_value

    @classmethod
    async def create(
        cls,
        bridge: HuaweiSolarBridge,
        description: HuaweiSolarSwitchEntityDescription,
        device_info: DeviceInfo,
    ):
        """Huawei Solar Number Entity constructor.

        This async constructor fills in the necessary min/max values
        """

        # Assumption: these values are not updated outside of HA.
        # This should hold true as they typically can only be set via the Modbus-interface,
        # which only allows one client at a time.
        initial_value = (await bridge.client.get(description.key)).value

        return cls(bridge, description, device_info, initial_value)

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the setting on."""

        if await self.bridge.set(self.entity_description.key, True):
            self._attr_is_on = True

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the setting off."""

        if await self.bridge.set(self.entity_description.key, False):
            self._attr_is_on = False
