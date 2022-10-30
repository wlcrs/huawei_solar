"""The Huawei Solar integration."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import TypedDict, TypeVar

import async_timeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from huawei_solar import HuaweiSolarBridge, HuaweiSolarException, InvalidCredentials
from huawei_solar import register_values as rv

from .const import (
    CONF_ENABLE_PARAMETER_CONFIGURATION,
    CONF_SLAVE_IDS,
    DATA_OPTIMIZER_UPDATE_COORDINATORS,
    DATA_UPDATE_COORDINATORS,
    DOMAIN,
    OPTIMIZER_UPDATE_INTERVAL,
    SERVICES,
    UPDATE_INTERVAL,
)
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.NUMBER,
    Platform.SWITCH,
    Platform.SELECT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Huawei Solar from a config entry."""

    primary_bridge = None
    try:

        if entry.data[CONF_HOST] is None:
            primary_bridge = await HuaweiSolarBridge.create_rtu(
                port=entry.data[CONF_PORT], slave_id=entry.data[CONF_SLAVE_IDS][0]
            )
        else:
            primary_bridge = await HuaweiSolarBridge.create(
                host=entry.data[CONF_HOST],
                port=entry.data[CONF_PORT],
                slave_id=entry.data[CONF_SLAVE_IDS][0],
            )

            if entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION):
                if entry.data.get(CONF_USERNAME) and entry.data.get(CONF_PASSWORD):
                    try:
                        await primary_bridge.login(
                            entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
                        )
                    except InvalidCredentials as err:
                        raise ConfigEntryAuthFailed() from err

        primary_bridge_device_infos = await _compute_device_infos(
            primary_bridge,
            connecting_inverter_device_id=None,
        )

        bridges_with_device_infos: list[
            tuple[HuaweiSolarBridge, HuaweiInverterBridgeDeviceInfos]
        ] = [(primary_bridge, primary_bridge_device_infos)]

        for extra_slave_id in entry.data[CONF_SLAVE_IDS][1:]:
            extra_bridge = await HuaweiSolarBridge.create_extra_slave(
                primary_bridge, extra_slave_id
            )

            extra_bridge_device_infos = await _compute_device_infos(
                extra_bridge,
                connecting_inverter_device_id=(
                    DOMAIN,
                    primary_bridge.serial_number,
                ),
            )

            bridges_with_device_infos.append((extra_bridge, extra_bridge_device_infos))

        # Now create update coordinators for each bridge
        update_coordinators = []
        optimizer_update_coordinators = []
        for bridge, device_infos in bridges_with_device_infos:
            update_coordinators.append(
                await _create_update_coordinator(
                    hass, bridge, device_infos, UPDATE_INTERVAL
                )
            )

            if bridge.has_optimizers:
                optimizers_device_infos = {}
                try:
                    optimizer_system_infos = (
                        await bridge.get_optimizer_system_information_data()
                    )
                    for optimizer_id, optimizer in optimizer_system_infos.items():
                        optimizers_device_infos[optimizer_id] = DeviceInfo(
                            identifiers={(DOMAIN, optimizer.sn)},
                            name=optimizer.sn,
                            manufacturer="Huawei",
                            model=optimizer.model,
                            sw_version=optimizer.software_version,
                            via_device=(DOMAIN, bridge.serial_number),
                        )

                    optimizer_update_coordinators.append(
                        await _create_optimizer_update_coordinator(
                            hass,
                            bridge,
                            optimizers_device_infos,
                            OPTIMIZER_UPDATE_INTERVAL,
                        )
                    )
                except HuaweiSolarException as exception:
                    _LOGGER.info(
                        "Cannot create optimizer sensor entities as the integration has insufficient permissions. "
                        "Consider enabling elevated permissions to get more optimizer data",
                        exc_info=exception,
                    )
                    optimizers_device_infos = None
                except Exception as exc:  # pylint: disable=broad-except
                    _LOGGER.exception(
                        "Cannot create optimizer sensor entities due to an unexpected error",
                        exc_info=exc,
                    )
                    optimizers_device_infos = {}

        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
            DATA_UPDATE_COORDINATORS: update_coordinators,
            DATA_OPTIMIZER_UPDATE_COORDINATORS: optimizer_update_coordinators,
        }
    except (HuaweiSolarException, TimeoutError, asyncio.TimeoutError) as err:
        if primary_bridge is not None:
            await primary_bridge.stop()

        raise ConfigEntryNotReady from err

    except Exception as err:
        # always try to stop the bridge, as it will keep retrying
        # in the background otherwise!
        if primary_bridge is not None:
            await primary_bridge.stop()

        raise err

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_setup_services(hass, entry, bridges_with_device_infos)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        update_coordinators = hass.data[DOMAIN][entry.entry_id][
            DATA_UPDATE_COORDINATORS
        ]
        for update_coordinator in update_coordinators:
            await update_coordinator.bridge.stop()

        for service in SERVICES:
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)

        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class HuaweiInverterBridgeDeviceInfos(TypedDict):
    """Device Infos for a specific inverter."""

    inverter: DeviceInfo
    power_meter: DeviceInfo | None
    connected_energy_storage: DeviceInfo | None


