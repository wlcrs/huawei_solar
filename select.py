"""Switch entities for Huawei Solar."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
import logging
from typing import Any, TypeVar, cast

from huawei_solar import (
    EMMADevice,
    HuaweiSolarDevice,
    SChargerDevice,
    SmartAcGunDevice,
    SUN2000Device,
    register_names as rn,
    register_values as rv,
)
from huawei_solar.register_definitions.number import NumberRegister
from huawei_solar.registers import REGISTERS

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import ChildDeviceInfo, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ENABLE_PARAMETER_CONFIGURATION, DATA_DEVICE_DATAS
from .types import (
    HuaweiSolarConfigEntry,
    HuaweiSolarDeviceData,
    HuaweiSolarEntity,
    HuaweiSolarEntityContext,
    HuaweiSolarEntityDescription,
    HuaweiSolarInverterData,
)
from .update_coordinator import HuaweiSolarUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


T = TypeVar("T")


@dataclass(frozen=True)
class HuaweiSolarSelectEntityDescription[T](
    HuaweiSolarEntityDescription, SelectEntityDescription
):
    """Huawei Solar Select Entity Description."""

    is_available_key: rn.RegisterName | None = None
    check_is_available_func: Callable[[Any], bool] | None = None

    def __post_init__(self) -> None:
        """Defaults the translation_key to the select key."""

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
        if self.is_available_key:
            registers.append(self.is_available_key)

        return {"register_names": registers}


ENERGY_STORAGE_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSelectEntityDescription, ...] = (
    HuaweiSolarSelectEntityDescription(
        key=rn.STORAGE_EXCESS_PV_ENERGY_USE_IN_TOU,
        icon="mdi:battery-charging-medium",
        entity_category=EntityCategory.CONFIG,
    ),
)

CAPACITY_CONTROL_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSelectEntityDescription, ...] = (
    HuaweiSolarSelectEntityDescription(
        key=rn.STORAGE_CAPACITY_CONTROL_MODE,
        icon="mdi:battery-arrow-up",
        entity_category=EntityCategory.CONFIG,
        # Active capacity control is only available is 'Charge from grid' is enabled
        is_available_key=rn.STORAGE_CHARGE_FROM_GRID_FUNCTION,
        check_is_available_func=lambda charge_from_grid: charge_from_grid,
    ),
)

BACKUP_VOLTAGE_INDEPENDENT_OPERATION_SELECT_DESCRIPTION = (
    HuaweiSolarSelectEntityDescription(
        key=rn.BACKUP_VOLTAGE_INDEPENDENT_OPERATION,
        icon="mdi:transmission-tower",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    )
)
"""In FusionSolar: Settings > Feature parameters > Voltage in independent operation."""

ACTIVE_POWER_LIMITATION_MODE_SELECT_DESCRIPTION = (
    HuaweiSolarSelectEntityDescription(
        key=rn.ACTIVE_POWER_LIMITATION_MODE,
        icon="mdi:transmission-tower-export",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    )
)
"""In FusionSolar: Settings > Power adjustment > Active power control > Grid-tied point control > Limitation mode."""

EMMA_BATTERY_SELECT_DESCRIPTIONS: tuple[HuaweiSolarSelectEntityDescription, ...] = (
    HuaweiSolarSelectEntityDescription(
        key=rn.EMMA_ESS_CONTROL_MODE,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarSelectEntityDescription(
        key=rn.EMMA_TOU_PREFERRED_USE_OF_SURPLUS_PV_POWER,
        entity_category=EntityCategory.CONFIG,
    ),
)

EMMA_CAPACITY_CONTROL_SELECT_DESCRIPTIONS: tuple[
    HuaweiSolarSelectEntityDescription, ...
] = (
    HuaweiSolarSelectEntityDescription(
        key=rn.EMMA_CAPACITY_CONTROL_MODE,
        icon="mdi:battery-arrow-up",
        entity_category=EntityCategory.CONFIG,
        # Capacity control is not available in 'Fully fed to grid' mode
        is_available_key=rn.EMMA_ESS_CONTROL_MODE,
        check_is_available_func=lambda mode: (
            mode is not None and mode != rv.EmmaEssControlMode.FULLY_FED_TO_GRID
        ),
    ),
)

SMART_AC_GUN_SELECT_DESCRIPTIONS: tuple[HuaweiSolarSelectEntityDescription, ...] = (
    HuaweiSolarSelectEntityDescription(
        key=rn.CHARGER_GUN_WORK_MODE,
        icon="mdi:solar-power",
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarSelectEntityDescription(
        key=rn.CHARGER_GUN_LOCK_CONTROL_MODE,
        icon="mdi:lock-cog",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HuaweiSolarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Huawei Solar Select Entities Setup."""
    if not entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION, False):
        _LOGGER.info("Skipping select setup, as parameter configuration is not enabled")
        return

    device_datas: list[HuaweiSolarDeviceData] = entry.runtime_data[DATA_DEVICE_DATAS]
    has_inverter_battery = any(
        isinstance(dd, HuaweiSolarInverterData)
        and dd.device.battery_type != rv.StorageProductModel.NONE
        for dd in device_datas
    )

    entities_to_add: list[SelectEntity] = []
    for ucs in device_datas:
        if not ucs.configuration_update_coordinator:
            continue

        slave_entities: list[HuaweiSolarSelectEntity | StorageModeSelectEntity] = []
        if isinstance(ucs.device, EMMADevice):
            if ucs.device.has_battery or has_inverter_battery:
                for entity_description in EMMA_BATTERY_SELECT_DESCRIPTIONS:
                    slave_entities.append( 
                        HuaweiSolarSelectEntity(
                            ucs.configuration_update_coordinator,
                            ucs.device,
                            entity_description,
                            ucs.device_info,
                        )
                    )
            else:
                _LOGGER.debug(
                    "No battery detected for EMMA %s. Skipping EMMA battery select entities",
                    ucs.device.serial_number,
                )

            if ucs.device.supports_capacity_control:
                _LOGGER.debug(
                    "Adding capacity control select entities for EMMA %s",
                    ucs.device.serial_number,
                )
                slave_entities.extend(
                    HuaweiSolarSelectEntity(
                        ucs.configuration_update_coordinator,
                        ucs.device,
                        entity_description,
                        ucs.device_info,
                    )
                    for entity_description in EMMA_CAPACITY_CONTROL_SELECT_DESCRIPTIONS
                )
            else:
                _LOGGER.debug(
                    "Capacity control is not supported by EMMA %s",
                    ucs.device.serial_number,
                )

        if isinstance(ucs.device, SmartAcGunDevice):
            slave_entities.extend(
                HuaweiSolarSelectEntity(
                    ucs.configuration_update_coordinator,
                    ucs.device,
                    entity_description,
                    ucs.device_info,
                )
                for entity_description in SMART_AC_GUN_SELECT_DESCRIPTIONS
            )

        if isinstance(ucs, HuaweiSolarInverterData):
            if ucs.device.supports_backup_voltage:
                slave_entities.append(
                    HuaweiSolarSelectEntity(
                        ucs.configuration_update_coordinator,
                        ucs.device,
                        BACKUP_VOLTAGE_INDEPENDENT_OPERATION_SELECT_DESCRIPTION,
                        ucs.device_info,
                    )
                )

            if ucs.device.supports_active_power_limitation_mode:
                slave_entities.append(
                    HuaweiSolarSelectEntity(
                        ucs.configuration_update_coordinator,
                        ucs.device,
                        ACTIVE_POWER_LIMITATION_MODE_SELECT_DESCRIPTION,
                        ucs.device_info,
                    )
                )

            if ucs.connected_energy_storage:
                if ucs.device.battery_type == rv.StorageProductModel.HUAWEI_LUNA2000:
                    slave_entities.extend(
                        HuaweiSolarSelectEntity(
                            ucs.configuration_update_coordinator,
                            ucs.device,
                            entity_description,
                            ucs.connected_energy_storage,
                        )
                        for entity_description in ENERGY_STORAGE_SWITCH_DESCRIPTIONS
                    )
                slave_entities.append(
                    StorageModeSelectEntity(
                        ucs.configuration_update_coordinator,
                        ucs.device,
                        ucs.connected_energy_storage,
                    )
                )
                if ucs.device.supports_capacity_control:
                    _LOGGER.debug(
                        "Adding capacity control switch entities for %s",
                        ucs.device.serial_number,
                    )
                    slave_entities.extend(
                        HuaweiSolarSelectEntity(
                            ucs.configuration_update_coordinator,
                            ucs.device,
                            entity_description,
                            ucs.connected_energy_storage,
                        )
                        for entity_description in CAPACITY_CONTROL_SWITCH_DESCRIPTIONS
                    )
                else:
                    _LOGGER.debug(
                        "Storage capacity control is not supported by inverter %s",
                        ucs.device.serial_number,
                    )

        entities_to_add.extend(slave_entities)

    async_add_entities(entities_to_add)


