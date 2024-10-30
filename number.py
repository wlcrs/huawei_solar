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
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from huawei_solar import (
    HuaweiEMMABridge,
    HuaweiSolarBridge,
    HuaweiSUN2000Bridge,
    register_names as rn,
    register_values as rv,
)

from . import HuaweiSolarEntity, HuaweiSolarUpdateCoordinators
from .const import CONF_ENABLE_PARAMETER_CONFIGURATION, DATA_UPDATE_COORDINATORS, DOMAIN
from .update_coordinator import HuaweiSolarUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
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
        # We use this special setter to be able to set/update the translation_key
        # in this frozen dataclass.
        # cfr. https://docs.python.org/3/library/dataclasses.html#frozen-instances
        object.__setattr__(
            self,
            "translation_key",
            self.translation_key or self.key.replace("#", "_").lower(),
        )

    @property
    def context(self):
        """Context used by DataUpdateCoordinator."""

        registers = [self.key]
        if self.dynamic_minimum_key:
            registers.append(self.dynamic_minimum_key)
        if self.dynamic_maximum_key:
            registers.append(self.dynamic_maximum_key)
        return {"register_names": registers}


INVERTER_NUMBER_DESCRIPTIONS: tuple[HuaweiSolarNumberEntityDescription, ...] = (
    HuaweiSolarNumberEntityDescription(
        key=rn.ACTIVE_POWER_PERCENTAGE_DERATING,
        native_max_value=100,
        native_step=0.1,
        native_min_value=-100,
        icon="mdi:transmission-tower-off",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.ACTIVE_POWER_FIXED_VALUE_DERATING,
        static_maximum_key=rn.P_MAX,
        native_step=1,
        native_min_value=0,
        icon="mdi:transmission-tower-off",
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.MPPT_SCANNING_INTERVAL,
        native_max_value=30,
        native_step=1,
        native_min_value=5,
        icon="mdi:sun-clock",
        native_unit_of_measurement="minutes",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
)

EMMA_NUMBER_DESCRIPTIONS: tuple[HuaweiSolarNumberEntityDescription, ...] = (
    HuaweiSolarNumberEntityDescription(
        key=rn.EMMA_MAXIMUM_FEED_GRID_POWER_PERCENT,
        native_max_value=100,
        native_step=0.1,
        native_min_value=-100,
        icon="mdi:transmission-tower-off",
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.EMMA_MAXIMUM_FEED_GRID_POWER_WATT,
        native_step=1,
        native_min_value=0,
        icon="mdi:transmission-tower-off",
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.CONFIG,
    ),
)

ENERGY_STORAGE_NUMBER_DESCRIPTIONS: tuple[HuaweiSolarNumberEntityDescription, ...] = (
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_MAXIMUM_CHARGING_POWER,
        native_min_value=0,
        static_maximum_key=rn.STORAGE_MAXIMUM_CHARGE_POWER,
        icon="mdi:battery-positive",
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_MAXIMUM_DISCHARGING_POWER,
        native_min_value=0,
        static_maximum_key=rn.STORAGE_MAXIMUM_DISCHARGE_POWER,
        icon="mdi:battery-negative",
        native_unit_of_measurement=UnitOfPower.WATT,
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
        native_unit_of_measurement=UnitOfPower.WATT,
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

    update_coordinators: list[HuaweiSolarUpdateCoordinators] = hass.data[DOMAIN][
        entry.entry_id
    ][DATA_UPDATE_COORDINATORS]

    entities_to_add: list[NumberEntity] = []
    for ucs in update_coordinators:
        if not ucs.configuration_update_coordinator:
            continue
        slave_entities: list[HuaweiSolarNumberEntity] = []
        if ucs.device_infos["emma"]:
            assert isinstance(ucs.bridge, HuaweiEMMABridge)
            for entity_description in EMMA_NUMBER_DESCRIPTIONS:
                slave_entities.append(  # noqa: PERF401
                    await HuaweiSolarNumberEntity.create(
                        ucs.configuration_update_coordinator,
                        ucs.bridge,
                        entity_description,
                        ucs.device_infos["emma"],
                    )
                )

        if ucs.device_infos["inverter"]:
            assert isinstance(ucs.bridge, HuaweiSUN2000Bridge)
            for entity_description in INVERTER_NUMBER_DESCRIPTIONS:
                slave_entities.append(  # noqa: PERF401
                    await HuaweiSolarNumberEntity.create(
                        ucs.configuration_update_coordinator,
                        ucs.bridge,
                        entity_description,
                        ucs.device_infos["inverter"],
                    )
                )

        if ucs.device_infos["connected_energy_storage"]:
            assert isinstance(ucs.bridge, HuaweiSUN2000Bridge)
            for entity_description in ENERGY_STORAGE_NUMBER_DESCRIPTIONS:
                slave_entities.append(  # noqa: PERF401
                    await HuaweiSolarNumberEntity.create(
                        ucs.configuration_update_coordinator,
                        ucs.bridge,
                        entity_description,
                        ucs.device_infos["connected_energy_storage"],
                    )
                )

            if ucs.bridge.supports_capacity_control:
                _LOGGER.debug(
                    "Adding capacity control number entities on slave %s",
                    ucs.bridge.serial_number,
                )
                for entity_description in CAPACITY_CONTROL_NUMBER_DESCRIPTIONS:
                    slave_entities.append(  # noqa: PERF401
                        await HuaweiSolarNumberEntity.create(
                            ucs.configuration_update_coordinator,
                            ucs.bridge,
                            entity_description,
                            ucs.device_infos["connected_energy_storage"],
                        )
                    )
            else:
                _LOGGER.debug(
                    "Capacity control not supported on slave %s. Skipping capacity control number entities",
                    ucs.bridge.serial_number,
                )

        else:
            _LOGGER.debug(
                "No battery detected on slave %s. Skipping energy storage number entities",
                ucs.bridge.slave_id,
            )

        entities_to_add.extend(slave_entities)

    async_add_entities(entities_to_add)


class HuaweiSolarNumberEntity(CoordinatorEntity, HuaweiSolarEntity, NumberEntity):
    """Huawei Solar Number Entity."""

    entity_description: HuaweiSolarNumberEntityDescription
    _attr_mode = NumberMode.BOX  # Always allow a precise number

    _static_min_value: float | None = None
    _static_max_value: float | None = None

    _dynamic_min_value: float | None = None
    _dynamic_max_value: float | None = None

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        bridge: HuaweiSolarBridge,
        description: HuaweiSolarNumberEntityDescription,
        device_info: DeviceInfo,
        static_max_value: float | None = None,
        static_min_value: float | None = None,
    ) -> None:
        """Huawei Solar Number Entity constructor.

        Do not use directly. Use `.create` instead!
        """
        super().__init__(coordinator, description.context)
        self.coordinator = coordinator

        self.bridge = bridge
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{bridge.serial_number}_{description.key}"

        self._static_max_value = static_max_value
        self._static_min_value = static_min_value

    @classmethod
    async def create(
        cls,
        coordinator: HuaweiSolarUpdateCoordinator,
        bridge: HuaweiSolarBridge,
        description: HuaweiSolarNumberEntityDescription,
        device_info: DeviceInfo,
    ) -> HuaweiSolarNumberEntity:
        """Huawei Solar Number Entity constructor.

        This async constructor fills in the necessary min/max values
        """

        static_max_value = None
        if description.static_maximum_key:
            static_max_value = (
                await bridge.client.get(description.static_maximum_key, bridge.slave_id)
            ).value

        static_min_value = None
        if description.static_minimum_key:
            static_min_value = (
                await bridge.client.get(description.static_minimum_key, bridge.slave_id)
            ).value

        return cls(
            coordinator,
            bridge,
            description,
            device_info,
            static_max_value,
            static_min_value,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.data
            and self.entity_description.key in self.coordinator.data
        ):
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
        else:
            self._attr_available = False
            self._attr_native_value = None

        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Set a new value."""
        if await self.bridge.set(self.entity_description.key, float(value)):
            self._attr_native_value = float(value)

        await self.coordinator.async_request_refresh()

    @property
    def native_max_value(self) -> float:
        """Maximum value, possibly determined dynamically using _dynamic_max_value."""
        native_max_value = (
            self._static_max_value or self.entity_description.native_max_value
        )

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
        native_min_value = (
            self._static_min_value or self.entity_description.native_min_value
        )

        if self._dynamic_min_value:
            if native_min_value:
                return max(self._dynamic_min_value, native_min_value)
            return self._dynamic_min_value

        if native_min_value:
            return native_min_value
        return DEFAULT_MIN_VALUE
