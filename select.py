"""This component provides switch entities for Huawei Solar."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Generic, TypeVar, Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from huawei_solar import HuaweiSolarBridge
from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.registers import REGISTERS

from . import (
    HuaweiSolarConfigurationUpdateCoordinator,
    HuaweiSolarEntity,
    HuaweiSolarUpdateCoordinator,
)
from .const import (
    CONF_ENABLE_PARAMETER_CONFIGURATION,
    DATA_CONFIGURATION_UPDATE_COORDINATORS,
    DATA_UPDATE_COORDINATORS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


T = TypeVar("T")


@dataclass
class HuaweiSolarSelectEntityDescription(Generic[T], SelectEntityDescription):
    """Huawei Solar Select Entity Description."""

    is_available_key: str | None = None
    check_is_available_func: Callable[[Any], bool] | None = None


ENERGY_STORAGE_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSelectEntityDescription, ...] = (
    HuaweiSolarSelectEntityDescription(
        key=rn.STORAGE_EXCESS_PV_ENERGY_USE_IN_TOU,
        name="Excess PV energy use in TOU",
        icon="mdi:battery-charging-medium",
        entity_category=EntityCategory.CONFIG,
    ),
)

CAPACITY_CONTROL_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSelectEntityDescription, ...] = (
    HuaweiSolarSelectEntityDescription(
        key=rn.STORAGE_CAPACITY_CONTROL_MODE,
        name="Capacity Control Mode",
        icon="mdi:battery-arrow-up",
        entity_category=EntityCategory.CONFIG,
        # Active capacity control is only available is 'Charge from grid' is enabled
        is_available_key=rn.STORAGE_CHARGE_FROM_GRID_FUNCTION,
        check_is_available_func=lambda charge_from_grid: charge_from_grid,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Huawei Solar Select Entities Setup."""

    if not entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION, False):
        _LOGGER.info("Skipping select setup, as parameter configuration is not enabled")
        return

    update_coordinators = hass.data[DOMAIN][entry.entry_id][
        DATA_UPDATE_COORDINATORS
    ]  # type: list[HuaweiSolarUpdateCoordinator]

    configuration_update_coordinators = hass.data[DOMAIN][entry.entry_id][
        DATA_CONFIGURATION_UPDATE_COORDINATORS
    ]

    # When more than one inverter is present, then we suffix all sensors with '#1', '#2', ...
    # The order for these suffixes is the order in which the user entered the slave-ids.
    must_append_inverter_suffix = len(update_coordinators) > 1

    entities_to_add: list[SelectEntity] = []
    for idx, (update_coordinator, configuration_update_coordinator) in enumerate(
        zip(update_coordinators, configuration_update_coordinators)
    ):
        slave_entities: list[HuaweiSolarSelectEntity] = []

        bridge = update_coordinator.bridge
        device_infos = update_coordinator.device_infos

        if bridge.battery_type != rv.StorageProductModel.NONE:
            assert device_infos["connected_energy_storage"]

            for entity_description in ENERGY_STORAGE_SWITCH_DESCRIPTIONS:
                slave_entities.append(
                    HuaweiSolarSelectEntity(
                        configuration_update_coordinator,
                        bridge,
                        entity_description,
                        device_infos["connected_energy_storage"],
                    )
                )
            slave_entities.append(
                StorageModeSelectEntity(
                    configuration_update_coordinator,
                    bridge,
                    device_infos["connected_energy_storage"],
                )
            )

            if bridge.supports_capacity_control:
                for entity_description in CAPACITY_CONTROL_SWITCH_DESCRIPTIONS:
                    slave_entities.append(
                        HuaweiSolarSelectEntity(
                            configuration_update_coordinator,
                            bridge,
                            entity_description,
                            device_infos["connected_energy_storage"],
                        )
                    )

        else:
            _LOGGER.debug(
                "No battery detected on slave %s. Skipping energy storage select entities",
                bridge.slave_id,
            )

        # Add suffix if multiple inverters are present
        if must_append_inverter_suffix:
            for entity in slave_entities:
                entity.add_name_suffix(f" #{idx+1}")

        entities_to_add.extend(slave_entities)

    async_add_entities(entities_to_add)


