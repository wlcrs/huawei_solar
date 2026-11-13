"""Number entities for Huawei Solar."""

from dataclasses import dataclass
from itertools import chain
import logging

from huawei_solar import (
    EMMADevice,
    HuaweiSolarDevice,
    RegisterName,
    SChargerDevice,
    SmartAcGunDevice,
    SUN2000Device,
    register_names as rn,
    register_values as rv,
)

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.components.number.const import DEFAULT_MAX_VALUE, DEFAULT_MIN_VALUE
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENABLE_PARAMETER_CONFIGURATION
from .types import (
    HuaweiSolarConfigEntry,
    HuaweiSolarCoordinatorEntity,
    HuaweiSolarDeviceData,
    HuaweiSolarEntityContext,
    HuaweiSolarEntityDescription,
    HuaweiSolarInverterData,
)
from .update_coordinator import HuaweiSolarUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


@dataclass(frozen=True)
class HuaweiSolarNumberEntityDescription(
    HuaweiSolarEntityDescription, NumberEntityDescription
):
    """Huawei Solar Number Entity Description."""

    minimum_key: RegisterName | None = None
    maximum_key: RegisterName | None = None

    def __post_init__(self) -> None:
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
    def context(self) -> HuaweiSolarEntityContext:
        """Context used by DataUpdateCoordinator."""

        registers = [self.register_name]
        if self.minimum_key:
            registers.append(self.minimum_key)
        if self.maximum_key:
            registers.append(self.maximum_key)
        return HuaweiSolarEntityContext(register_names=registers)


ACTIVE_POWER_FAIL_SAFE_THRESHOLD_NUMBER_DESCRIPTION = HuaweiSolarNumberEntityDescription(
    key=rn.ACTIVE_POWER_FAIL_SAFE_THRESHOLD,
    native_min_value=0,
    native_max_value=100,
    native_step=0.1,
    native_unit_of_measurement=PERCENTAGE,
    entity_category=EntityCategory.CONFIG,
    entity_registry_enabled_default=False,
)
"""In FusionSolar: Settings > Power adjustment > Active power control > Active power threshold when communication fails."""


INVERTER_NUMBER_DESCRIPTIONS: tuple[HuaweiSolarNumberEntityDescription, ...] = (
    HuaweiSolarNumberEntityDescription(
        key=rn.ACTIVE_POWER_PERCENTAGE_DERATING,
        native_max_value=100,
        native_step=0.1,
        native_min_value=-100,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.ACTIVE_POWER_FIXED_VALUE_DERATING,
        maximum_key=rn.P_MAX,
        native_step=1,
        native_min_value=0,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.MPPT_SCANNING_INTERVAL,
        native_max_value=30,
        native_step=1,
        native_min_value=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
)


DONGLE_PLANT_MAXIMUM_CHARGE_FROM_GRID_POWER_NUMBER_DESCRIPTION = HuaweiSolarNumberEntityDescription(
    key=rn.DONGLE_PLANT_MAXIMUM_CHARGE_FROM_GRID_POWER,
    native_min_value=0,
    native_unit_of_measurement=UnitOfPower.WATT,
    entity_category=EntityCategory.CONFIG,
    entity_registry_enabled_default=False,
)
"""In FusionSolar: Settings > Power adjustment > Battery control > Maximum charge power of grid."""


STORAGE_MAXIMUM_GRID_POWER_DURING_DISCHARGE_NUMBER_DESCRIPTION = HuaweiSolarNumberEntityDescription(
    key=rn.STORAGE_MAXIMUM_GRID_POWER_DURING_DISCHARGE,
    native_min_value=0,
    native_max_value=1000,
    native_step=1,
    native_unit_of_measurement=UnitOfPower.WATT,
    entity_category=EntityCategory.CONFIG,
    entity_registry_enabled_default=False,
)
"""In FusionSolar: Settings > Power adjustment > Battery control > Maximum grid power during battery discharge."""


STORAGE_ADJUSTMENT_DEADBAND_NUMBER_DESCRIPTION = HuaweiSolarNumberEntityDescription(
    key=rn.STORAGE_ADJUSTMENT_DEADBAND,
    native_min_value=0,
    native_max_value=100,
    native_step=1,
    native_unit_of_measurement=UnitOfPower.WATT,
    entity_category=EntityCategory.CONFIG,
    entity_registry_enabled_default=False,
)
"""In FusionSolar: Settings > Power adjustment > Battery control > Power control hysteresis."""


EMMA_NUMBER_DESCRIPTIONS: tuple[HuaweiSolarNumberEntityDescription, ...] = (
    HuaweiSolarNumberEntityDescription(
        key=rn.EMMA_MAXIMUM_FEED_GRID_POWER_PERCENT,
        native_max_value=100,
        native_step=0.1,
        native_min_value=-100,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.EMMA_MAXIMUM_FEED_GRID_POWER_WATT,
        native_max_value=50000,
        native_step=1,
        native_min_value=-1000,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.EMMA_TOU_MAXIMUM_POWER_FOR_CHARGING_BATTERIES_FROM_GRID,
        native_min_value=0,
        native_max_value=50000,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.CONFIG,
    ),
)

ENERGY_STORAGE_NUMBER_DESCRIPTIONS: tuple[HuaweiSolarNumberEntityDescription, ...] = (
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_MAXIMUM_CHARGING_POWER,
        native_min_value=0,
        maximum_key=rn.STORAGE_MAXIMUM_CHARGE_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_MAXIMUM_DISCHARGING_POWER,
        native_min_value=0,
        maximum_key=rn.STORAGE_MAXIMUM_DISCHARGE_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_CHARGING_CUTOFF_CAPACITY,
        native_min_value=90,
        native_max_value=100,
        native_step=0.1,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_BACKUP_POWER_STATE_OF_CHARGE,
        native_min_value=0,
        native_max_value=100,
        native_step=0.1,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_GRID_CHARGE_CUTOFF_STATE_OF_CHARGE,
        native_min_value=20,
        native_max_value=100,
        native_step=0.1,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_POWER_OF_CHARGE_FROM_GRID,
        native_min_value=0,
        maximum_key=rn.STORAGE_MAXIMUM_POWER_OF_CHARGE_FROM_GRID,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.CONFIG,
    ),
)

