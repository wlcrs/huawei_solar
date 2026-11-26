"""Typing for the Huawei Solar integration."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypedDict, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import ChildDeviceInfo, DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from huawei_solar import (
    ConnectionInterruptedException,
    EncodeError,
    HuaweiSolarDevice,
    HuaweiSolarException,
    InvalidCredentials,
    PeakPeriodsValidationError,
    RegisterName,
    SUN2000Device,
    TimeOfUsePeriodsException,
)
from huawei_solar import (
    register_names as rn,
)
from huawei_solar import (
    register_values as rv,
)
from huawei_solar.modbus_pdu import PermissionDeniedError

from .const import DOMAIN
from .update_coordinator import (
    HuaweiSolarOptimizerUpdateCoordinator,
    HuaweiSolarUpdateCoordinator,
)


@dataclass(kw_only=True)
class HuaweiSolarDeviceData:
    """Runtime data for the Huawei Solar integration."""

    device: HuaweiSolarDevice
    ha_device_id: str
    device_info: DeviceInfo | ChildDeviceInfo
    update_coordinator: HuaweiSolarUpdateCoordinator
    configuration_update_coordinator: HuaweiSolarUpdateCoordinator | None
    has_write_permission: bool = False


@dataclass(kw_only=True)
class HuaweiSolarInverterData(HuaweiSolarDeviceData):
    """Runtime data for the Huawei Solar integration for SUN2000 inverter devices."""

    device: SUN2000Device

    power_meter: DeviceInfo | None
    connected_energy_storage: DeviceInfo | None
    battery_1: DeviceInfo | None
    battery_2: DeviceInfo | None
    optimizer_device_infos: dict[int, DeviceInfo] | None

    power_meter_update_coordinator: HuaweiSolarUpdateCoordinator | None
    energy_storage_update_coordinator: HuaweiSolarUpdateCoordinator | None
    optimizer_update_coordinator: HuaweiSolarOptimizerUpdateCoordinator | None


type HuaweiSolarConfigEntry = ConfigEntry[list[HuaweiSolarDeviceData]]


async def async_call_with_device_error_handling[T](coro: Awaitable[T]) -> T:
    """Await a device operation and translate library errors to HA errors."""
    try:
        return await coro
    except (
        TimeOfUsePeriodsException,
        PeakPeriodsValidationError,
        EncodeError,
    ) as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="invalid_device_value",
            translation_placeholders={
                "error": str(err) or type(err).__name__,
            },
        ) from err
    except PermissionDeniedError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="device_permission_denied",
        ) from err
    except InvalidCredentials as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="device_authentication_failed",
        ) from err
    except ConnectionInterruptedException as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="device_connection_interrupted",
        ) from err
    except TimeoutError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="device_timeout",
        ) from err
    except HuaweiSolarException as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="device_communication_error",
            translation_placeholders={
                "error": str(err) or type(err).__name__,
            },
        ) from err


class HuaweiSolarEntity(Entity):
    """Huawei Solar Entity."""

    _attr_has_entity_name = True
    device: HuaweiSolarDevice

    async def _async_set_register(self, register: RegisterName, value: Any) -> bool:
        """Write a register and translate device communication errors."""
        return await async_call_with_device_error_handling(
            self.device.set(register, value)
        )


class HuaweiSolarEntityContext(TypedDict):
    """Context for Huawei Solar Entities."""

    register_names: list[RegisterName]


@dataclass(frozen=True)
class HuaweiSolarEntityDescription(EntityDescription):
    """Huawei Solar Entity Description."""

    is_available_key: RegisterName | None = None
    check_is_available_func: Callable[[Any], bool] | None = None

    def __post_init__(self) -> None:
        """Defaults the translation_key to the entity key."""
        object.__setattr__(
            self,
            "translation_key",
            self.translation_key or self.key.replace("#", "_").lower(),
        )

    @property
    def register_name(self) -> RegisterName:
        """Return the register name."""
        return RegisterName(self.key.split("#")[0])

    @property
    def context(self) -> HuaweiSolarEntityContext:
        """Context used by DataUpdateCoordinator."""
        registers = [self.register_name]
        if self.is_available_key:
            registers.append(self.is_available_key)
        return {"register_names": registers}


class HuaweiSolarCoordinatorEntity[
    CoordinatorT: DataUpdateCoordinator[Any] = HuaweiSolarUpdateCoordinator
](CoordinatorEntity[CoordinatorT], HuaweiSolarEntity):
    """Huawei Solar Coordinator Entity."""

    @property
    @override
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self._attr_available

    def _is_available_from_description(
        self, description: HuaweiSolarEntityDescription
    ) -> bool:
        """Return availability evaluated from description's check_is_available_func."""
        if description.check_is_available_func:
            assert description.is_available_key
            is_available_register = self.coordinator.data.get(
                description.is_available_key
            )
            return description.check_is_available_func(
                is_available_register.value if is_available_register else None
            )
        return True

    @callback
    def _async_update_attrs(self) -> None:
        """Update entity attributes from coordinator data."""

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._async_update_attrs()
        super()._handle_coordinator_update()

    @override
    async def async_added_to_hass(self) -> None:
        """When entity is added to hass update state from existing coordinator data."""
        await super().async_added_to_hass()
        self._async_update_attrs()


HELD_BY_ENERGY_MANAGER: dict[RegisterName, rv.ParameterLockFlags] = {
    rn.ACTIVE_POWER_PERCENTAGE_DERATING: (
        rv.ParameterLockFlags.ACTIVE_POWER_PERCENTAGE_DERATING
    ),
    rn.ACTIVE_POWER_FIXED_VALUE_DERATING: (
        rv.ParameterLockFlags.ACTIVE_POWER_FIXED_VALUE_DERATING
    ),
    rn.STORAGE_CHARGE_FROM_GRID_FUNCTION: rv.ParameterLockFlags.CHARGE_FROM_GRID,
    rn.STORAGE_POWER_OF_CHARGE_FROM_GRID: (
        rv.ParameterLockFlags.GRID_CHARGE_MAXIMUM_POWER
    ),
    rn.STORAGE_GRID_CHARGE_CUTOFF_STATE_OF_CHARGE: (
        rv.ParameterLockFlags.GRID_CHARGE_CUTOFF_SOC
    ),
    rn.STORAGE_CHARGING_CUTOFF_CAPACITY: rv.ParameterLockFlags.END_OF_CHARGE_SOC,
    rn.STORAGE_DISCHARGING_CUTOFF_CAPACITY: rv.ParameterLockFlags.END_OF_DISCHARGE_SOC,
}
"""Inverter settings an energy manager can hold, with their flag in register 30298."""


def is_held_by_energy_manager(device: HuaweiSolarDevice, register_name: str) -> bool:
    """Whether an energy manager (EMMA) holds this inverter setting.

    The FusionSolar app shows such a setting read-only and asks to set it on the
    energy manager instead. The library reads the flags once during setup.
    """
    return (
        isinstance(device, SUN2000Device)
        and register_name in HELD_BY_ENERGY_MANAGER
        and HELD_BY_ENERGY_MANAGER[RegisterName(register_name)]
        in device.parameters_held_by_energy_manager
    )