class HuaweiSolarSelectEntity(
    CoordinatorEntity[HuaweiSolarUpdateCoordinator], HuaweiSolarEntity, SelectEntity
):
    """Huawei Solar Select Entity."""

    entity_description: HuaweiSolarSelectEntityDescription

    def _friendly_format(self, value: IntEnum) -> str:
        return value.name.lower()

    def _to_enum(self, value: str) -> IntEnum:
        return cast(IntEnum, getattr(self._register_unit, value.upper()))

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        device: HuaweiSolarDevice,
        description: HuaweiSolarSelectEntityDescription,
        device_info: DeviceInfo | ChildDeviceInfo,
    ) -> None:
        """Huawei Solar Select Entity constructor."""
        super().__init__(coordinator, description.context)
        self.coordinator = coordinator

        self.device = device
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_{description.key}"

        register = REGISTERS[description.register_name]

        assert isinstance(register, NumberRegister)
        assert isinstance(register.unit, type) and issubclass(register.unit, IntEnum)

        self._register_unit: type[IntEnum] = register.unit

        self._attr_current_option = None
        self._attr_options = [
            self._friendly_format(value) for value in self._register_unit
        ]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.data
            and self.entity_description.key in self.coordinator.data
        ):
            self._attr_current_option = self._friendly_format(
                self.coordinator.data[self.entity_description.register_name].value
            )

            if self.entity_description.check_is_available_func:
                assert self.entity_description.is_available_key
                is_available_register = self.coordinator.data[
                    self.entity_description.is_available_key
                ]
                self._attr_available = self.entity_description.check_is_available_func(
                    is_available_register.value if is_available_register else None
                )
            else:
                self._attr_available = True
        else:
            self._attr_current_option = None
            self._attr_available = False

        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self.device.set(
            self.entity_description.register_name, self._to_enum(option)
        )
        self._attr_current_option = option

        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        """Is the entity available.

        Override available property (from CoordinatorEntity) to take into
        account the custom check_is_available_func result.
        """
        available = super().available

        if self.entity_description.check_is_available_func and available:
            return self._attr_available

        return available