CAPACITY_CONTROL_NUMBER_DESCRIPTIONS: tuple[HuaweiSolarNumberEntityDescription, ...] = (
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_CAPACITY_CONTROL_SOC_PEAK_SHAVING,
        minimum_key=rn.STORAGE_DISCHARGING_CUTOFF_CAPACITY,
        native_max_value=100,
        native_step=0.1,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
    ),
    # this entity has a dynamic maximum value which is only available when capacity control is supported
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_DISCHARGING_CUTOFF_CAPACITY,
        native_min_value=0,
        native_max_value=20,
        maximum_key=rn.STORAGE_CAPACITY_CONTROL_SOC_PEAK_SHAVING,
        native_step=0.1,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
    ),
)


NON_CAPACITY_CONTROL_NUMBER_DESCRIPTIONS: tuple[
    HuaweiSolarNumberEntityDescription, ...
] = (
    # this entity is identical to the one above, but without dynamic maximum.
    HuaweiSolarNumberEntityDescription(
        key=rn.STORAGE_DISCHARGING_CUTOFF_CAPACITY,
        native_min_value=0,
        native_max_value=20,
        native_step=0.1,
        native_unit_of_measurement=PERCENTAGE,
        entity_category=EntityCategory.CONFIG,
    ),
)


CHARGER_NUMBER_DESCRIPTIONS: tuple[HuaweiSolarNumberEntityDescription, ...] = (
    HuaweiSolarNumberEntityDescription(
        key=rn.CHARGER_DYNAMIC_POWER_THRESHOLD,
        minimum_key=rn.CHARGER_MIN_CHARGING_POWER,
        maximum_key=rn.CHARGER_MAX_FIXED_POWER,
        native_step=0.1,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.CHARGER_ORDERLY_CHARGING_POWER,
        minimum_key=rn.CHARGER_MIN_CHARGING_POWER,
        maximum_key=rn.CHARGER_MAX_CHARGING_POWER,
        native_step=0.1,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        entity_category=EntityCategory.CONFIG,
    ),
)


