"""Support for Huawei inverter monitoring API."""

from typing import Any

from huawei_solar import (
    EMMADevice,
    HuaweiSolarDevice,
    SChargerDevice,
    SDongleDevice,
    SmartLoggerDevice,
    register_names as rn,
    register_values as rv,
)
from huawei_solar.files import OptimizerRunningStatus
from huawei_solar.register_definitions.periods import (
    ChargeFlag,
    HUAWEI_LUNA2000_TimeOfUsePeriod,
    LG_RESU_TimeOfUsePeriod,
    PeakSettingPeriod,
)

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_DEVICE_DATAS
from .sensor_descriptions import (
    BATTERIES_SENSOR_DESCRIPTIONS,
    BATTERY_TEMPLATE_SENSOR_DESCRIPTIONS,
    CHARGER_SENSOR_DESCRIPTIONS,
    EMMA_SENSOR_DESCRIPTIONS,
    INVERTER_SENSOR_DESCRIPTIONS,
    OPTIMIZER_DETAIL_SENSOR_DESCRIPTIONS,
    OPTIMIZER_SENSOR_DESCRIPTIONS,
    SINGLE_PHASE_METER_ENTITY_DESCRIPTIONS,
    SMARTLOGGER_SENSOR_DESCRIPTIONS,
    SDONGLE_SENSOR_DESCRIPTIONS,
    THREE_PHASE_METER_ENTITY_DESCRIPTIONS,
    BatteryTemplateEntityDescription,
    HuaweiSolarSensorEntityDescription,
    get_pv_entity_descriptions,
)
from .types import (
    HuaweiSolarConfigEntry,
    HuaweiSolarDeviceData,
    HuaweiSolarEntity,
    HuaweiSolarInverterData,
)
from .update_coordinator import (
    HuaweiSolarOptimizerUpdateCoordinator,
    HuaweiSolarUpdateCoordinator,
)

PARALLEL_UPDATES = 1


