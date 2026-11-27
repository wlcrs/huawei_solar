"""Switch entities for Huawei Solar."""

import logging
from dataclasses import dataclass
from enum import IntEnum
from itertools import chain
from typing import cast, overload, override

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import ChildDeviceInfo, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from huawei_solar import (
    EMMADevice,
    HuaweiSolarDevice,
    RegisterName,
    SmartAcGunDevice,
    SUN2000Device,
)
from huawei_solar import (
    register_names as rn,
)
from huawei_solar import (
    register_values as rv,
)
from huawei_solar.register_definitions.number import NumberRegister
from huawei_solar.registers import REGISTERS

from .const import CONF_ENABLE_PARAMETER_CONFIGURATION
from .types import (
    HuaweiSolarConfigEntry,
    HuaweiSolarCoordinatorEntity,
    HuaweiSolarDeviceData,
    HuaweiSolarEntityDescription,
    HuaweiSolarInverterData,
)
from .update_coordinator import HuaweiSolarUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


@dataclass(frozen=True)
class HuaweiSolarSelectEntityDescription(
    HuaweiSolarEntityDescription, SelectEntityDescription
):
    """Huawei Solar Select Entity Description."""


ENERGY_STORAGE_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSelectEntityDescription, ...] = (
    HuaweiSolarSelectEntityDescription(
        key=rn.STORAGE_EXCESS_PV_ENERGY_USE_IN_TOU,
        entity_category=EntityCategory.CONFIG,
    ),
)

CAPACITY_CONTROL_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSelectEntityDescription, ...] = (
    HuaweiSolarSelectEntityDescription(
        key=rn.STORAGE_CAPACITY_CONTROL_MODE,
        entity_category=EntityCategory.CONFIG,
        # Active capacity control is only available is 'Charge from grid' is enabled
        is_available_key=rn.STORAGE_CHARGE_FROM_GRID_FUNCTION,
        check_is_available_func=lambda charge_from_grid: charge_from_grid,
    ),
)

BACKUP_VOLTAGE_INDEPENDENT_OPERATION_SELECT_DESCRIPTION = (
    HuaweiSolarSelectEntityDescription(
        key=rn.BACKUP_VOLTAGE_INDEPENDENT_OPERATION,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    )
)
"""In FusionSolar: Settings > Feature parameters > Voltage in independent operation."""

ACTIVE_POWER_LIMITATION_MODE_SELECT_DESCRIPTION = (
    HuaweiSolarSelectEntityDescription(
        key=rn.ACTIVE_POWER_LIMITATION_MODE,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    )
)
"""In FusionSolar: Settings > Power adjustment > Active power control > Grid-tied point control > Limitation mode."""