SMART_AC_GUN_NUMBER_DESCRIPTIONS: tuple[HuaweiSolarNumberEntityDescription, ...] = (
    HuaweiSolarNumberEntityDescription(
        key=rn.CHARGER_GUN_MAX_CURRENT,
        native_min_value=6.0,
        native_max_value=32.0,
        maximum_key=rn.CHARGER_CABLE_MAX_CURRENT,
        native_step=0.1,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.CHARGER_MAX_POWER_FROM_GRID,
        native_min_value=0.0,
        native_max_value=22.0,
        native_step=0.1,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarNumberEntityDescription(
        key=rn.CHARGER_SURPLUS_POWER_START_THRESHOLD,
        native_min_value=0.0,
        native_max_value=22.0,
        native_step=0.1,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HuaweiSolarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Huawei Solar Number entities Setup."""
    if not entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION):
        _LOGGER.info("Skipping number setup, as parameter configuration is not enabled")
        return

    device_datas: list[HuaweiSolarDeviceData] = entry.runtime_data

    entities_to_add: list[NumberEntity] = []
    for ucs in device_datas:
        if not ucs.configuration_update_coordinator:
            continue
        slave_entities: list[HuaweiSolarNumberEntity] = []
        if isinstance(ucs.device, EMMADevice):
            for entity_description in EMMA_NUMBER_DESCRIPTIONS:
                slave_entities.append(
                    HuaweiSolarNumberEntity(
                        ucs.configuration_update_coordinator,
                        ucs.device,
                        entity_description,
                        ucs.device_info,
                    )
                )

        if isinstance(ucs.device, SChargerDevice):
            for entity_description in CHARGER_NUMBER_DESCRIPTIONS:
                slave_entities.append(
                    HuaweiSolarNumberEntity(
                        ucs.configuration_update_coordinator,
                        ucs.device,
                        entity_description,
                        ucs.device_info,
                    )
                )

        if isinstance(ucs.device, SmartAcGunDevice):
            for entity_description in SMART_AC_GUN_NUMBER_DESCRIPTIONS:
                slave_entities.append(
                    HuaweiSolarNumberEntity(
                        ucs.configuration_update_coordinator,
                        ucs.device,
                        entity_description,
                        ucs.device_info,
                    )
                )

        if isinstance(ucs, HuaweiSolarInverterData):
            for entity_description in INVERTER_NUMBER_DESCRIPTIONS:
                slave_entities.append(
                    HuaweiSolarNumberEntity(
                        ucs.configuration_update_coordinator,
                        ucs.device,
                        entity_description,
                        ucs.device_info,
                    )
                )

            if ucs.device.supports_active_power_fail_safe:
                slave_entities.append(
                    HuaweiSolarNumberEntity(
                        ucs.configuration_update_coordinator,
                        ucs.device,
                        ACTIVE_POWER_FAIL_SAFE_THRESHOLD_NUMBER_DESCRIPTION,
                        ucs.device_info,
                    )
                )

            if ucs.connected_energy_storage:
                for entity_description in ENERGY_STORAGE_NUMBER_DESCRIPTIONS:
                    slave_entities.append(
                        HuaweiSolarNumberEntity(
                            ucs.configuration_update_coordinator,
                            ucs.device,
                            entity_description,
                            ucs.device_info,
                        )
                    )

                if ucs.device.supports_dongle_charge_power_limit:
                    slave_entities.append(
                        HuaweiSolarNumberEntity(
                            ucs.configuration_update_coordinator,
                            ucs.device,
                            DONGLE_PLANT_MAXIMUM_CHARGE_FROM_GRID_POWER_NUMBER_DESCRIPTION,
                            ucs.device_info,
                        )
                    )

                if ucs.device.supports_discharge_power_adjustment:
                    slave_entities.append(
                        HuaweiSolarNumberEntity(
                            ucs.configuration_update_coordinator,
                            ucs.device,
                            STORAGE_MAXIMUM_GRID_POWER_DURING_DISCHARGE_NUMBER_DESCRIPTION,
                            ucs.device_info,
                        )
                    )
                    slave_entities.append(
                        HuaweiSolarNumberEntity(
                            ucs.configuration_update_coordinator,
                            ucs.device,
                            STORAGE_ADJUSTMENT_DEADBAND_NUMBER_DESCRIPTION,
                            ucs.device_info,
                        )
                    )

                if ucs.device.supports_capacity_control:
                    _LOGGER.debug(
                        "Adding capacity control number entities on device %s",
                        ucs.device.serial_number,
                    )
                    for entity_description in CAPACITY_CONTROL_NUMBER_DESCRIPTIONS:
                        slave_entities.append(
                            HuaweiSolarNumberEntity(
                                ucs.configuration_update_coordinator,
                                ucs.device,
                                entity_description,
                                ucs.connected_energy_storage,
                            )
                        )

                else:
                    _LOGGER.debug(
                        "Capacity control not supported on slave %s. Skipping capacity control number entities",
                        ucs.device.serial_number,
                    )
                    for entity_description in NON_CAPACITY_CONTROL_NUMBER_DESCRIPTIONS:
                        slave_entities.append(
                            HuaweiSolarNumberEntity(
                                ucs.configuration_update_coordinator,
                                ucs.device,
                                entity_description,
                                ucs.connected_energy_storage,
                            )
                        )

        else:
            _LOGGER.debug(
                "No battery detected on slave %s. Skipping energy storage number entities",
                ucs.device.client.unit_id,
            )

        entities_to_add.extend(slave_entities)

    async_add_entities(entities_to_add)


class HuaweiSolarNumberEntity(HuaweiSolarCoordinatorEntity, NumberEntity):
    """Huawei Solar Number Entity."""

    entity_description: HuaweiSolarNumberEntityDescription
    _attr_mode = NumberMode.BOX  # Always allow a precise number

    _minimum_value: float | None = None
    _maximum_value: float | None = None

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        device: HuaweiSolarDevice,
        description: HuaweiSolarNumberEntityDescription,
        device_info: DeviceInfo,
    ) -> None:
        """Huawei Solar Number Entity constructor."""
        super().__init__(coordinator, description.context)
        self.coordinator = coordinator

        self.device = device
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_{description.key}"

    @classmethod
    async def create(
        cls,
        coordinator: HuaweiSolarUpdateCoordinator,
        device: HuaweiSolarDevice,
        description: HuaweiSolarNumberEntityDescription,
        device_info: DeviceInfo,
    ) -> "HuaweiSolarNumberEntity":
        """Huawei Solar Number Entity constructor."""
        return cls(coordinator, device, description, device_info)

    @callback
    def _async_update_attrs(self) -> None:
        """Update entity attributes from coordinator data."""
        if (
            self.coordinator.data
            and self.entity_description.key in self.coordinator.data
        ):
            self._attr_native_value = self.coordinator.data[
                self.entity_description.register_name
            ].value

            if self.entity_description.minimum_key:
                min_register = self.coordinator.data.get(
                    self.entity_description.minimum_key
                )
                if min_register is not None and min_register.value is not None:
                    self._minimum_value = min_register.value

            if self.entity_description.maximum_key:
                max_register = self.coordinator.data.get(
                    self.entity_description.maximum_key
                )
                if max_register is not None and max_register.value is not None:
                    self._maximum_value = max_register.value

            self._attr_available = True
        else:
            self._attr_available = False
            self._attr_native_value = None

    async def async_set_native_value(self, value: float) -> None:
        """Set a new value."""
        if await self._async_set_register(
            self.entity_description.register_name, float(value)
        ):
            self._attr_native_value = float(value)

        await self.coordinator.async_request_refresh()

    @property
    def native_max_value(self) -> float:
        """Maximum value, possibly determined dynamically using maximum_key."""
        if self._maximum_value is not None:
            if self.entity_description.native_max_value is not None:
                return min(self._maximum_value, self.entity_description.native_max_value)
            return self._maximum_value

        if self.entity_description.native_max_value is not None:
            return self.entity_description.native_max_value

        return DEFAULT_MAX_VALUE

    @property
    def native_min_value(self) -> float:
        """Minimum value, possibly determined dynamically using minimum_key."""
        if self._minimum_value is not None:
            if self.entity_description.native_min_value is not None:
                return max(self._minimum_value, self.entity_description.native_min_value)
            return self._minimum_value

        if self.entity_description.native_min_value is not None:
            return self.entity_description.native_min_value

        return DEFAULT_MIN_VALUE


def get_number_registers(device: HuaweiSolarDevice) -> set[RegisterName]:
    """Get registers needed for number entities."""
    descriptions: list[HuaweiSolarNumberEntityDescription] = []
    if isinstance(device, EMMADevice):
        descriptions.extend(EMMA_NUMBER_DESCRIPTIONS)
    elif isinstance(device, SChargerDevice):
        descriptions.extend(CHARGER_NUMBER_DESCRIPTIONS)
    elif isinstance(device, SmartAcGunDevice):
        descriptions.extend(SMART_AC_GUN_NUMBER_DESCRIPTIONS)
    elif isinstance(device, SUN2000Device):
        descriptions.extend(INVERTER_NUMBER_DESCRIPTIONS)
        if device.supports_active_power_fail_safe:
            descriptions.append(ACTIVE_POWER_FAIL_SAFE_THRESHOLD_NUMBER_DESCRIPTION)
        if device.battery_type != rv.StorageProductModel.NONE:
            descriptions.extend(ENERGY_STORAGE_NUMBER_DESCRIPTIONS)
            if device.supports_dongle_charge_power_limit:
                descriptions.append(
                    DONGLE_PLANT_MAXIMUM_CHARGE_FROM_GRID_POWER_NUMBER_DESCRIPTION
                )
            if device.supports_discharge_power_adjustment:
                descriptions.append(
                    STORAGE_MAXIMUM_GRID_POWER_DURING_DISCHARGE_NUMBER_DESCRIPTION
                )
                descriptions.append(
                    STORAGE_ADJUSTMENT_DEADBAND_NUMBER_DESCRIPTION
                )
            if device.supports_capacity_control:
                descriptions.extend(CAPACITY_CONTROL_NUMBER_DESCRIPTIONS)
            else:
                descriptions.extend(NON_CAPACITY_CONTROL_NUMBER_DESCRIPTIONS)

    return set(
        chain.from_iterable(desc.context["register_names"] for desc in descriptions)
    )
