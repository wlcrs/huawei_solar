"""Specialized DataUpdateCoordinators for Huawei Solar entities."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from itertools import chain
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from huawei_solar import HuaweiSolarBridge, HuaweiSolarException, HuaweiSUN2000Bridge

from .const import OPTIMIZER_UPDATE_TIMEOUT, UPDATE_TIMEOUT

_LOGGER = logging.getLogger(__name__)


class HuaweiSolarUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """A specialised DataUpdateCoordinator for Huawei Solar entities."""

    bridge: HuaweiSolarBridge

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        bridge: HuaweiSolarBridge,
        name: str,
        update_interval: timedelta | None = None,
        update_method: Callable[[], Awaitable[dict[str, Any]]] | None = None,
        request_refresh_debouncer: Debouncer | None = None,
        update_timeout: timedelta = UPDATE_TIMEOUT,
    ) -> None:
        """Create a HuaweiSolarUpdateCoordinator."""
        super().__init__(
            hass,
            logger,
            name=name,
            update_interval=update_interval,
            update_method=update_method,
            request_refresh_debouncer=request_refresh_debouncer,
        )
        self.bridge = bridge
        self.update_timeout = update_timeout

    async def _async_update_data(self):
        register_names_set = set(
            chain.from_iterable(ctx["register_names"] for ctx in self.async_contexts())
        )
        try:
            async with asyncio.timeout(self.update_timeout.total_seconds()):
                return await self.bridge.batch_update(list(register_names_set))
        except HuaweiSolarException as err:
            raise UpdateFailed(
                f"Could not update {self.bridge.serial_number} values: {err}"
            ) from err


class HuaweiSolarOptimizerUpdateCoordinator(DataUpdateCoordinator):
    """A specialised DataUpdateCoordinator for Huawei Solar optimizers."""

    data: dict[str, Any] = {}

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        bridge: HuaweiSUN2000Bridge,
        optimizer_device_infos: dict[int, DeviceInfo],
        name: str,
        update_interval: timedelta | None = None,
        request_refresh_debouncer: Debouncer | None = None,
    ) -> None:
        """Create a HuaweiSolarRegisterUpdateCoordinator."""
        super().__init__(
            hass,
            logger,
            name=name,
            update_interval=update_interval,
            request_refresh_debouncer=request_refresh_debouncer,
        )
        self.bridge = bridge
        self.optimizer_device_infos = optimizer_device_infos

    async def _async_update_data(self):
        """Retrieve the latest values from the optimizers."""
        try:
            async with asyncio.timeout(OPTIMIZER_UPDATE_TIMEOUT.total_seconds()):
                return await self.bridge.get_latest_optimizer_history_data()
        except HuaweiSolarException as err:
            raise UpdateFailed(
                f"Could not update {self.bridge.serial_number} optimizer values: {err}"
            ) from err


async def create_optimizer_update_coordinator(
    hass: HomeAssistant,
    bridge: HuaweiSUN2000Bridge,
    optimizer_device_infos: dict[int, DeviceInfo],
    update_interval,
) -> HuaweiSolarOptimizerUpdateCoordinator:
    """Create and refresh entities of an HuaweiSolarOptimizerUpdateCoordinator."""

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