class HuaweiSolarSelectEntity(CoordinatorEntity, HuaweiSolarEntity, SelectEntity):
    """Huawei Solar Select Entity."""

    entity_description: HuaweiSolarSelectEntityDescription

    def _friendly_format(self, value: IntEnum):
        return value.name.replace("_", " ").capitalize()

    def _to_enum(self, value: str):
        return getattr(self._register_unit, value.replace(" ", "_").upper())

    def __init__(
        self,
        coordinator: HuaweiSolarConfigurationUpdateCoordinator,
        bridge: HuaweiSolarBridge,
        description: HuaweiSolarSelectEntityDescription,
        device_info: DeviceInfo,
    ) -> None:
        """Huawei Solar Select Entity constructor."""
        super().__init__(coordinator)
        self.coordinator = coordinator

        self.bridge = bridge
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{bridge.serial_number}_{description.key}"

        self._register_unit: IntEnum = REGISTERS[description.key].unit

        self._attr_current_option = self._friendly_format(
            self.coordinator.data[self.entity_description.key].value
        )
        self._attr_options = [
            self._friendly_format(value) for value in self._register_unit
        ]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_current_option = self._friendly_format(
            self.coordinator.data[self.entity_description.key].value
        )

        if self.entity_description.check_is_available_func:
            is_available_register = self.coordinator.data[
                self.entity_description.is_available_key
            ]
            self._attr_available = self.entity_description.check_is_available_func(
                is_available_register.value if is_available_register else None
            )

        self.async_write_ha_state()

    async def async_select_option(self, option) -> None:
        """Change the selected option."""

        await self.bridge.set(self.entity_description.key, self._to_enum(option))
        self._attr_current_option = option

        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        """Override available property (from CoordinatorEntity) to take into account
        the custom check_is_available_func result"""
        available = super().available

        if self.entity_description.check_is_available_func and available:
            return self._attr_available

        return available


class StorageModeSelectEntity(CoordinatorEntity, HuaweiSolarEntity, SelectEntity):
    """Huawei Solar Storage Mode Select Entity.

    The available options depend on the type of battery used, so it needs
    separate logic.
    """

    entity_description: HuaweiSolarSelectEntityDescription

    def __init__(
        self,
        coordinator: HuaweiSolarConfigurationUpdateCoordinator,
        bridge: HuaweiSolarBridge,
        device_info: DeviceInfo,
    ) -> None:
        """Huawei Solar Storage Mode Select Entity constructor.

        Do not use directly. Use `.create` instead!
        """
        super().__init__(coordinator)
        self.coordinator = coordinator

        self.bridge = bridge
        self.entity_description = HuaweiSolarSelectEntityDescription(
            key=rn.STORAGE_WORKING_MODE_SETTINGS,
            name="Working Mode",
            entity_category=EntityCategory.CONFIG,
        )
        self._attr_device_info = device_info
        self._attr_unique_id = f"{bridge.serial_number}_{self.entity_description.key}"

        # The options depend on the type of battery
        self.options_to_values = {}
        if bridge.battery_type == rv.StorageProductModel.HUAWEI_LUNA2000:
            self.options_to_values = {
                "Maximise Self Consumption": rv.StorageWorkingModesC.MAXIMISE_SELF_CONSUMPTION,
                "Time Of Use": rv.StorageWorkingModesC.TIME_OF_USE_LUNA2000,
                "Fully Fed To Grid": rv.StorageWorkingModesC.FULLY_FED_TO_GRID,
            }
        elif bridge.battery_type == rv.StorageProductModel.LG_RESU:
            self.options_to_values = {
                "Maximise Self Consumption": rv.StorageWorkingModesC.MAXIMISE_SELF_CONSUMPTION,
                "Time Of Use": rv.StorageWorkingModesC.TIME_OF_USE_LG,
                "Fully Fed To Grid": rv.StorageWorkingModesC.FULLY_FED_TO_GRID,
            }

        self._update_current_option()

        self._attr_options = list(self.options_to_values.keys())

    def _update_current_option(self):
        current_value = self.coordinator.data[self.entity_description.key].value
        for key, value in self.options_to_values.items():
            if value == current_value:
                self._attr_current_option = key

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_current_option()
        self.async_write_ha_state()

    async def async_select_option(self, option) -> None:
        """Change the selected option."""

        await self.bridge.set(
            rn.STORAGE_WORKING_MODE_SETTINGS, self.options_to_values[option]
        )
        self._attr_current_option = option

        await self.coordinator.async_request_refresh()
