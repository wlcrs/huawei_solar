"""This component provides switch entities for Huawei Solar."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Generic, TypeVar

from huawei_solar import HuaweiSolarBridge, register_names as rn, register_values as rv

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HuaweiSolarEntity, HuaweiSolarUpdateCoordinator
from .const import CONF_ENABLE_PARAMETER_CONFIGURATION, DATA_UPDATE_COORDINATORS, DOMAIN

_LOGGER = logging.getLogger(__name__)


T = TypeVar("T")


@dataclass
class HuaweiSolarSelectEntityDescription(Generic[T], SelectEntityDescription):
    """Huawei Solar Select Entity Description."""


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

    # When more than one inverter is present, then we suffix all sensors with '#1', '#2', ...
    # The order for these suffixes is the order in which the user entered the slave-ids.
    must_append_inverter_suffix = len(update_coordinators) > 1

    entities_to_add: list[SelectEntity] = []
    for idx, update_coordinator in enumerate(update_coordinators):
        slave_entities: list[HuaweiSolarSelectEntity] = []

        bridge = update_coordinator.bridge
        device_infos = update_coordinator.device_infos

        if bridge.battery_1_type != rv.StorageProductModel.NONE:
            assert device_infos["connected_energy_storage"]

            slave_entities.append(
                await StorageModeSelectEntity.create(
                    bridge, device_infos["connected_energy_storage"]
                )
            )

        else:
            _LOGGER.debug(
                "No battery detected on slave %s. Skipping energy storage switch entities",
                bridge.slave_id,
            )

            # Add suffix if multiple inverters are present
        if must_append_inverter_suffix:
            for entity in slave_entities:
                entity.add_name_suffix(f" #{idx+1}")

        entities_to_add.extend(slave_entities)

    async_add_entities(entities_to_add)


class HuaweiSolarSelectEntity(HuaweiSolarEntity, SelectEntity):
    """Huawei Solar Select Entity."""

    entity_description: HuaweiSolarSelectEntityDescription

    def __init__(
        self,
        bridge: HuaweiSolarBridge,
        description: HuaweiSolarSelectEntityDescription,
        device_info: DeviceInfo,
    ) -> None:
        """Huawei Solar Switch Entity constructor."""
        self.bridge = bridge
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{bridge.serial_number}_{description.key}"


class StorageModeSelectEntity(HuaweiSolarSelectEntity):
    """Huawei Solar Switch Entity."""

    entity_description: HuaweiSolarSelectEntityDescription

    def __init__(
        self,
        bridge: HuaweiSolarBridge,
        device_info: DeviceInfo,
        initial_value: rv.StorageWorkingModesC,
    ) -> None:
        """Huawei Solar Select Entity constructor.

        Do not use directly. Use `.create` instead!
        """
        super().__init__(
            bridge,
            HuaweiSolarSelectEntityDescription(
                key=rn.STORAGE_WORKING_MODE_SETTINGS,
                name="Working Mode",
                entity_category=EntityCategory.CONFIG,
            ),
            device_info,
        )

        # The options depend on the type of battery
        self.options_to_values = {}
        if bridge.battery_1_type == rv.StorageProductModel.HUAWEI_LUNA2000:
            self.options_to_values = {
                "Maximise Self Consumption": rv.StorageWorkingModesC.MAXIMISE_SELF_CONSUMPTION,
                "Time Of Use": rv.StorageWorkingModesC.TIME_OF_USE_LUNA2000,
            }
        elif bridge.battery_2_type == rv.StorageProductModel.LG_RESU:
            self.options_to_values = {
                "Maximise Self Consumption": rv.StorageWorkingModesC.MAXIMISE_SELF_CONSUMPTION,
                "Time Of Use": rv.StorageWorkingModesC.TIME_OF_USE_LG,
            }
        self._attr_options = list(self.options_to_values.keys())

        for key, value in self.options_to_values.items():
            if value == initial_value:
                self._attr_current_option = key

    @classmethod
    async def create(
        cls,
        bridge: HuaweiSolarBridge,
        device_info: DeviceInfo,
    ):
        """Huawei Solar Number Entity constructor.

        This async constructor fills in the necessary min/max values
        """

        # Assumption: these values are not updated outside of HA.
        # This should hold true as they typically can only be set via the Modbus-interface,
        # which only allows one client at a time.
        initial_value = (
            await bridge.client.get(rn.STORAGE_WORKING_MODE_SETTINGS)
        ).value

        return cls(bridge, device_info, initial_value)

    async def async_select_option(self, option) -> None:
        """Change the selected option."""

        await self.bridge.set(
            rn.STORAGE_WORKING_MODE_SETTINGS, self.options_to_values[option]
        )
        self._attr_current_option = option
