"""Switch entities for Huawei Solar."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from itertools import chain
import logging
from typing import Any, TypeVar

from huawei_solar import (
    HuaweiSolarDevice,
    HuaweiSolarException,
    RegisterName,
    SChargerDevice,
    SmartAcGunDevice,
    SUN2000Device,
    register_names as rn,
    register_values as rv,
)

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENABLE_PARAMETER_CONFIGURATION, DATA_DEVICE_DATAS
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


T = TypeVar("T")


@dataclass(frozen=True)
class HuaweiSolarSwitchEntityDescription[T](
    HuaweiSolarEntityDescription, SwitchEntityDescription
):
    """Huawei Solar Switch Entity Description."""

    is_available_key: rn.RegisterName | None = None
    check_is_available_func: Callable[[Any], bool] | None = None

    def __post_init__(self) -> None:
        """Defaults the translation_key to the switch key."""

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


ENERGY_STORAGE_WITH_CAPACITY_CONTROL_SWITCH_DESCRIPTIONS: tuple[
    HuaweiSolarSwitchEntityDescription, ...
] = (
    HuaweiSolarSwitchEntityDescription(
        key=rn.STORAGE_CHARGE_FROM_GRID_FUNCTION,
        icon="mdi:battery-charging-50",
        entity_category=EntityCategory.CONFIG,
        is_available_key=rn.STORAGE_CAPACITY_CONTROL_MODE,
        check_is_available_func=(
            lambda ccm: ccm != rv.StorageCapacityControlMode.ACTIVE_CAPACITY_CONTROL
        ),
    ),
)

ENERGY_STORAGE_WITHOUT_CAPACITY_CONTROL_SWITCH_DESCRIPTIONS: tuple[
    HuaweiSolarSwitchEntityDescription, ...
] = (
    HuaweiSolarSwitchEntityDescription(
        key=rn.STORAGE_CHARGE_FROM_GRID_FUNCTION,
        icon="mdi:battery-charging-50",
        entity_category=EntityCategory.CONFIG,
    ),
)

ENERGY_STORAGE_ESS_LOW_POWER_SWITCH_DESCRIPTION = (
    HuaweiSolarSwitchEntityDescription(
        key=rn.STORAGE_ESS_LOW_POWER,
        icon="mdi:battery-saver",
        entity_category=EntityCategory.CONFIG,
    )
)

BACKUP_SWITCH_TO_OFF_GRID_SWITCH_DESCRIPTION = HuaweiSolarSwitchEntityDescription(
    key=rn.BACKUP_SWITCH_TO_OFF_GRID,
    icon="mdi:transmission-tower-off",
    entity_category=EntityCategory.CONFIG,
    entity_registry_enabled_default=False,
)
"""In FusionSolar: Settings > Feature parameters > Off-grid mode / Switch to off-grid."""

INVERTER_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSwitchEntityDescription, ...] = (
    HuaweiSolarSwitchEntityDescription(
        key=rn.MPPT_MULTIMODAL_SCANNING,
        icon="mdi:magnify-scan",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
)

CHARGER_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSwitchEntityDescription, ...] = (
    HuaweiSolarSwitchEntityDescription(
        key=rn.CHARGER_RANDOM_DELAY_CHARGING,
        icon="mdi:timer-sand",
        entity_category=EntityCategory.CONFIG,
    ),
)

SMART_AC_GUN_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSwitchEntityDescription, ...] = (
    HuaweiSolarSwitchEntityDescription(
        key=rn.CHARGER_SINGLE_THREE_PHASE_SWITCH,
        icon="mdi:numeric-3-box-multiple",
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarSwitchEntityDescription(
        key=rn.CHARGER_DYNAMIC_POWER_CONTROL,
        icon="mdi:flash-auto",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HuaweiSolarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Huawei Solar Switch Entities Setup."""
    if not entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION, False):
        _LOGGER.info("Skipping switch setup, as parameter configuration is not enabled")
        return

    device_data: list[HuaweiSolarDeviceData] = entry.runtime_data[DATA_DEVICE_DATAS]

    entities_to_add: list[SwitchEntity] = []
    for ucs in device_data:
        if not ucs.configuration_update_coordinator:
            continue

        slave_entities: list[
            HuaweiSolarSwitchEntity | HuaweiSolarOnOffSwitchEntity
        ] = []

        if isinstance(ucs, HuaweiSolarInverterData):
            # This entity dependens on DEVICE_STATUS which is already read by the inverter_update_coordinator
            slave_entities.append(
                HuaweiSolarOnOffSwitchEntity(
                    ucs.update_coordinator, ucs.device, ucs.device_info
                )
            )

            slave_entities.extend(
                [
                    HuaweiSolarSwitchEntity(
                        ucs.update_coordinator,
                        ucs.device,
                        entity_description,
                        ucs.device_info,
                    )
                    for entity_description in INVERTER_SWITCH_DESCRIPTIONS
                ]
            )

            if ucs.device.supports_off_grid_switch:
                slave_entities.append(
                    HuaweiSolarSwitchEntity(
                        ucs.configuration_update_coordinator,
                        ucs.device,
                        BACKUP_SWITCH_TO_OFF_GRID_SWITCH_DESCRIPTION,
                        ucs.device_info,
                    )
                )

            if ucs.connected_energy_storage:
                if ucs.device.supports_capacity_control:
                    slave_entities.extend(
                        HuaweiSolarSwitchEntity(
                            ucs.configuration_update_coordinator,
                            ucs.device,
                            entity_description,
                            ucs.connected_energy_storage,
                        )
                        for entity_description in ENERGY_STORAGE_WITH_CAPACITY_CONTROL_SWITCH_DESCRIPTIONS
                    )
                else:
                    slave_entities.extend(
                        HuaweiSolarSwitchEntity(
                            ucs.configuration_update_coordinator,
                            ucs.device,
                            entity_description,
                            ucs.connected_energy_storage,
                        )
                        for entity_description in ENERGY_STORAGE_WITHOUT_CAPACITY_CONTROL_SWITCH_DESCRIPTIONS
                    )

                if ucs.device.supports_ess_low_power:
                    slave_entities.append(
                        HuaweiSolarSwitchEntity(
                            ucs.configuration_update_coordinator,
                            ucs.device,
                            ENERGY_STORAGE_ESS_LOW_POWER_SWITCH_DESCRIPTION,
                            ucs.connected_energy_storage,
                        )
                    )

        if isinstance(ucs.device, SChargerDevice):
            slave_entities.extend(
                HuaweiSolarSwitchEntity(
                    ucs.configuration_update_coordinator,
                    ucs.device,
                    entity_description,
                    ucs.device_info,
                )
                for entity_description in CHARGER_SWITCH_DESCRIPTIONS
            )

        if isinstance(ucs.device, SmartAcGunDevice):
            slave_entities.extend(
                HuaweiSolarSwitchEntity(
                    ucs.configuration_update_coordinator,
                    ucs.device,
                    entity_description,
                    ucs.device_info,
                )
                for entity_description in SMART_AC_GUN_SWITCH_DESCRIPTIONS
            )

        entities_to_add.extend(slave_entities)

    async_add_entities(entities_to_add)


