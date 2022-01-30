"""This component provides number entities for Huawei Solar."""
from __future__ import annotations

from dataclasses import dataclass
import logging

from huawei_solar import HuaweiSolarBridge, register_names as rn, register_values as rv

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, POWER_WATT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HuaweiSolarUpdateCoordinator
from .const import DATA_UPDATE_COORDINATORS, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class HuaweiSolarNumberEntityDescription(NumberEntityDescription):
    """Huawei Solar Number Entity Description."""

    minimum_key: str | None = None
    maximum_key: str | None = None
    custom_class: type[HuaweiSolarNumberEntity] | None = None


ENERGY_STORAGE_NUMBER_DESCRIPTIONS: tuple[HuaweiSolarNumberEntityDescription, ...] = (
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_MAXIMUM_CHARGING_POWER,
        min_value=0,
        maximum_key=rn.STORAGE_MAXIMUM_CHARGE_POWER,
        name="Maximum Charging Power",
        icon="mdi:battery-positive",
        unit_of_measurement=POWER_WATT,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_MAXIMUM_DISCHARGING_POWER,
        min_value=0,
        maximum_key=rn.STORAGE_MAXIMUM_DISCHARGE_POWER,
        name="Maximum Discharging Power",
        icon="mdi:battery-negative",
        unit_of_measurement=POWER_WATT,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_GRID_CHARGE_CUTOFF_STATE_OF_CHARGE,
        min_value=30,
        max_value=70,
        name="Grid Charge Cutoff SOC",
        icon="mdi:battery-charging-50",
        unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_POWER_OF_CHARGE_FROM_GRID,
        min_value=0,
        maximum_key=rn.STORAGE_MAXIMUM_POWER_OF_CHARGE_FROM_GRID,
        name="Grid Charge Maximum Power",
        icon="mdi:battery-negative",
        unit_of_measurement=POWER_WATT,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Huawei Solar Number entities Setup."""

    update_coordinators = hass.data[DOMAIN][entry.entry_id][
        DATA_UPDATE_COORDINATORS
    ]  # type: list[HuaweiSolarUpdateCoordinator]

    entities_to_add: list[NumberEntity] = []

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

            for entity_description in ENERGY_STORAGE_NUMBER_DESCRIPTIONS:
                entities_to_add.append(
                    await HuaweiSolarNumberEntity.create(
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


class HuaweiSolarNumberEntity(NumberEntity):
    """Huawei Solar Number Entity."""

    def __init__(
        self,
        bridge: HuaweiSolarBridge,
        description: HuaweiSolarNumberEntityDescription,
        device_info: DeviceInfo,
        initial_value: float,
    ) -> None:
        """Huawei Solar Number Entity constructor.

        Do not use directly. Use `.create` instead!
        """
        self.bridge = bridge
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{bridge.serial_number}_{description.key}"
        self._attr_value = initial_value

    @classmethod
    async def create(
        cls,
        bridge: HuaweiSolarBridge,
        description: HuaweiSolarNumberEntityDescription,
        device_info: DeviceInfo,
    ):
        """Huawei Solar Number Entity constructor.

        This async constructor fills in the necessary min/max values
        """
        if description.minimum_key:
            description.min_value = (
                await bridge.client.get(description.minimum_key)
            ).value

        if description.maximum_key:
            description.max_value = (
                await bridge.client.get(description.maximum_key)
            ).value

        # Assumption: these values are not updated outside of HA.
        # This should hold true as they typically can only be set via the Modbus-interface,
        # which only allows one client at a time.
        initial_value = (await bridge.client.get(description.key)).value

        return cls(bridge, description, device_info, initial_value)

    async def async_set_value(self, value: float) -> None:
        """Set a new value."""
        if await self.bridge.set(self.entity_description.key, int(value)):
            self._attr_value = int(value)
