"""Switch entities for Huawei Solar."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any, Generic, TypeVar

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from huawei_solar import HuaweiSolarBridge, register_names as rn, register_values as rv

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
class HuaweiSolarSwitchEntityDescription(Generic[T], SwitchEntityDescription):
    """Huawei Solar Switch Entity Description."""

    is_available_key: str | None = None
    check_is_available_func: Callable[[Any], bool] | None = None

    def __post_init__(self):
        """Defaults the translation_key to the switch key."""
        self.translation_key = self.translation_key or self.key.replace('#','_').lower()

ENERGY_STORAGE_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSwitchEntityDescription, ...] = (
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Huawei Solar Switch Entities Setup."""

    if not entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION, False):
        _LOGGER.info("Skipping switch setup, as parameter configuration is not enabled")
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

    entities_to_add: list[SwitchEntity] = []
    for idx, (update_coordinator, configuration_update_coordinator) in enumerate(
        zip(update_coordinators, configuration_update_coordinators)
    ):
        slave_entities: list[
            HuaweiSolarSwitchEntity | HuaweiSolarOnOffSwitchEntity
        ] = []

        bridge = update_coordinator.bridge
        device_infos = update_coordinator.device_infos

        slave_entities.append(
            HuaweiSolarOnOffSwitchEntity(
                update_coordinator, bridge, device_infos["inverter"]
            )
        )

        if bridge.battery_type != rv.StorageProductModel.NONE:
            assert device_infos["connected_energy_storage"]

            for entity_description in ENERGY_STORAGE_SWITCH_DESCRIPTIONS:
                slave_entities.append(
                    HuaweiSolarSwitchEntity(
                        configuration_update_coordinator,
                        bridge,
                        entity_description,
                        device_infos["connected_energy_storage"],
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


DEVICE_STATUS_OFF_RANGE_START = 0x3000
DEVICE_STATUS_OFF_RANGE_END = 0x3FFF


class HuaweiSolarSwitchEntity(CoordinatorEntity, HuaweiSolarEntity, SwitchEntity):
    """Huawei Solar Switch Entity."""

    entity_description: HuaweiSolarSwitchEntityDescription

    def __init__(
        self,
        coordinator: HuaweiSolarConfigurationUpdateCoordinator,
        bridge: HuaweiSolarBridge,
        description: HuaweiSolarSwitchEntityDescription,
        device_info: DeviceInfo,
    ) -> None:
        """Huawei Solar Switch Entity constructor.

        Do not use directly. Use `.create` instead!
        """
        super().__init__(coordinator)
        self.coordinator = coordinator

        self.bridge = bridge
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{bridge.serial_number}_{description.key}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self.coordinator.data[self.entity_description.key].value

        if self.entity_description.check_is_available_func:
            is_available_register = self.coordinator.data.get(
                self.entity_description.is_available_key
            )
            self._attr_available = self.entity_description.check_is_available_func(
                is_available_register.value if is_available_register else None
            )

        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the setting on."""

        if await self.bridge.set(self.entity_description.key, True):
            self._attr_is_on = True

        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the setting off."""

        if await self.bridge.set(self.entity_description.key, False):
            self._attr_is_on = False

        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        """Override available property (from CoordinatorEntity) to take into account the custom check_is_available_func result."""
        available = super().available

        if self.entity_description.check_is_available_func and available:
            return self._attr_available

        return available


class HuaweiSolarOnOffSwitchEntity(CoordinatorEntity, HuaweiSolarEntity, SwitchEntity):
    """Huawei Solar Switch Entity."""

    POLL_FREQUENCY_SECONDS = 15
    MAX_STATUS_CHANGE_TIME_SECONDS = 3000  # Maximum status change time is 5 minutes

    def __init__(
        self,
        # not the HuaweiSolarConfigurationUpdateCoordinator as
        # this entity depends on the 'Device Status' register
        coordinator: HuaweiSolarUpdateCoordinator,
        bridge: HuaweiSolarBridge,
        device_info: DeviceInfo,
    ) -> None:
        """Huawei Solar Switch Entity constructor.

        Do not use directly. Use `.create` instead!
        """
        super().__init__(coordinator)
        self.coordinator = coordinator

        self.bridge = bridge
        self.entity_description = SwitchEntityDescription(
            rn.STARTUP,
            icon="mdi:power-standby",
            entity_category=EntityCategory.CONFIG,
        )

        self._attr_device_info = device_info
        self._attr_unique_id = f"{bridge.serial_number}_{self.entity_description.key}"

        self._change_lock = asyncio.Lock()

    @staticmethod
    def _is_off(device_status: str):
        return device_status.startswith("Shutdown")

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._change_lock.locked():
            return  # Don't do status updates if async_turn_on or async_turn_off is running

        device_status = self.coordinator.data[rn.DEVICE_STATUS].value

        self._attr_is_on = not self._is_off(device_status)
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the setting on."""
        async with self._change_lock:
            await self.bridge.set(rn.STARTUP, 0)

            # Turning on can take up to 5 minutes... We'll poll every 15 seconds
            for _ in range(
                self.MAX_STATUS_CHANGE_TIME_SECONDS // self.POLL_FREQUENCY_SECONDS
            ):
                await asyncio.sleep(self.POLL_FREQUENCY_SECONDS)
                device_status = (
                    await self.bridge.client.get(rn.DEVICE_STATUS, self.bridge.slave_id)
                ).value
                if not self._is_off(device_status):
                    self._attr_is_on = True
                    break

        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the setting off."""

        async with self._change_lock:
            await self.bridge.set(rn.SHUTDOWN, 0)

            # Turning on can take up to 5 minutes... We'll poll every 15 seconds
            for _ in range(
                self.MAX_STATUS_CHANGE_TIME_SECONDS // self.POLL_FREQUENCY_SECONDS
            ):
                await asyncio.sleep(self.POLL_FREQUENCY_SECONDS)
                device_status = (
                    await self.bridge.client.get(rn.DEVICE_STATUS, self.bridge.slave_id)
                ).value
                if self._is_off(device_status):
                    self._attr_is_on = False
                    break

        await self.coordinator.async_request_refresh()