DEVICE_STATUS_OFF_RANGE_START = 0x3000
DEVICE_STATUS_OFF_RANGE_END = 0x3FFF


class HuaweiSolarSwitchEntity(HuaweiSolarCoordinatorEntity, SwitchEntity):
    """Huawei Solar Switch Entity."""

    entity_description: HuaweiSolarSwitchEntityDescription

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        device: HuaweiSolarDevice,
        description: HuaweiSolarSwitchEntityDescription,
        device_info: DeviceInfo,
    ) -> None:
        """Huawei Solar Switch Entity constructor.

        Do not use directly. Use `.create` instead!
        """
        super().__init__(coordinator, description.context)
        self.coordinator = coordinator

        self.device = device
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_{description.key}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.data
            and self.entity_description.key in self.coordinator.data
        ):
            self._attr_is_on = self.coordinator.data[
                self.entity_description.register_name
            ].value

            if self.entity_description.check_is_available_func:
                assert self.entity_description.is_available_key
                is_available_register = self.coordinator.data.get(
                    self.entity_description.is_available_key
                )
                self._attr_available = self.entity_description.check_is_available_func(
                    is_available_register.value if is_available_register else None
                )
            else:
                self._attr_available = True
        else:
            self._attr_is_on = None
            self._attr_available = False

        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        if await self.device.set(self.entity_description.register_name, True):
            self._attr_is_on = True

        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        if await self.device.set(self.entity_description.register_name, False):
            self._attr_is_on = False

        await self.coordinator.async_request_refresh()


