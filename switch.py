"""Switch entities for Huawei Solar."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from itertools import chain
from typing import Any, override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import ChildDeviceInfo, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from huawei_solar import (
    HuaweiSolarDevice,
    RegisterName,
    SChargerDevice,
    SmartAcGunDevice,
    SmartGuardDevice,
    SmartLoadDevice,
    SUN2000Device,
)
from huawei_solar import (
    register_names as rn,
)
from huawei_solar import (
    register_values as rv,
)

from .const import CONF_ENABLE_PARAMETER_CONFIGURATION, DOMAIN
from .types import (
    HuaweiSolarConfigEntry,
    HuaweiSolarCoordinatorEntity,
    HuaweiSolarDeviceData,
    HuaweiSolarEntityDescription,
    HuaweiSolarInverterData,
    async_call_with_device_error_handling,
)
from .update_coordinator import HuaweiSolarUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


@dataclass(frozen=True)
class HuaweiSolarSwitchEntityDescription(
    HuaweiSolarEntityDescription, SwitchEntityDescription
):
    """Huawei Solar Switch Entity Description."""


ENERGY_STORAGE_WITH_CAPACITY_CONTROL_SWITCH_DESCRIPTIONS: tuple[
    HuaweiSolarSwitchEntityDescription, ...
] = (
    HuaweiSolarSwitchEntityDescription(
        key=rn.STORAGE_CHARGE_FROM_GRID_FUNCTION,
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
        entity_category=EntityCategory.CONFIG,
    ),
)

ENERGY_STORAGE_ESS_LOW_POWER_SWITCH_DESCRIPTION = (
    HuaweiSolarSwitchEntityDescription(
        key=rn.STORAGE_ESS_LOW_POWER,
        entity_category=EntityCategory.CONFIG,
    )
)

BACKUP_SWITCH_TO_OFF_GRID_SWITCH_DESCRIPTION = HuaweiSolarSwitchEntityDescription(
    key=rn.BACKUP_SWITCH_TO_OFF_GRID,
    entity_category=EntityCategory.CONFIG,
    entity_registry_enabled_default=False,
)
"""In FusionSolar: Settings > Feature parameters > Off-grid mode / Switch to off-grid."""

INVERTER_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSwitchEntityDescription, ...] = (
    HuaweiSolarSwitchEntityDescription(
        key=rn.MPPT_MULTIMODAL_SCANNING,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
    ),
)

CHARGER_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSwitchEntityDescription, ...] = (
    HuaweiSolarSwitchEntityDescription(
        key=rn.CHARGER_RANDOM_DELAY_CHARGING,
        entity_category=EntityCategory.CONFIG,
    ),
)

SMART_AC_GUN_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSwitchEntityDescription, ...] = (
    HuaweiSolarSwitchEntityDescription(
        key=rn.CHARGER_SINGLE_THREE_PHASE_SWITCH,
        entity_category=EntityCategory.CONFIG,
    ),
    HuaweiSolarSwitchEntityDescription(
        key=rn.CHARGER_DYNAMIC_POWER_CONTROL,
        entity_category=EntityCategory.CONFIG,
    ),
)


SMARTLOAD_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarSwitchEntityDescription, ...] = (
    HuaweiSolarSwitchEntityDescription(
        key=rn.SMARTLOAD_OFF_GRID_AUTO_CONTROL,
        icon="mdi:transmission-tower-off",
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

    device_data: list[HuaweiSolarDeviceData] = entry.runtime_data

    entities_to_add: list[SwitchEntity] = []
    for ucs in device_data:
        if not ucs.configuration_update_coordinator:
            continue

        slave_entities: list[
            HuaweiSolarSwitchEntity
            | HuaweiSolarOnOffSwitchEntity
            | SmartGuardOffGridSwitchEntity
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
                        ucs.configuration_update_coordinator,
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

        if isinstance(ucs.device, SmartLoadDevice):
            slave_entities.extend(
                HuaweiSolarSwitchEntity(
                    ucs.configuration_update_coordinator,
                    ucs.device,
                    entity_description,
                    ucs.device_info,
                )
                for entity_description in SMARTLOAD_SWITCH_DESCRIPTIONS
            )

        if (
            isinstance(ucs.device, SmartGuardDevice)
            and ucs.device.supports_grid_switchover
        ):
            # Uses the update coordinator: the state comes from the SmartGuard status.
            slave_entities.append(
                SmartGuardOffGridSwitchEntity(
                    ucs.update_coordinator, ucs.device, ucs.device_info
                )
            )

        entities_to_add.extend(slave_entities)

    async_add_entities(entities_to_add)


# The on-grid command is also sent from these statuses: after an island has
# collapsed (inverter overload), the SmartGuard otherwise retries the commanded
# off-grid once the inverter recovers.
_ON_GRID_COMMAND_STATUSES = rv.SMARTGUARD_OFF_GRID_STATUSES | {
    rv.SmartGuardStatus.STANDBY,
    rv.SmartGuardStatus.UNEXPECTED_SHUTDOWN,
    rv.SmartGuardStatus.UNEXPECTED_SHUTDOWN_GRID_SUPPLY,
}


class SmartGuardOffGridSwitchEntity(HuaweiSolarCoordinatorEntity, SwitchEntity):
    """Switch that moves the SmartGuard's backup loads off the grid (on) or back (off).

    The state comes from the SmartGuard status: on while off-grid, off while on-grid
    and unknown in any other status. Like the FusionSolar app, the off-grid command is
    only sent from on-grid. The on-grid command is also sent from standby and the
    unexpected-shutdown statuses, and only while the grid voltage is present. Each
    command is confirmed by reading the status every second for up to 30 seconds;
    every status read is passed to the coordinator, so automations and the recorder
    see the statuses the SmartGuard goes through.
    """

    device: SmartGuardDevice

    POLL_INTERVAL_SECONDS = 1
    MAX_SWITCH_TIME_SECONDS = 30
    # Only detects a missing phase or an invalid reading; the SmartGuard checks the grid
    # quality itself.
    GRID_PRESENT_MIN_VOLTAGE = 100
    GRID_PRESENT_MAX_VOLTAGE = 300

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        device: SmartGuardDevice,
        device_info: DeviceInfo | ChildDeviceInfo,
    ) -> None:
        """Initialize the switch entity."""
        # Subscribing to the status keeps it polled even when the Status sensor is
        # disabled.
        super().__init__(coordinator, {"register_names": [rn.SMARTGUARD_STATUS]})
        self.device = device
        self.entity_description = SwitchEntityDescription(
            key="smartguard_off_grid",
            translation_key="smartguard_off_grid",
            entity_category=EntityCategory.CONFIG,
            # Moving the house onto the battery should be a deliberate choice.
            entity_registry_enabled_default=False,
        )
        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_{self.entity_description.key}"

    @staticmethod
    def _status_is_on(status: rv.SmartGuardStatus | None) -> bool | None:
        if status in rv.SMARTGUARD_OFF_GRID_STATUSES:
            return True
        if status == rv.SmartGuardStatus.ON_GRID:
            return False
        return None

    @callback
    @override
    def _async_update_attrs(self) -> None:
        """Update the state from the SmartGuard status."""
        result = (
            self.coordinator.data.get(rn.SMARTGUARD_STATUS)
            if self.coordinator.data
            else None
        )
        self._attr_is_on = self._status_is_on(result.value if result else None)

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Move the backup loads off the grid."""
        await self._switch(
            rv.SmartGuardGridSwitchover.OFF_GRID,
            allowed={rv.SmartGuardStatus.ON_GRID},
            expected=rv.SMARTGUARD_OFF_GRID_STATUSES,
        )

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Move the backup loads back onto the grid."""
        await self._switch(
            rv.SmartGuardGridSwitchover.ON_GRID,
            allowed=_ON_GRID_COMMAND_STATUSES,
            expected={rv.SmartGuardStatus.ON_GRID},
        )

    @override
    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle only from a known state.

        The default toggle turns on whenever the state is not on, which includes
        unknown: right after an island collapsed, that would send the SmartGuard back
        off-grid.
        """
        if self.is_on is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="smartguard_toggle_state_unknown",
            )
        await super().async_toggle(**kwargs)

    async def _switch(
        self,
        command: rv.SmartGuardGridSwitchover,
        allowed: set[rv.SmartGuardStatus] | frozenset[rv.SmartGuardStatus],
        expected: set[rv.SmartGuardStatus] | frozenset[rv.SmartGuardStatus],
    ) -> None:
        # PARALLEL_UPDATES = 1 already serialises the service calls of this platform.
        try:
            # Decide on a fresh reading, never on the coordinator's last good data.
            status = await self._read_status()
            if status in expected:
                return
            if status not in allowed:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="smartguard_switchover_not_allowed",
                    translation_placeholders={"status": _status_name(status)},
                )
            if command == rv.SmartGuardGridSwitchover.ON_GRID:
                await self._check_grid_present()

            # The write result is not checked: whether the command was executed is
            # decided by the status below.
            await self._async_set_register(rn.SMARTGUARD_GRID_SWITCHOVER, command)

            # A deadline rather than a count: a single read can take longer than the
            # poll interval.
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.MAX_SWITCH_TIME_SECONDS
            while loop.time() < deadline:
                await asyncio.sleep(self.POLL_INTERVAL_SECONDS)
                status = await self._read_status()
                if status in expected:
                    return

            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="smartguard_switchover_not_confirmed",
                translation_placeholders={
                    "seconds": str(self.MAX_SWITCH_TIME_SECONDS),
                    "status": _status_name(status),
                },
            )
        finally:
            await self.coordinator.async_request_refresh()

    async def _read_status(self) -> rv.SmartGuardStatus | None:
        """Read the SmartGuard status and pass it to the coordinator if it changed."""
        result = await async_call_with_device_error_handling(
            self.device.get(rn.SMARTGUARD_STATUS)
        )
        if not self.coordinator.data or result.value != getattr(
            self.coordinator.data.get(rn.SMARTGUARD_STATUS), "value", None
        ):
            self.coordinator.async_set_updated_data(
                {**(self.coordinator.data or {}), rn.SMARTGUARD_STATUS: result}
            )
        return result.value

    async def _check_grid_present(self) -> None:
        # Single-phase SmartGuards report the grid voltage in their own register
        # (30500, SMARTGUARD_GRID_VOLTAGE); 30501-30503 are the three-phase registers.
        # Only the three-phase registers were verified on hardware.
        if self.device.phase_type == rv.SmartGuardPhaseType.SINGLE_PHASE:
            register_names = [rn.SMARTGUARD_GRID_VOLTAGE]
        else:
            register_names = [
                rn.SMARTGUARD_GRID_PHASE_A_VOLTAGE,
                rn.SMARTGUARD_GRID_PHASE_B_VOLTAGE,
                rn.SMARTGUARD_GRID_PHASE_C_VOLTAGE,
            ]
        results = await async_call_with_device_error_handling(
            self.device.batch_update(register_names)
        )
        voltages = [results[register_name].value for register_name in register_names]
        if any(
            voltage is None
            or not self.GRID_PRESENT_MIN_VOLTAGE
            <= voltage
            <= self.GRID_PRESENT_MAX_VOLTAGE
            for voltage in voltages
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="smartguard_grid_not_present",
                translation_placeholders={
                    "voltages": "/".join(
                        "?" if voltage is None else f"{voltage:.0f}"
                        for voltage in voltages
                    )
                },
            )


