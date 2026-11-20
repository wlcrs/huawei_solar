"""Button entities for Huawei Solar."""

import logging
from typing import override

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from huawei_solar import SUN2000Device

from .const import CONF_ENABLE_PARAMETER_CONFIGURATION
from .services import async_stop_forcible_charge
from .types import (
    HuaweiSolarConfigEntry,
    HuaweiSolarCoordinatorEntity,
    HuaweiSolarDeviceData,
    HuaweiSolarInverterData,
    async_call_with_device_error_handling,
)
from .update_coordinator import HuaweiSolarUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HuaweiSolarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Huawei Solar Button entities Setup."""
    if not entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION):
        return

    device_datas: list[HuaweiSolarDeviceData] = entry.runtime_data

    entities_to_add: list[ButtonEntity] = []
    for ucs in device_datas:
        if not isinstance(ucs, HuaweiSolarInverterData):
            continue
        if not ucs.connected_energy_storage or not ucs.configuration_update_coordinator:
            continue

        entities_to_add.append(
            StopForcibleChargeButtonEntity(
                ucs.configuration_update_coordinator,
                ucs.device,
                ucs.connected_energy_storage,
            )
        )

    async_add_entities(entities_to_add)


class StopForcibleChargeButtonEntity(HuaweiSolarCoordinatorEntity, ButtonEntity):
    """Button to stop a running forcible charge or discharge."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "stop_forcible_charge"

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        device: SUN2000Device,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator, {"register_names": []})
        self.device = device
        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_stop_forcible_charge"

    @override
    async def async_press(self) -> None:
        """Stop the forcible charge or discharge."""
        await async_call_with_device_error_handling(
            async_stop_forcible_charge(self.device)
        )
        await self.coordinator.async_request_refresh()