async def create_sun2000_entities(ucs: HuaweiSolarInverterData) -> list[SensorEntity]:
    """Create SUN2000 sensor entities."""
    entities_to_add: list[SensorEntity] = []

    entities_to_add.extend(
        HuaweiSolarSensorEntity(
            ucs.update_coordinator,
            entity_description,
            ucs.device_info,
        )
        for entity_description in INVERTER_SENSOR_DESCRIPTIONS
    )
    entities_to_add.append(
        HuaweiSolarAlarmSensorEntity(ucs.update_coordinator, ucs.device_info)
    )

    entities_to_add.extend(
        HuaweiSolarSensorEntity(
            ucs.update_coordinator,
            entity_description,
            ucs.device_info,
        )
        for entity_description in get_pv_entity_descriptions(ucs.device.pv_string_count)
    )

    if ucs.device.has_optimizers:
        entities_to_add.extend(
            HuaweiSolarSensorEntity(
                ucs.update_coordinator,
                entity_description,
                ucs.device_info,
            )
            for entity_description in OPTIMIZER_SENSOR_DESCRIPTIONS
        )

    if (
        ucs.device.power_meter_type == rv.MeterType.SINGLE_PHASE
        and ucs.power_meter_update_coordinator
        and ucs.power_meter
    ):
        entities_to_add.extend(
            HuaweiSolarSensorEntity(
                ucs.power_meter_update_coordinator, entity_description, ucs.power_meter
            )
            for entity_description in SINGLE_PHASE_METER_ENTITY_DESCRIPTIONS
        )

    elif (
        ucs.device.power_meter_type == rv.MeterType.THREE_PHASE
        and ucs.power_meter_update_coordinator
        and ucs.power_meter
    ):
        entities_to_add.extend(
            HuaweiSolarSensorEntity(
                ucs.power_meter_update_coordinator, entity_description, ucs.power_meter
            )
            for entity_description in THREE_PHASE_METER_ENTITY_DESCRIPTIONS
        )

    if (
        not isinstance(ucs.device.primary_device, EMMADevice)
        and await ucs.device.has_write_permission()
        and ucs.configuration_update_coordinator
    ):
        entities_to_add.append(
            HuaweiSolarActivePowerControlModeEntity(
                ucs.configuration_update_coordinator,
                ucs.device,
                ucs.device_info,
            )
        )

    if (
        ucs.device.battery_type != rv.StorageProductModel.NONE
        and ucs.energy_storage_update_coordinator
        and ucs.connected_energy_storage
    ):
        entities_to_add.extend(
            HuaweiSolarSensorEntity(
                ucs.energy_storage_update_coordinator,
                entity_description,
                ucs.connected_energy_storage,
            )
            for entity_description in BATTERIES_SENSOR_DESCRIPTIONS
        )

        if ucs.configuration_update_coordinator:
            if ucs.device.battery_type == rv.StorageProductModel.HUAWEI_LUNA2000:
                entities_to_add.append(
                    HuaweiSolarTOUSensorEntity(
                        ucs.configuration_update_coordinator,
                        ucs.device,
                        ucs.connected_energy_storage,
                    ),
                )
            elif ucs.device.battery_type == rv.StorageProductModel.LG_RESU:
                entities_to_add.append(
                    HuaweiSolarPricePeriodsSensorEntity(
                        ucs.configuration_update_coordinator,
                        ucs.device,
                        ucs.connected_energy_storage,
                    ),
                )
            entities_to_add.append(
                HuaweiSolarForcibleChargeEntity(
                    ucs.configuration_update_coordinator,
                    ucs.device,
                    ucs.connected_energy_storage,
                ),
            )

            if ucs.device.supports_capacity_control:
                entities_to_add.append(
                    HuaweiSolarCapacityControlPeriodsSensorEntity(
                        ucs.configuration_update_coordinator,
                        ucs.device,
                        ucs.connected_energy_storage,
                    )
                )

        if ucs.battery_1:
            entities_to_add.extend(
                HuaweiSolarSensorEntity(
                    ucs.energy_storage_update_coordinator,
                    HuaweiSolarSensorEntityDescription(
                        key=entity_description_template.battery_1_key,
                        translation_key=entity_description_template.translation_key,
                        device_class=entity_description_template.device_class,
                        state_class=entity_description_template.state_class,
                        native_unit_of_measurement=entity_description_template.native_unit_of_measurement,
                        icon=entity_description_template.icon,
                        entity_category=entity_description_template.entity_category,
                        entity_registry_enabled_default=False,
                    ),
                    ucs.battery_1,
                )
                for entity_description_template in BATTERY_TEMPLATE_SENSOR_DESCRIPTIONS
                if entity_description_template.battery_1_key
            )

        if ucs.battery_2:
            entities_to_add.extend(
                HuaweiSolarSensorEntity(
                    ucs.energy_storage_update_coordinator,
                    HuaweiSolarSensorEntityDescription(
                        key=entity_description_template.battery_2_key,
                        translation_key=entity_description_template.translation_key,
                        device_class=entity_description_template.device_class,
                        state_class=entity_description_template.state_class,
                        native_unit_of_measurement=entity_description_template.native_unit_of_measurement,
                        icon=entity_description_template.icon,
                        entity_category=entity_description_template.entity_category,
                        entity_registry_enabled_default=False,
                    ),
                    ucs.battery_2,
                )
                for entity_description_template in BATTERY_TEMPLATE_SENSOR_DESCRIPTIONS
                if entity_description_template.battery_2_key
            )
    if ucs.optimizer_update_coordinator:
        optimizer_device_infos = ucs.optimizer_update_coordinator.optimizer_device_infos

        entities_to_add.extend(
            HuaweiSolarOptimizerSensorEntity(
                ucs.optimizer_update_coordinator,
                entity_description,
                optimizer_id,
                device_info,
            )
            for optimizer_id, device_info in optimizer_device_infos.items()
            for entity_description in OPTIMIZER_DETAIL_SENSOR_DESCRIPTIONS
        )

    return entities_to_add


def create_emma_entities(
    ucs: HuaweiSolarDeviceData,
) -> list["SensorEntity"]:
    """Create EMMA sensor entities."""
    if not isinstance(ucs.device, EMMADevice):
        return []

    entities: list[SensorEntity] = [
        HuaweiSolarSensorEntity(
            ucs.update_coordinator, entity_description, ucs.device_info
        )
        for entity_description in EMMA_SENSOR_DESCRIPTIONS
    ]

    if ucs.configuration_update_coordinator:
        entities.append(
            HuaweiSolarTOUSensorEntity(
                ucs.configuration_update_coordinator,
                ucs.device,
                ucs.device_info,
                register_name=rn.EMMA_TOU_PERIODS,
                entity_registry_enabled_default=False,
            )
        )

    return entities