class HuaweiSolarOnOffSwitchEntity(HuaweiSolarCoordinatorEntity, SwitchEntity):
    """Huawei Solar Switch Entity."""

    POLL_FREQUENCY_SECONDS = 15
    MAX_STATUS_CHANGE_TIME_SECONDS = 300  # Maximum status change time is 5 minutes

    def __init__(
        self,
        # not the HuaweiSolarConfigurationUpdateCoordinator as
        # this entity depends on the 'Device Status' register
        coordinator: HuaweiSolarUpdateCoordinator,
        device: HuaweiSolarDevice,
        device_info: DeviceInfo,
    ) -> None:
        """Huawei Solar Switch Entity constructor.

        Do not use directly. Use `.create` instead!
        """
        super().__init__(coordinator, {"register_names": [rn.DEVICE_STATUS]})
        self.coordinator = coordinator

        self.device = device
        self.entity_description = SwitchEntityDescription(
            key=rn.STARTUP,
            icon="mdi:power-standby",
            entity_category=EntityCategory.CONFIG,
        )

        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_{self.entity_description.key}"

        self._change_lock = asyncio.Lock()

    @staticmethod
    def _is_off(device_status: str) -> bool:
        return device_status.startswith("Shutdown")

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._change_lock.locked():
            return  # Don't do status updates if async_turn_on or async_turn_off is running

        if self.coordinator.data and rn.DEVICE_STATUS in self.coordinator.data:
            device_status = self.coordinator.data[rn.DEVICE_STATUS].value

            self._attr_is_on = not self._is_off(device_status)
            self._attr_available = True
        else:
            self._attr_available = False

        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        async with self._change_lock:
            await self.device.set(rn.STARTUP, 0)

            # Turning on can take up to 5 minutes... We'll poll every 15 seconds
            for _ in range(
                self.MAX_STATUS_CHANGE_TIME_SECONDS // self.POLL_FREQUENCY_SECONDS
            ):
                await asyncio.sleep(self.POLL_FREQUENCY_SECONDS)
                try:
                    result = await self.device.get(rn.DEVICE_STATUS)
                    device_status = result.value
                except HuaweiSolarException:
                    continue

                if not self._is_off(device_status):
                    self._attr_is_on = True
                    self.async_write_ha_state()
                    break

        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        async with self._change_lock:
            await self.device.set(rn.SHUTDOWN, 0)

            # Turning off can take up to 5 minutes... We'll poll every 15 seconds
            for _ in range(
                self.MAX_STATUS_CHANGE_TIME_SECONDS // self.POLL_FREQUENCY_SECONDS
            ):
                await asyncio.sleep(self.POLL_FREQUENCY_SECONDS)
                try:
                    result = await self.device.get(rn.DEVICE_STATUS)
                    device_status = result.value
                except HuaweiSolarException:
                    continue

                if self._is_off(device_status):
                    self._attr_is_on = False
                    self.async_write_ha_state()
                    break

        await self.coordinator.async_request_refresh()


def get_inverter_switch_registers() -> set[RegisterName]:
    """Get registers needed for inverter update coordinator from switch platform."""
    registers = {rn.DEVICE_STATUS}
    registers.update(
        chain.from_iterable(
            desc.context["register_names"] for desc in INVERTER_SWITCH_DESCRIPTIONS
        )
    )
    return registers


def get_switch_registers(device: HuaweiSolarDevice) -> set[RegisterName]:
    """Get registers needed for configuration update coordinator from switch platform."""
    descriptions: list[HuaweiSolarSwitchEntityDescription] = []
    if isinstance(device, SUN2000Device):
        if device.supports_off_grid_switch:
            descriptions.append(BACKUP_SWITCH_TO_OFF_GRID_SWITCH_DESCRIPTION)
        if device.battery_type != rv.StorageProductModel.NONE:
            if device.supports_capacity_control:
                descriptions.extend(
                    ENERGY_STORAGE_WITH_CAPACITY_CONTROL_SWITCH_DESCRIPTIONS
                )
            else:
                descriptions.extend(
                    ENERGY_STORAGE_WITHOUT_CAPACITY_CONTROL_SWITCH_DESCRIPTIONS
                )
            if device.supports_ess_low_power:
                descriptions.append(
                    ENERGY_STORAGE_ESS_LOW_POWER_SWITCH_DESCRIPTION
                )
    elif isinstance(device, SChargerDevice):
        descriptions.extend(CHARGER_SWITCH_DESCRIPTIONS)
    elif isinstance(device, SmartAcGunDevice):
        descriptions.extend(SMART_AC_GUN_SWITCH_DESCRIPTIONS)

    return set(
        chain.from_iterable(desc.context["register_names"] for desc in descriptions)
    )
