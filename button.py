"""Button entities for Huawei Solar."""

import logging

from huawei_solar import SUN2000Device, register_names as rn, register_values as rv

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENABLE_PARAMETER_CONFIGURATION, DATA_DEVICE_DATAS
from .types import (
    HuaweiSolarConfigEntry,
    HuaweiSolarDeviceData,
    HuaweiSolarEntity,
    HuaweiSolarInverterData,
)
from .update_coordinator import HuaweiSolarUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HuaweiSolarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Huawei Solar Button entities Setup."""
    if not entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION):
        return

    device_datas: list[HuaweiSolarDeviceData] = entry.runtime_data[DATA_DEVICE_DATAS]

    entities_to_add: list[ButtonEntity] = []
    for ucs in device_datas:
        if not isinstance(ucs, HuaweiSolarInverterData):
            continue
        if not ucs.connected_energy_storage:
            continue

        entities_to_add.append(
            StopForcibleChargeButtonEntity(
                ucs.device,
                ucs.connected_energy_storage,
                ucs.configuration_update_coordinator,
            )
        )

    async_add_entities(entities_to_add)


class StopForcibleChargeButtonEntity(HuaweiSolarEntity, ButtonEntity):
    """Button to stop a running forcible charge or discharge."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "stop_forcible_charge"
    _attr_icon = "mdi:battery-off"

    def __init__(
        self,
        device: SUN2000Device,
        device_info: DeviceInfo,
        configuration_update_coordinator: HuaweiSolarUpdateCoordinator | None,
    ) -> None:
        """Initialize the button entity."""
        self.device = device
        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_stop_forcible_charge"
        self._configuration_update_coordinator = configuration_update_coordinator

    async def async_press(self) -> None:
        """Stop the forcible charge or discharge."""
        await self.device.set(
            rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
            rv.StorageForcibleChargeDischarge.STOP,
        )
        await self.device.set(rn.STORAGE_FORCIBLE_DISCHARGE_POWER, 0)
        await self.device.set(
            rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD,
            0,
        )
        await self.device.set(
            rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE,
            rv.StorageForcibleChargeDischargeTargetMode.TIME,
        )

        if self._configuration_update_coordinator:
            await self._configuration_update_coordinator.async_request_refresh()