def create_charger_entities(
    ucs: HuaweiSolarDeviceData,
) -> list["HuaweiSolarSensorEntity"]:
    """Create Charger sensor entities."""
    if not isinstance(ucs.device, SChargerDevice):
        return []

    return [
        HuaweiSolarSensorEntity(
            ucs.update_coordinator, entity_description, ucs.device_info
        )
        for entity_description in CHARGER_SENSOR_DESCRIPTIONS
    ]


def create_sdongle_entities(
    ucs: HuaweiSolarDeviceData,
) -> list["HuaweiSolarSensorEntity"]:
    """Create SDongle sensor entities."""
    if not isinstance(ucs.device, SDongleDevice):
        return []

    return [
        HuaweiSolarSensorEntity(
            ucs.update_coordinator, entity_description, ucs.device_info
        )
        for entity_description in SDONGLE_SENSOR_DESCRIPTIONS
    ]


def create_smartlogger_entities(
    ucs: HuaweiSolarDeviceData,
) -> list["HuaweiSolarSensorEntity"]:
    """Create SmartLogger sensor entities."""
    if not isinstance(ucs.device, SmartLoggerDevice):
        return []

    return [
        HuaweiSolarSensorEntity(
            ucs.update_coordinator, entity_description, ucs.device_info
        )
        for entity_description in SMARTLOGGER_SENSOR_DESCRIPTIONS
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HuaweiSolarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add Huawei Solar entry."""
    device_datas: list[HuaweiSolarDeviceData] = entry.runtime_data[DATA_DEVICE_DATAS]

    entities_to_add = []
    for ucs in device_datas:
        if isinstance(ucs, HuaweiSolarInverterData):
            entities_to_add.extend(await create_sun2000_entities(ucs))
        elif isinstance(ucs.device, EMMADevice):
            entities_to_add.extend(create_emma_entities(ucs))
        elif isinstance(ucs.device, SChargerDevice):
            entities_to_add.extend(create_charger_entities(ucs))
        elif isinstance(ucs.device, SDongleDevice):
            entities_to_add.extend(create_sdongle_entities(ucs))
        elif isinstance(ucs.device, SmartLoggerDevice):
            entities_to_add.extend(create_smartlogger_entities(ucs))

    async_add_entities(entities_to_add, True)


class HuaweiSolarSensorEntity(
    CoordinatorEntity[HuaweiSolarUpdateCoordinator], HuaweiSolarEntity, SensorEntity
):
    """Huawei Solar Sensor which receives its data via an DataUpdateCoordinator."""

    entity_description: HuaweiSolarSensorEntityDescription

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        description: HuaweiSolarSensorEntityDescription,
        device_info: DeviceInfo,
        context: Any = None,
    ) -> None:
        """Batched Huawei Solar Sensor Entity constructor."""
        super().__init__(coordinator, context or description.context)

        self.coordinator = coordinator
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{coordinator.device.serial_number}_{description.key}"

        register_key = self.entity_description.key
        if "#" in register_key:
            register_key = register_key[0 : register_key.find("#")]

        self._register_key = rn.RegisterName(register_key)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data and self._register_key in self.coordinator.data:
            value = self.coordinator.data[self._register_key].value

            if self.entity_description.value_conversion_function:
                value = self.entity_description.value_conversion_function(value)

            self._attr_native_value = value
            self._attr_available = True
        else:
            self._attr_available = False
            self._attr_native_value = None

        self.async_write_ha_state()


class HuaweiSolarAlarmSensorEntity(HuaweiSolarSensorEntity):
    """Huawei Solar Sensor for Alarm values.

    These are spread over three registers that are received by the DataUpdateCoordinator.
    """

    ALARM_REGISTERS: list[rn.RegisterName] = [rn.ALARM_1, rn.ALARM_2, rn.ALARM_3]

    DESCRIPTION = HuaweiSolarSensorEntityDescription(
        key="ALARMS",
        translation_key="alarms",
        entity_category=EntityCategory.DIAGNOSTIC,
    )

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        device_info: DeviceInfo,
    ) -> None:
        """Batched Huawei Solar Sensor Entity constructor."""
        super().__init__(
            coordinator,
            self.DESCRIPTION,
            device_info,
            context={"register_names": self.ALARM_REGISTERS},
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self.coordinator.data and set(self.ALARM_REGISTERS) <= set(
            self.coordinator.data.keys()
        ):
            alarms = []
            for register_name in self.ALARM_REGISTERS:
                alarms.extend(self.coordinator.data[register_name].value)

            if len(alarms):
                self._attr_native_value = ", ".join(alarms)
            else:
                self._attr_native_value = "None"
            self._attr_available = True
        else:
            self._attr_available = False
            self._attr_native_value = None
        self.async_write_ha_state()


def _days_effective_to_str(
    days: tuple[bool, bool, bool, bool, bool, bool, bool],
) -> str:
    value = ""
    for i in range(7):  # Sunday is on index 0, but we want to name it day 7
        if days[(i + 1) % 7]:
            value += f"{i + 1}"

    return value


def _time_int_to_str(time: int) -> str:
    return f"{time // 60:02d}:{time % 60:02d}"


class HuaweiSolarTOUSensorEntity(
    CoordinatorEntity[HuaweiSolarUpdateCoordinator], HuaweiSolarEntity, SensorEntity
):
    """Huawei Solar Sensor for configured TOU periods.

    It shows the number of configured TOU periods, and has the
    contents of them as extended attributes
    """

    entity_description: HuaweiSolarSensorEntityDescription

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        device: HuaweiSolarDevice,
        device_info: DeviceInfo,
        register_name: str = rn.STORAGE_HUAWEI_LUNA2000_TIME_OF_USE_CHARGING_AND_DISCHARGING_PERIODS,
        entity_registry_enabled_default: bool = True,
    ) -> None:
        """Huawei Solar TOU Sensor Entity constructor."""
        super().__init__(
            coordinator,
            {"register_names": [register_name]},
        )
        self.coordinator = coordinator

        self.entity_description = HuaweiSolarSensorEntityDescription(
            key=register_name,
            icon="mdi:calendar-text",
            entity_registry_enabled_default=entity_registry_enabled_default,
        )

        self._bridge = device
        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_{self.entity_description.key}"

    def _huawei_luna2000_period_to_text(
        self, period: HUAWEI_LUNA2000_TimeOfUsePeriod
    ) -> str:
        return (
            f"{_time_int_to_str(period.start_time)}-{_time_int_to_str(period.end_time)}"
            f"/{_days_effective_to_str(period.days_effective)}"
            f"/{'+' if period.charge_flag == ChargeFlag.CHARGE else '-'}"
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.data
            and self.entity_description.register_name in self.coordinator.data
        ):
            self._attr_available = True

            data: list[HUAWEI_LUNA2000_TimeOfUsePeriod] = self.coordinator.data[
                self.entity_description.register_name
            ].value

            self._attr_native_value = len(data)
            self._attr_extra_state_attributes = {
                f"Period {idx + 1}": self._huawei_luna2000_period_to_text(period)
                for idx, period in enumerate(data)
            }
        else:
            self._attr_available = False
            self._attr_native_value = None

        self.async_write_ha_state()


def _lg_resu_period_to_text(period: LG_RESU_TimeOfUsePeriod) -> str:
    return (
        f"{_time_int_to_str(period.start_time)}-{_time_int_to_str(period.end_time)}"
        f"/{period.electricity_price}"
    )


class HuaweiSolarPricePeriodsSensorEntity(
    CoordinatorEntity[HuaweiSolarUpdateCoordinator], HuaweiSolarEntity, SensorEntity
):
    """Huawei Solar Sensor for configured TOU periods.

    It shows the number of configured TOU periods, and has the
    contents of them as extended attributes
    """

    entity_description: HuaweiSolarSensorEntityDescription

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        device: HuaweiSolarDevice,
        device_info: DeviceInfo,
        register_name: str = rn.STORAGE_LG_RESU_TIME_OF_USE_PRICE_PERIODS,
        entity_registry_enabled_default: bool = True,
    ) -> None:
        """Huawei Solar TOU Sensor Entity constructor."""
        super().__init__(
            coordinator,
            {"register_names": [register_name]},
        )
        self.coordinator = coordinator

        self.entity_description = HuaweiSolarSensorEntityDescription(
            key=register_name,
            icon="mdi:calendar-text",
            entity_registry_enabled_default=entity_registry_enabled_default,
        )

        self._bridge = device
        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_{self.entity_description.key}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.data
            and self.entity_description.register_name in self.coordinator.data
        ):
            self._attr_available = True

            data: list[LG_RESU_TimeOfUsePeriod] = self.coordinator.data[
                self.entity_description.register_name
            ].value

            self._attr_native_value = len(data)
            self._attr_extra_state_attributes = {
                f"Period {idx + 1}": _lg_resu_period_to_text(period)
                for idx, period in enumerate(data)
            }
        else:
            self._attr_available = False
            self._attr_native_value = None

        self.async_write_ha_state()


class HuaweiSolarCapacityControlPeriodsSensorEntity(
    CoordinatorEntity[HuaweiSolarUpdateCoordinator], HuaweiSolarEntity, SensorEntity
):
    """Huawei Solar Sensor for configured Capacity Control periods.

    It shows the number of configured capacity control periods, and has the
    contents of them as extended attributes
    """

    entity_description: HuaweiSolarSensorEntityDescription

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        device: HuaweiSolarDevice,
        device_info: DeviceInfo,
    ) -> None:
        """Huawei Solar Capacity Control Periods Sensor Entity constructor."""
        super().__init__(
            coordinator, {"register_names": [rn.STORAGE_CAPACITY_CONTROL_PERIODS]}
        )
        self.coordinator = coordinator

        self.entity_description = HuaweiSolarSensorEntityDescription(
            key=rn.STORAGE_CAPACITY_CONTROL_PERIODS,
            icon="mdi:calendar-text",
        )

        self._device = device
        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_{self.entity_description.key}"

    def _period_to_text(self, psp: PeakSettingPeriod) -> str:
        return (
            f"{_time_int_to_str(psp.start_time)}"
            f"-{_time_int_to_str(psp.end_time)}"
            f"/{_days_effective_to_str(psp.days_effective)}"
            f"/{psp.power}W"
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.data
            and self.entity_description.key in self.coordinator.data
        ):
            data: list[PeakSettingPeriod] = self.coordinator.data[
                self.entity_description.register_name
            ].value

            self._attr_available = True
            self._attr_native_value = len(data)
            self._attr_extra_state_attributes = {
                f"Period {idx + 1}": self._period_to_text(period)
                for idx, period in enumerate(data)
            }
        else:
            self._attr_available = False
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}

        self.async_write_ha_state()


class HuaweiSolarForcibleChargeEntity(
    CoordinatorEntity[HuaweiSolarUpdateCoordinator], HuaweiSolarEntity, SensorEntity
):
    """Huawei Solar Sensor for the current forcible charge status."""

    REGISTER_NAMES = [
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE,  # is SoC or time the target?
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,  # stop/charging/discharging
        rn.STORAGE_FORCIBLE_CHARGE_POWER,
        rn.STORAGE_FORCIBLE_DISCHARGE_POWER,
        rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD,
        rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SOC,
    ]

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        device: HuaweiSolarDevice,
        device_info: DeviceInfo,
    ) -> None:
        """Create HuaweiSolarForcibleChargeEntity."""
        super().__init__(
            coordinator,
            {"register_names": self.REGISTER_NAMES},
        )
        self.coordinator = coordinator

        self.entity_description = HuaweiSolarSensorEntityDescription(
            key=rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE,
            icon="mdi:battery-charging-medium",
            translation_key="forcible_charge_summary",
        )

        self._device = device
        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_{self.entity_description.key}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.data
            and set(self.REGISTER_NAMES) <= self.coordinator.data.keys()
        ):
            mode = self.coordinator.data[
                rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_WRITE
            ].value
            setting = self.coordinator.data[
                rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SETTING_MODE
            ].value
            charge_power = self.coordinator.data[rn.STORAGE_FORCIBLE_CHARGE_POWER].value
            discharge_power = self.coordinator.data[
                rn.STORAGE_FORCIBLE_DISCHARGE_POWER
            ].value
            target_soc = self.coordinator.data[
                rn.STORAGE_FORCIBLE_CHARGE_DISCHARGE_SOC
            ].value
            duration = self.coordinator.data[
                rn.STORAGE_FORCED_CHARGING_AND_DISCHARGING_PERIOD
            ].value

            if mode == rv.StorageForcibleChargeDischarge.STOP:
                value = "Stopped"
            elif mode == rv.StorageForcibleChargeDischarge.CHARGE:
                if setting == rv.StorageForcibleChargeDischargeTargetMode.SOC:
                    value = f"Charging at {charge_power}W until {target_soc}%"
                else:
                    value = f"Charging at {charge_power}W for {duration} minutes"
            elif mode == rv.StorageForcibleChargeDischarge.DISCHARGE:
                if setting == rv.StorageForcibleChargeDischargeTargetMode.SOC:
                    value = f"Discharging at {discharge_power}W until {target_soc}%"
                else:
                    value = f"Discharging at {discharge_power}W for {duration} minutes"

            self._attr_available = True
            self._attr_native_value = value
            self._attr_extra_state_attributes = {
                "mode": str(mode),
                "setting": str(setting),
                "charge_power": charge_power,
                "discharge_power": discharge_power,
                "target_soc": target_soc,
                "duration": duration,
            }
        else:
            self._attr_available = False
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
        self.async_write_ha_state()


class HuaweiSolarActivePowerControlModeEntity(
    CoordinatorEntity[HuaweiSolarUpdateCoordinator], HuaweiSolarEntity, SensorEntity
):
    """Huawei Solar Sensor for the current forcible charge status."""

    REGISTER_NAMES = [
        rn.ACTIVE_POWER_CONTROL_MODE,
        rn.MAXIMUM_FEED_GRID_POWER_WATT,
        rn.MAXIMUM_FEED_GRID_POWER_PERCENT,
    ]

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        device: HuaweiSolarDevice,
        device_info: DeviceInfo,
    ) -> None:
        """Create HuaweiSolarForcibleChargeEntity."""
        super().__init__(
            coordinator,
            {"register_names": self.REGISTER_NAMES},
        )
        self.coordinator = coordinator

        self.entity_description = HuaweiSolarSensorEntityDescription(
            key=rn.ACTIVE_POWER_CONTROL_MODE,
            translation_key="active_power_control_mode",
            icon="mdi:transmission-tower",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
        )

        self._device = device
        self._attr_device_info = device_info
        self._attr_unique_id = f"{device.serial_number}_{self.entity_description.key}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if (
            self.coordinator.data
            and set(self.REGISTER_NAMES) <= self.coordinator.data.keys()
        ):
            mode = self.coordinator.data[rn.ACTIVE_POWER_CONTROL_MODE].value
            maximum_power_watt = self.coordinator.data[
                rn.MAXIMUM_FEED_GRID_POWER_WATT
            ].value
            maximum_power_percent = self.coordinator.data[
                rn.MAXIMUM_FEED_GRID_POWER_PERCENT
            ].value

            if mode == rv.ActivePowerControlMode.UNLIMITED:
                value = "Unlimited"
            elif (
                mode == rv.ActivePowerControlMode.POWER_LIMITED_GRID_CONNECTION_PERCENT
            ):
                value = f"Limited to {maximum_power_percent}%"
            elif mode == rv.ActivePowerControlMode.POWER_LIMITED_GRID_CONNECTION_WATT:
                value = f"Limited to {maximum_power_watt}W"
            elif mode == rv.ActivePowerControlMode.ZERO_POWER_GRID_CONNECTION:
                value = "Zero Power"
            elif mode == rv.ActivePowerControlMode.DI_ACTIVE_SCHEDULING:
                value = "DI Active Scheduling"
            else:
                value = "Unknown"

            self._attr_available = True
            self._attr_native_value = value
            self._attr_extra_state_attributes = {
                "mode": str(mode),
                "maximum_power_watt": maximum_power_watt,
                "maximum_power_percent": maximum_power_percent,
            }
        else:
            self._attr_available = False
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
        self.async_write_ha_state()


class HuaweiSolarOptimizerSensorEntity(
    CoordinatorEntity[HuaweiSolarOptimizerUpdateCoordinator],
    HuaweiSolarEntity,
    SensorEntity,
):
    """Huawei Solar Optimizer Sensor which receives its data via an DataUpdateCoordinator."""

    entity_description: HuaweiSolarSensorEntityDescription

    def __init__(
        self,
        coordinator: HuaweiSolarOptimizerUpdateCoordinator,
        description: HuaweiSolarSensorEntityDescription,
        optimizer_id: int,
        device_info: DeviceInfo,
    ) -> None:
        """Batched Huawei Solar Sensor Entity constructor."""
        super().__init__(coordinator)

        self.coordinator = coordinator
        self.entity_description = description
        self.optimizer_id = optimizer_id

        self._attr_device_info = device_info
        self._attr_unique_id = f"{device_info['name']}_{description.key}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_available = (
            self.optimizer_id in self.coordinator.data
            # Optimizer data fields only return sensible data when the
            # optimizer is not offline
            and (
                self.entity_description.key == "running_status"
                or self.coordinator.data[self.optimizer_id].running_status
                != OptimizerRunningStatus.OFFLINE
            )
        )

        if self.optimizer_id in self.coordinator.data:
            value = getattr(
                self.coordinator.data[self.optimizer_id], self.entity_description.key
            )
            if self.entity_description.value_conversion_function:
                value = self.entity_description.value_conversion_function(value)

            self._attr_native_value = value

        else:
            self._attr_native_value = None

        self.async_write_ha_state()
