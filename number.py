"""Number entities for Huawei Solar."""
from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.components.number.const import DEFAULT_MAX_VALUE, DEFAULT_MIN_VALUE
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, POWER_WATT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from huawei_solar import HuaweiSolarBridge, register_names as rn, register_values as rv

from . import HuaweiSolarConfigurationUpdateCoordinator, HuaweiSolarEntity
from .const import (
    CONF_ENABLE_PARAMETER_CONFIGURATION,
    DATA_CONFIGURATION_UPDATE_COORDINATORS,
    DATA_UPDATE_COORDINATORS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class HuaweiSolarNumberEntityDescription(NumberEntityDescription):
    """Huawei Solar Number Entity Description."""

    # Used when the min/max cannot dynamically change
    static_minimum_key: str | None = None
    static_maximum_key: str | None = None

    # Used when the min/max is influenced by other parameters
    dynamic_minimum_key: str | None = None
    dynamic_maximum_key: str | None = None

    def __post_init__(self):
        """Defaults the translation_key to the number key."""
        self.translation_key = self.translation_key or self.key.replace('#','_').lower()

ENERGY_STORAGE_NUMBER_DESCRIPTIONS: tuple[HuaweiSolarNumberEntityDescription, ...] = (
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_MAXIMUM_CHARGING_POWER,
        native_min_value=0,
        static_maximum_key=rn.STORAGE_MAXIMUM_CHARGE_POWER,
        icon="mdi:battery-positive",
        native_unit_of_measurement=POWER_WATT,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_MAXIMUM_DISCHARGING_POWER,
        native_min_value=0,
        static_maximum_key=rn.STORAGE_MAXIMUM_DISCHARGE_POWER,
        icon="mdi:battery-negative",
        native_unit_of_measurement=POWER_WATT,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_CHARGING_CUTOFF_CAPACITY,
        native_min_value=90,
        native_max_value=100,
        native_step=0.1,
        icon="mdi:battery-positive",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_DISCHARGING_CUTOFF_CAPACITY,
        native_min_value=0,
        native_max_value=20,
        dynamic_maximum_key=rn.STORAGE_CAPACITY_CONTROL_SOC_PEAK_SHAVING,
        native_step=0.1,
        icon="mdi:battery-negative",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_BACKUP_POWER_STATE_OF_CHARGE,
        native_min_value=0,
        native_max_value=100,
        native_step=0.1,
        icon="mdi:battery-negative",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_GRID_CHARGE_CUTOFF_STATE_OF_CHARGE,
        native_min_value=20,
        native_max_value=100,
        native_step=0.1,
        icon="mdi:battery-charging-50",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_POWER_OF_CHARGE_FROM_GRID,
        native_min_value=0,
        dynamic_maximum_key=rn.STORAGE_MAXIMUM_POWER_OF_CHARGE_FROM_GRID,
        icon="mdi:battery-negative",
        native_unit_of_measurement=POWER_WATT,
        entity_category=EntityCategory.CONFIG,
    ),
)
CAPACITY_CONTROL_NUMBER_DESCRIPTIONS: tuple[HuaweiSolarNumberEntityDescription, ...] = (
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_CAPACITY_CONTROL_SOC_PEAK_SHAVING,
        dynamic_minimum_key=rn.STORAGE_DISCHARGING_CUTOFF_CAPACITY,
        native_max_value=100,
        native_step=0.1,
        icon="mdi:battery-arrow-up",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Huawei Solar Number entities Setup."""

    if not entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION):
        _LOGGER.info("Skipping number setup, as parameter configuration is not enabled")
        return

    update_coordinators = hass.data[DOMAIN][entry.entry_id][
        DATA_UPDATE_COORDINATORS
    ]  # type: list[HuaweiSolarUpdateCoordinator]

    configuration_update_coordinators = hass.data[DOMAIN][entry.entry_id][
        DATA_CONFIGURATION_UPDATE_COORDINATORS
    ]  # type: list[HuaweiSolarConfigurationUpdateCoordinator]

    # When more than one inverter is present, then we suffix all sensors with '#1', '#2', ...
    # The order for these suffixes is the order in which the user entered the slave-ids.
    must_append_inverter_suffix = len(update_coordinators) > 1

    entities_to_add: list[NumberEntity] = []
    for idx, (update_coordinator, configuration_update_coordinator) in enumerate(
        zip(update_coordinators, configuration_update_coordinators)
    ):
        slave_entities: list[HuaweiSolarNumberEntity] = []
        bridge = update_coordinator.bridge
        device_infos = update_coordinator.device_infos

        if bridge.battery_type != rv.StorageProductModel.NONE:
            assert device_infos["connected_energy_storage"]

            for entity_description in ENERGY_STORAGE_NUMBER_DESCRIPTIONS:
                slave_entities.append(
                    await HuaweiSolarNumberEntity.create(
                        configuration_update_coordinator,
                        bridge,
                        entity_description,
                        device_infos["connected_energy_storage"],
                    )
                )

            if bridge.supports_capacity_control:
                for entity_description in CAPACITY_CONTROL_NUMBER_DESCRIPTIONS:
                    slave_entities.append(
                        await HuaweiSolarNumberEntity.create(
                            configuration_update_coordinator,
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

        # Add suffix if multiple inverters are present
        if must_append_inverter_suffix:
            for entity in slave_entities:
                entity.add_name_suffix(f" #{idx+1}")

        entities_to_add.extend(slave_entities)

    async_add_entities(entities_to_add)


class HuaweiSolarNumberEntity(CoordinatorEntity, HuaweiSolarEntity, NumberEntity):
    """Huawei Solar Number Entity."""

    entity_description: HuaweiSolarNumberEntityDescription

    def __init__(
        self,
        coordinator: HuaweiSolarConfigurationUpdateCoordinator,
        bridge: HuaweiSolarBridge,
        description: HuaweiSolarNumberEntityDescription,
        device_info: DeviceInfo,
    ) -> None:
        """Huawei Solar Number Entity constructor.

        Do not use directly. Use `.create` instead!
        """
        super().__init__(coordinator)
        self.coordinator = coordinator

        self.bridge = bridge
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{bridge.serial_number}_{description.key}"
        self._attr_mode = NumberMode.BOX  # Always allow a precise number

        self._dynamic_min_value: float | None = None
        self._dynamic_max_value: float | None = None

    @classmethod
    async def create(
        cls,
        coordinator: HuaweiSolarConfigurationUpdateCoordinator,
        bridge: HuaweiSolarBridge,
        description: HuaweiSolarNumberEntityDescription,
        device_info: DeviceInfo,
    ):
        """Huawei Solar Number Entity constructor.

        This async constructor fills in the necessary min/max values
        """
        if description.static_minimum_key:
            description.native_min_value = (
                await bridge.client.get(description.static_minimum_key, bridge.slave_id)
            ).value

        if description.static_maximum_key:
            description.native_max_value = (
                await bridge.client.get(description.static_maximum_key, bridge.slave_id)
            ).value

        return cls(coordinator, bridge, description, device_info)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self.coordinator.data[
            self.entity_description.key
        ].value

        if self.entity_description.dynamic_minimum_key:
            min_register = self.coordinator.data.get(
                self.entity_description.dynamic_minimum_key
            )

            if min_register:
                self._dynamic_min_value = min_register.value

        if self.entity_description.dynamic_maximum_key:
            max_register = self.coordinator.data.get(
                self.entity_description.dynamic_maximum_key
            )

            if max_register:
                self._dynamic_max_value = max_register.value

        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Set a new value."""
        if await self.bridge.set(self.entity_description.key, int(value)):
            self._attr_native_value = int(value)

        await self.coordinator.async_request_refresh()

    @property
    def native_max_value(self) -> float:
        """Maximum value, possibly determined dynamically using _dynamic_max_value."""
        native_max_value = self.entity_description.native_max_value

        if self._dynamic_max_value:
            if native_max_value:
                return min(self._dynamic_max_value, native_max_value)
            return self._dynamic_max_value

        if native_max_value:
            return native_max_value
        return DEFAULT_MAX_VALUE

    @property
    def native_min_value(self) -> float:
        """Minimum value, possibly determined dynamically using _dynamic_min_value."""
        native_min_value = self.entity_description.native_min_value

        if self._dynamic_min_value:
            if native_min_value:
                return max(self._dynamic_min_value, native_min_value)
            return self._dynamic_min_value

        if native_min_value:
            return native_min_value
        return DEFAULT_MIN_VALUE