EMMA_BATTERY_SELECT_DESCRIPTIONS: tuple[HuaweiSolarSelectEntityDescription, ...] = (
    HuaweiSolarSelectEntityDescription(
        key=rn.EMMA_ESS_CONTROL_MODE,
        entity_category=EntityCategory.CONFIG,
        options=[
            mode.name.lower()
            for mode in rv.EmmaEssControlMode
            if mode not in (
                rv.EmmaEssControlMode.RESERVED_1,
                rv.EmmaEssControlMode.RESERVED_3,
            )
        ],
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
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarSelectEntityDescription(
        key=rn.CHARGER_GUN_LOCK_CONTROL_MODE,
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

    device_datas: list[HuaweiSolarDeviceData] = entry.runtime_data
    has_inverter_battery = any(
        isinstance(dd, HuaweiSolarInverterData)
        and dd.device.battery_type != rv.StorageProductModel.NONE
        for dd in device_datas
    )

    entities_to_add: list[SelectEntity] = []
    for ucs in device_datas:
        if not ucs.configuration_update_coordinator:
            continue

        slave_entities: list[HuaweiSolarSelectEntity] = []
        if isinstance(ucs.device, EMMADevice):
            if (
                ucs.device.battery_type != rv.StorageProductModel.NONE
                or has_inverter_battery
            ):
                for entity_description in EMMA_BATTERY_SELECT_DESCRIPTIONS:
                    slave_entities.append(  # noqa: PERF401
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
                        ucs.device.battery_type,
                        (
                            swm
                            for swm in rv.StorageWorkingModesC
                            if swm != rv.StorageWorkingModesC.THIRD_PARTY_CONTROL
                        ),
                    )
                )
                if ucs.device.supports_third_party_control:
                    available_modes.append(rv.StorageWorkingModesC.THIRD_PARTY_CONTROL)

                slave_entities.append(
                    HuaweiSolarSelectEntity(
                        ucs.configuration_update_coordinator,
                        ucs.device,
                        HuaweiSolarSelectEntityDescription(
                            key=rn.STORAGE_WORKING_MODE_SETTINGS,
                            entity_category=EntityCategory.CONFIG,
                        ),
                        ucs.connected_energy_storage,
                        options=[mode.name.lower() for mode in available_modes],
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


class HuaweiSolarSelectEntity(HuaweiSolarCoordinatorEntity, SelectEntity):
    """Huawei Solar Select Entity."""

    entity_description: HuaweiSolarSelectEntityDescription

    @overload
    def _friendly_format(self, value: None) -> None: ...

    @overload
    def _friendly_format(self, value: IntEnum) -> str: ...

    def _friendly_format(self, value: IntEnum | None) -> str | None:
        if value is None:
            return None
        return value.name.lower()

    def _to_enum(self, value: str) -> IntEnum:
        return cast(IntEnum, getattr(self._register_unit, value.upper()))

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        device: HuaweiSolarDevice,
        description: HuaweiSolarSelectEntityDescription,
        device_info: DeviceInfo | ChildDeviceInfo,
        *,
        options: list[str] | None = None,
    ) -> None:
        """Huawei Solar Select Entity constructor."""
        super().__init__(coordinator, description.context)

        self.device = device
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_{description.key}"

        register = REGISTERS[description.register_name]

        assert isinstance(register, NumberRegister)
        assert isinstance(register.unit, type) and issubclass(register.unit, IntEnum)

        self._register_unit: type[IntEnum] = register.unit

        self._attr_current_option = None
        if options is None:
            options = description.options
        self._attr_options = (
            options
            if options is not None
            else [self._friendly_format(value) for value in self._register_unit]
        )

    @callback
    @override
    def _async_update_attrs(self) -> None:
        """Update entity attributes from coordinator data."""
        if (
            self.coordinator.data
            and self.entity_description.key in self.coordinator.data
            and self.coordinator.data[self.entity_description.register_name].value
            is not None
        ):
            self._attr_current_option = self._friendly_format(
                self.coordinator.data[self.entity_description.register_name].value
            )

            self._attr_available = self._is_available_from_description(
                self.entity_description
            )
        else:
            self._attr_current_option = None
            self._attr_available = False

    @override
    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self._async_set_register(
            self.entity_description.register_name, self._to_enum(option)
        )
        self._attr_current_option = option

        await self.coordinator.async_request_refresh()


def get_select_registers(device: HuaweiSolarDevice) -> set[RegisterName]:
    """Get registers needed for select entities."""
    descriptions: list[HuaweiSolarSelectEntityDescription] = []
    extra_registers: set[RegisterName] = set()

    if isinstance(device, EMMADevice):
        descriptions.extend(EMMA_BATTERY_SELECT_DESCRIPTIONS)
        if device.supports_capacity_control:
            descriptions.extend(EMMA_CAPACITY_CONTROL_SELECT_DESCRIPTIONS)
    elif isinstance(device, SmartAcGunDevice):
        descriptions.extend(SMART_AC_GUN_SELECT_DESCRIPTIONS)
    elif isinstance(device, SUN2000Device):
        if device.supports_backup_voltage:
            descriptions.append(
                BACKUP_VOLTAGE_INDEPENDENT_OPERATION_SELECT_DESCRIPTION
            )
        if device.supports_active_power_limitation_mode:
            descriptions.append(ACTIVE_POWER_LIMITATION_MODE_SELECT_DESCRIPTION)
        if device.battery_type != rv.StorageProductModel.NONE:
            if device.battery_type == rv.StorageProductModel.HUAWEI_LUNA2000:
                descriptions.extend(ENERGY_STORAGE_SWITCH_DESCRIPTIONS)
            extra_registers.add(rn.STORAGE_WORKING_MODE_SETTINGS)
            if device.supports_capacity_control:
                descriptions.extend(CAPACITY_CONTROL_SWITCH_DESCRIPTIONS)

    registers = set(
        chain.from_iterable(
            desc.context["register_names"]
            for desc in descriptions
            if desc.entity_registry_enabled_default
        )
    )
    registers.update(extra_registers)
    return registers