async def _compute_device_infos(
    bridge: HuaweiSolarBridge,
    connecting_inverter_device_id: tuple[str, str] | None,
) -> HuaweiInverterBridgeDeviceInfos:
    """Create the correct DeviceInfo-objects, which can be used to correctly assign to entities in this integration."""

    inverter_device_info = DeviceInfo(
        identifiers={(DOMAIN, bridge.serial_number)},
        name="Inverter",
        manufacturer="Huawei",
        model=bridge.model_name,
        via_device=connecting_inverter_device_id,  # type: ignore
    )

    # Add power meter device if a power meter is detected
    power_meter_device_info = None

    if bridge.power_meter_type is not None:
        power_meter_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, f"{bridge.serial_number}/power_meter"),
            },
            name="Power meter",
            via_device=(DOMAIN, bridge.serial_number),
        )

    # Add battery device if a battery is detected
    battery_device_info = None

    if bridge.battery_1_type != rv.StorageProductModel.NONE:
        battery_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, f"{bridge.serial_number}/connected_energy_storage"),
            },
            name="Battery",
            manufacturer=inverter_device_info["manufacturer"],
            model=f"{inverter_device_info['model']} Connected energy storage",
            via_device=(DOMAIN, bridge.serial_number),
        )

    return HuaweiInverterBridgeDeviceInfos(
        inverter=inverter_device_info,
        power_meter=power_meter_device_info,
        connected_energy_storage=battery_device_info,
    )


class HuaweiSolarUpdateCoordinator(DataUpdateCoordinator):
    """A specialised DataUpdateCoordinator for Huawei Solar."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        bridge: HuaweiSolarBridge,
        device_infos: HuaweiInverterBridgeDeviceInfos,
        name: str,
        update_interval: timedelta | None = None,
        update_method: Callable[[], Awaitable[T]] | None = None,
        request_refresh_debouncer: Debouncer | None = None,
    ) -> None:
        """Create a HuaweiSolarRegisterUpdateCoordinator."""
        super().__init__(
            hass,
            logger,
            name=name,
            update_interval=update_interval,
            update_method=update_method,
            request_refresh_debouncer=request_refresh_debouncer,
        )
        self.bridge = bridge
        self.device_infos = device_infos

    async def _async_update_data(self):
        try:
            async with async_timeout.timeout(20):
                return await self.bridge.update()
        except HuaweiSolarException as err:
            raise UpdateFailed(
                f"Could not update {self.bridge.serial_number} values: {err}"
            ) from err


async def _create_update_coordinator(
    hass,
    bridge: HuaweiSolarBridge,
    device_infos: HuaweiInverterBridgeDeviceInfos,
    update_interval,
):

    coordinator = HuaweiSolarUpdateCoordinator(
        hass,
        _LOGGER,
        bridge=bridge,
        device_infos=device_infos,
        name=f"{bridge.serial_number}_data_update_coordinator",
        update_interval=update_interval,
    )

    await coordinator.async_config_entry_first_refresh()

    return coordinator


class HuaweiSolarOptimizerUpdateCoordinator(DataUpdateCoordinator):
    """A specialised DataUpdateCoordinator for Huawei Solar optimizers."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        bridge: HuaweiSolarBridge,
        optimizer_device_infos: dict[int, DeviceInfo],
        name: str,
        update_interval: timedelta | None = None,
        update_method: Callable[[], Awaitable[T]] | None = None,
        request_refresh_debouncer: Debouncer | None = None,
    ) -> None:
        """Create a HuaweiSolarRegisterUpdateCoordinator."""
        super().__init__(
            hass,
            logger,
            name=name,
            update_interval=update_interval,
            update_method=update_method,
            request_refresh_debouncer=request_refresh_debouncer,
        )
        self.bridge = bridge
        self.optimizer_device_infos = optimizer_device_infos

    async def _async_update_data(self):
        """Retrieve the latest values from the optimizers."""
        try:
            async with async_timeout.timeout(20):
                return await self.bridge.get_latest_optimizer_history_data()
        except HuaweiSolarException as err:
            raise UpdateFailed(
                f"Could not update {self.bridge.serial_number} optimizer values: {err}"
            ) from err


async def _create_optimizer_update_coordinator(
    hass,
    bridge: HuaweiSolarBridge,
    optimizer_device_infos: dict[int, DeviceInfo],
    update_interval,
):

    coordinator = HuaweiSolarOptimizerUpdateCoordinator(
        hass,
        _LOGGER,
        bridge=bridge,
        optimizer_device_infos=optimizer_device_infos,
        name=f"{bridge.serial_number}_optimizer_data_update_coordinator",
        update_interval=update_interval,
    )

    await coordinator.async_config_entry_first_refresh()

    return coordinator


class HuaweiSolarEntity(Entity):
    """Huawei Solar Entity."""

    _attr_has_entity_name = True

    def add_name_suffix(self, suffix) -> None:
        """Add a suffix after the current entity name."""
        self._attr_name = f"{self.name}{suffix}"
