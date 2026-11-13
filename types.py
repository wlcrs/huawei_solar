"""Typing for the Huawei Solar integration."""

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, TypedDict, cast

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
from huawei_solar.modbus_pdu import PermissionDeniedError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .update_coordinator import (
    HuaweiSolarOptimizerUpdateCoordinator,
    HuaweiSolarUpdateCoordinator,
)


@dataclass
class HuaweiSolarDeviceData:
    """Runtime data for the Huawei Solar integration."""

    device: HuaweiSolarDevice
    ha_device_id: str
    device_info: DeviceInfo
    update_coordinator: HuaweiSolarUpdateCoordinator
    configuration_update_coordinator: HuaweiSolarUpdateCoordinator | None
    has_write_permission: bool = False


@dataclass
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


type HuaweiSolarConfigEntry = ConfigEntry[HuaweiSolarData]


class HuaweiSolarData(TypedDict):
    """Data for each Huawei Solar config entry."""

    device_datas: list[HuaweiSolarDeviceData]


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


class HuaweiSolarEntityDescription(EntityDescription):
    """Huawei Solar Entity Description."""

    @property
    def register_name(self) -> RegisterName:
        """Return the register name."""
        return cast("RegisterName", self.key)


class HuaweiSolarEntityContext(TypedDict):
    """Context for Huawei Solar Entities."""

    register_names: list[RegisterName]


class HuaweiSolarCoordinatorEntity[
    CoordinatorT: DataUpdateCoordinator[Any] = HuaweiSolarUpdateCoordinator
](CoordinatorEntity[CoordinatorT], HuaweiSolarEntity):
    """Huawei Solar Coordinator Entity."""

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self._attr_available

    @callback
    def _async_update_attrs(self) -> None:
        """Update entity attributes from coordinator data."""

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._async_update_attrs()
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass update state from existing coordinator data."""
        await super().async_added_to_hass()
        self._async_update_attrs()