def _status_name(status: rv.SmartGuardStatus | None) -> str:
    return status.name.lower() if status is not None else "unknown"


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
        device_info: DeviceInfo | ChildDeviceInfo,
    ) -> None:
        """Huawei Solar Switch Entity constructor."""
        super().__init__(coordinator, description.context)

        self.device = device
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_{description.key}"

    @callback
    @override
    def _async_update_attrs(self) -> None:
        """Update entity attributes from coordinator data."""
        if (
            self.coordinator.data
            and self.entity_description.key in self.coordinator.data
        ):
            self._attr_is_on = self.coordinator.data[
                self.entity_description.register_name
            ].value

            self._attr_available = self._is_available_from_description(
                self.entity_description
            )
        else:
            self._attr_is_on = None
            self._attr_available = False

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        if await self._async_set_register(self.entity_description.register_name, True):
            self._attr_is_on = True

        await self.coordinator.async_request_refresh()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        if await self._async_set_register(self.entity_description.register_name, False):
            self._attr_is_on = False

        await self.coordinator.async_request_refresh()


class HuaweiSolarOnOffSwitchEntity(HuaweiSolarCoordinatorEntity, SwitchEntity):
    """Huawei Solar Switch Entity."""

    MAX_STATUS_CHANGE_TIME_SECONDS = 300  # Maximum status change time is 5 minutes

    def __init__(
        self,
        # not the HuaweiSolarConfigurationUpdateCoordinator as
        # this entity depends on the 'Device Status' register
        coordinator: HuaweiSolarUpdateCoordinator,
        device: HuaweiSolarDevice,
        device_info: DeviceInfo | ChildDeviceInfo,
    ) -> None:
        """Huawei Solar Switch Entity constructor."""
        super().__init__(coordinator, {"register_names": [rn.DEVICE_STATUS]})

        self.device = device
        self.entity_description = SwitchEntityDescription(
            key=rn.STARTUP,
            translation_key=rn.STARTUP,
            entity_category=EntityCategory.CONFIG,
        )

        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_{self.entity_description.key}"

        self._pending_state: tuple[bool, float] | None = None

    @staticmethod
    def _is_off(device_status: str) -> bool:
        return device_status.startswith("Shutdown")

    @callback
    @override
    def _async_update_attrs(self) -> None:
        """Update entity attributes from coordinator data."""
        if (
            self.coordinator.data
            and rn.DEVICE_STATUS in self.coordinator.data
            and (device_status := self.coordinator.data[rn.DEVICE_STATUS].value)
            is not None
        ):
            actual_is_on = not self._is_off(device_status)

            if self._pending_state is not None:
                target_is_on, deadline = self._pending_state
                if actual_is_on == target_is_on or time.monotonic() >= deadline:
                    self._pending_state = None
                    self._attr_is_on = actual_is_on
                else:
                    self._attr_is_on = target_is_on
            else:
                self._attr_is_on = actual_is_on

            self._attr_available = True
        else:
            self._attr_available = False
            self._attr_is_on = None

    async def _async_set_power_state(
        self, target_is_on: bool, register: RegisterName
    ) -> None:
        """Send a startup or shutdown command with a non-blocking grace window."""
        if self._pending_state is not None:
            _, deadline = self._pending_state
            if time.monotonic() < deadline:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="inverter_status_change_in_progress",
                )
            self._pending_state = None

        await self._async_set_register(register, 0)
        self._pending_state = (
            target_is_on,
            time.monotonic() + self.MAX_STATUS_CHANGE_TIME_SECONDS,
        )
        self._attr_is_on = target_is_on
        self.async_write_ha_state()

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self._async_set_power_state(True, rn.STARTUP)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self._async_set_power_state(False, rn.SHUTDOWN)


def get_switch_registers(device: HuaweiSolarDevice) -> set[RegisterName]:
    """Get registers needed for configuration update coordinator from switch platform."""
    descriptions: list[HuaweiSolarSwitchEntityDescription] = []
    if isinstance(device, SUN2000Device):
        descriptions.extend(INVERTER_SWITCH_DESCRIPTIONS)
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
    elif isinstance(device, SmartLoadDevice):
        descriptions.extend(SMARTLOAD_SWITCH_DESCRIPTIONS)

    return set(
        chain.from_iterable(
            desc.context["register_names"]
            for desc in descriptions
            if desc.entity_registry_enabled_default
        )
    )