class StorageModeSelectEntity(
    CoordinatorEntity[HuaweiSolarUpdateCoordinator], HuaweiSolarEntity, SelectEntity
):
    """Huawei Solar Storage Mode Select Entity.

    The available options depend on the type of battery used, so it needs
    separate logic.
    """

    entity_description: HuaweiSolarSelectEntityDescription

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        device: SUN2000Device,
        device_info: DeviceInfo,
    ) -> None:
        """Huawei Solar Storage Mode Select Entity constructor.

        Do not use directly. Use `.create` instead!
        """
        super().__init__(
            coordinator, {"register_names": [rn.STORAGE_WORKING_MODE_SETTINGS]}
        )
        self.coordinator = coordinator

        self.device = device
        self.entity_description = HuaweiSolarSelectEntityDescription(
            key=rn.STORAGE_WORKING_MODE_SETTINGS,
            entity_category=EntityCategory.CONFIG,
        )
        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_{self.entity_description.key}"

        self._attr_current_option = None
        # The options depend on the type of battery and feature mask 30283
        battery_working_modes: dict[
            rv.StorageProductModel, tuple[rv.StorageWorkingModesC, ...]
        ] = {
            rv.StorageProductModel.HUAWEI_LUNA2000: (
                rv.StorageWorkingModesC.MAXIMISE_SELF_CONSUMPTION,
                rv.StorageWorkingModesC.FULLY_FED_TO_GRID,
                rv.StorageWorkingModesC.TIME_OF_USE_LUNA2000,
            ),
            rv.StorageProductModel.LG_RESU: (
                rv.StorageWorkingModesC.FIXED_CHARGE_DISCHARGE,
                rv.StorageWorkingModesC.MAXIMISE_SELF_CONSUMPTION,
                rv.StorageWorkingModesC.TIME_OF_USE_LG,
            ),
        }
        available_modes = list(
            battery_working_modes.get(
                device.battery_type,
                (
                    swm
                    for swm in rv.StorageWorkingModesC
                    if swm != rv.StorageWorkingModesC.THIRD_PARTY_CONTROL
                ),
            )
        )
        if device.supports_third_party_control:
            available_modes.append(rv.StorageWorkingModesC.THIRD_PARTY_CONTROL)
        self._attr_options = [mode.name.lower() for mode in available_modes]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.data
            and self.entity_description.key in self.coordinator.data
        ):
            value = self.coordinator.data[
                self.entity_description.register_name
            ].value
            self._attr_current_option = (
                value.name.lower() if value is not None else None
            )
            self._attr_available = True
        else:
            self._attr_current_option = None
            self._attr_available = False
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self.device.set(
            rn.STORAGE_WORKING_MODE_SETTINGS,
            getattr(rv.StorageWorkingModesC, option.upper()),
        )
        self._attr_current_option = option

        await self.coordinator.async_request_refresh()
