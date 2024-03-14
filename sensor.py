"""Support for Huawei inverter monitoring API."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import zip_longest
from typing import Any, cast

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    POWER_VOLT_AMPERE_REACTIVE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from huawei_solar import HuaweiSolarBridge, Result, register_names as rn, register_values as rv
from huawei_solar.files import OptimizerRunningStatus
from huawei_solar.registers import (
    ChargeDischargePeriod,
    ChargeFlag,
    HUAWEI_LUNA2000_TimeOfUsePeriod,
    LG_RESU_TimeOfUsePeriod,
    PeakSettingPeriod,
)

from . import (
    HuaweiSolarConfigurationUpdateCoordinator,
    HuaweiSolarEntity,
    HuaweiSolarOptimizerUpdateCoordinator,
    HuaweiSolarUpdateCoordinator,
)
from .const import (
    CONF_EXCLUDE_BATTERY,
    CONF_EXCLUDE_POWER_METER,
    DATA_CONFIGURATION_UPDATE_COORDINATORS,
    DATA_OPTIMIZER_UPDATE_COORDINATORS,
    DATA_UPDATE_COORDINATORS,
    DOMAIN,
)

PARALLEL_UPDATES = 1


@dataclass
class HuaweiSolarSensorEntityDescription(SensorEntityDescription):
    """Huawei Solar Sensor Entity."""

    value_conversion_function: Callable[[Any], str] | None = None

    def __post_init__(self):
        """Defaults the translation_key to the sensor key."""
        self.translation_key = self.translation_key or self.key.replace('#','_').lower()


# Every list in this file describes a group of entities which are related to each other.
# The order of these lists matters, as they need to be in ascending order wrt. to their modbus-register.


INVERTER_SENSOR_DESCRIPTIONS: tuple[HuaweiSolarSensorEntityDescription, ...] = (
    HuaweiSolarSensorEntityDescription(
        key=rn.INPUT_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_A_B,
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_B_C,
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_C_A,
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_A_VOLTAGE,
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_B_VOLTAGE,
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_C_VOLTAGE,
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_A_CURRENT,
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_B_CURRENT,
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_C_CURRENT,
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.DAY_ACTIVE_POWER_PEAK,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.REACTIVE_POWER,
        native_unit_of_measurement=POWER_VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.POWER_FACTOR,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.EFFICIENCY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.INTERNAL_TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.DEVICE_STATUS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STARTUP_TIME,
        icon="mdi:weather-sunset-up",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SHUTDOWN_TIME,
        icon="mdi:weather-sunset-down",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACCUMULATED_YIELD_ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.DAILY_YIELD_ENERGY,
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STATE_1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_conversion_function=", ".join,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STATE_2 + "#0",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_conversion_function=lambda value: value[0],
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STATE_2 + "#1",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_conversion_function=lambda value: value[1],
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STATE_2 + "#2",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_conversion_function=lambda value: value[2],
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STATE_3 + "#0",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_conversion_function=lambda value: value[0],
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STATE_3 + "#1",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_conversion_function=lambda value: value[1],
    ),
)

OPTIMIZER_SENSOR_DESCRIPTIONS: tuple[HuaweiSolarSensorEntityDescription, ...] = (
    HuaweiSolarSensorEntityDescription(
        key=rn.NB_ONLINE_OPTIMIZERS,
        icon="mdi:solar-panel",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

OPTIMIZER_DETAIL_SENSOR_DESCRIPTIONS: tuple[HuaweiSolarSensorEntityDescription, ...] = (
    HuaweiSolarSensorEntityDescription(
        key="output_power",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key="voltage_to_ground",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key="output_voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key="output_current",
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key="input_voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key="input_current",
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key="temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key="running_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HuaweiSolarSensorEntityDescription(
        key="accumulated_energy_yield",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key="alarm",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_conversion_function=lambda alarms: ", ".join(alarms) if len(alarms) else "None"
    ),
)


SINGLE_PHASE_METER_ENTITY_DESCRIPTIONS: tuple[
    HuaweiSolarSensorEntityDescription, ...
] = (
    HuaweiSolarSensorEntityDescription(
        key=rn.METER_STATUS,
        icon="mdi:electric-switch",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_A_VOLTAGE,
        translation_key="single_phase_voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_A_CURRENT,
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.POWER_METER_ACTIVE_POWER,
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.POWER_METER_REACTIVE_POWER,
        icon="mdi:flash",
        native_unit_of_measurement=POWER_VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_POWER_FACTOR,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_EXPORTED_ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_ACCUMULATED_ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_ACCUMULATED_REACTIVE_POWER,
        native_unit_of_measurement="kVarh",
        # Was SensorDeviceClass.REACTIVE_POWER, which only supports 'var' unit of measurement.
        # We need a SensorDeviceClass.REACTIVE_ENERGY
        device_class=None,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
)


THREE_PHASE_METER_ENTITY_DESCRIPTIONS: tuple[
    HuaweiSolarSensorEntityDescription, ...
] = (
    HuaweiSolarSensorEntityDescription(
        key=rn.METER_STATUS,
        icon="mdi:electric-switch",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_A_VOLTAGE,
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_B_VOLTAGE,
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_C_VOLTAGE,
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_A_CURRENT,
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_B_CURRENT,
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_C_CURRENT,
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.POWER_METER_ACTIVE_POWER,
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.POWER_METER_REACTIVE_POWER,
        icon="mdi:flash",
        native_unit_of_measurement=POWER_VOLT_AMPERE_REACTIVE,
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_POWER_FACTOR,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_EXPORTED_ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_ACCUMULATED_ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_ACCUMULATED_REACTIVE_POWER,
        native_unit_of_measurement="kVarh",
        # Was SensorDeviceClass.REACTIVE_POWER, which only supports 'var' unit of measurement.
        # We need a SensorDeviceClass.REACTIVE_ENERGY
        device_class=None,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_A_B_VOLTAGE,
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_B_C_VOLTAGE,
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_C_A_VOLTAGE,
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_A_POWER,
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_B_POWER,
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_C_POWER,
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

BATTERY_SENSOR_DESCRIPTIONS: tuple[HuaweiSolarSensorEntityDescription, ...] = (
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_STATE_OF_CAPACITY,
        icon="mdi:home-battery",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_RUNNING_STATUS,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_BUS_VOLTAGE,
        icon="mdi:home-lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_BUS_CURRENT,
        icon="mdi:home-lightning-bolt-outline",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_CHARGE_DISCHARGE_POWER,
        icon="mdi:home-battery-outline",
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_TOTAL_CHARGE,
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.ENERGY,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_TOTAL_DISCHARGE,
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.ENERGY,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_CURRENT_DAY_CHARGE_CAPACITY,
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_CURRENT_DAY_DISCHARGE_CAPACITY,
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add Huawei Solar entry."""
    update_coordinators = hass.data[DOMAIN][entry.entry_id][
        DATA_UPDATE_COORDINATORS
    ]  # type: list[HuaweiSolarUpdateCoordinator]

    configuration_update_coordinators = hass.data[DOMAIN][entry.entry_id][
        DATA_CONFIGURATION_UPDATE_COORDINATORS
    ]  # type: list[HuaweiSolarConfigurationUpdateCoordinator]

    entities_to_add: list[SensorEntity] = []
    for (update_coordinator, configuration_update_coordinator) in \
        zip_longest(update_coordinators, configuration_update_coordinators):
        slave_entities: list[
            HuaweiSolarSensorEntity
            | HuaweiSolarTOUPricePeriodsSensorEntity
            | HuaweiSolarFixedChargingPeriodsSensorEntity
            | HuaweiSolarCapacityControlPeriodsSensorEntity
        ] = []

        bridge = update_coordinator.bridge
        device_infos = update_coordinator.device_infos

        for entity_description in INVERTER_SENSOR_DESCRIPTIONS:
            slave_entities.append(
                HuaweiSolarSensorEntity(
                    update_coordinator, entity_description, device_infos["inverter"]
                )
            )
        slave_entities.append(
            HuaweiSolarAlarmSensorEntity(update_coordinator, device_infos["inverter"])
        )

        for entity_description in get_pv_entity_descriptions(bridge.pv_string_count):
            slave_entities.append(
                HuaweiSolarSensorEntity(
                    update_coordinator, entity_description, device_infos["inverter"]
                )
            )

        if bridge.has_optimizers:
            for entity_description in OPTIMIZER_SENSOR_DESCRIPTIONS:
                slave_entities.append(
                    HuaweiSolarSensorEntity(
                        update_coordinator, entity_description, device_infos["inverter"]
                    )
                )

        if not entry.data.get(CONF_EXCLUDE_POWER_METER):
            if bridge.power_meter_type == rv.MeterType.SINGLE_PHASE:
                for entity_description in SINGLE_PHASE_METER_ENTITY_DESCRIPTIONS:
                    slave_entities.append(
                        HuaweiSolarSensorEntity(
                            update_coordinator,
                            entity_description,
                            device_infos["power_meter"],
                        )
                    )
            elif bridge.power_meter_type == rv.MeterType.THREE_PHASE:
                for entity_description in THREE_PHASE_METER_ENTITY_DESCRIPTIONS:
                    slave_entities.append(
                        HuaweiSolarSensorEntity(
                            update_coordinator,
                            entity_description,
                            device_infos["power_meter"],
                        )
                    )

        if (
            not entry.data.get(CONF_EXCLUDE_BATTERY)
            and bridge.battery_type != rv.StorageProductModel.NONE
        ):
            for entity_description in BATTERY_SENSOR_DESCRIPTIONS:
                slave_entities.append(
                    HuaweiSolarSensorEntity(
                        update_coordinator,
                        entity_description,
                        device_infos["connected_energy_storage"],
                    )
                )

            if configuration_update_coordinator:
                slave_entities.append(
                    HuaweiSolarTOUPricePeriodsSensorEntity(
                        configuration_update_coordinator,
                        update_coordinator.bridge,
                        device_infos["connected_energy_storage"],
                    )
                )
                slave_entities.append(
                    HuaweiSolarFixedChargingPeriodsSensorEntity(
                        configuration_update_coordinator,
                        update_coordinator.bridge,
                        device_infos["connected_energy_storage"],
                    )
                )

                if bridge.supports_capacity_control:
                    slave_entities.append(
                        HuaweiSolarCapacityControlPeriodsSensorEntity(
                            configuration_update_coordinator,
                            update_coordinator.bridge,
                            device_infos["connected_energy_storage"],
                        )
                    )

        entities_to_add.extend(slave_entities)

    optimizer_update_coordinators = hass.data[DOMAIN][entry.entry_id][
        DATA_OPTIMIZER_UPDATE_COORDINATORS
    ]  # type: list[HuaweiSolarOptimizerUpdateCoordinator]

    for update_coordinator in optimizer_update_coordinators:
        optimizer_entities: list[HuaweiSolarOptimizerSensorEntity] = []

        bridge = update_coordinator.bridge
        optimizer_device_infos = update_coordinator.optimizer_device_infos

        for entity_description in OPTIMIZER_DETAIL_SENSOR_DESCRIPTIONS:
            for optimizer_id, device_info in optimizer_device_infos.items():
                optimizer_entities.append(
                    HuaweiSolarOptimizerSensorEntity(
                        update_coordinator,
                        entity_description,
                        optimizer_id,
                        device_info,
                    )
                )

        entities_to_add.extend(optimizer_entities)

    async_add_entities(entities_to_add, True)


class HuaweiSolarSensorEntity(CoordinatorEntity, HuaweiSolarEntity, SensorEntity):
    """Huawei Solar Sensor which receives its data via an DataUpdateCoordinator."""

    entity_description: HuaweiSolarSensorEntityDescription

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        description: HuaweiSolarSensorEntityDescription,
        device_info,
    ) -> None:
        """Batched Huawei Solar Sensor Entity constructor."""
        super().__init__(coordinator)

        self.coordinator = coordinator
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{coordinator.bridge.serial_number}_{description.key}"

        self._register_key = self.entity_description.key
        if "#" in self._register_key:
            self._register_key = self._register_key[0 : self._register_key.find("#")]

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        register = self.coordinator.data.get(self._register_key)
        if register:
            value = register.value
            if self.entity_description.value_conversion_function:
                value = self.entity_description.value_conversion_function(value)

            self._attr_native_value = value
            self._attr_available = True
        else:
            self._attr_native_value = None
            self._attr_available = False

        self.async_write_ha_state()


class HuaweiSolarAlarmSensorEntity(HuaweiSolarSensorEntity):
    """Huawei Solar Sensor for Alarm values.

    These are spread over three registers that are received by the DataUpdateCoordinator.
    """

    ALARM_REGISTERS = [rn.ALARM_1, rn.ALARM_2, rn.ALARM_3]

    DESCRIPTION = HuaweiSolarSensorEntityDescription(
        key="ALARMS",
        translation_key="alarms",
        entity_category=EntityCategory.DIAGNOSTIC,
    )

    def __init__(
        self,
        coordinator: HuaweiSolarUpdateCoordinator,
        device_info,
    ):
        """Huawei Solar Alarm Sensor Entity constructor."""
        super().__init__(
            coordinator, HuaweiSolarAlarmSensorEntity.DESCRIPTION, device_info
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        alarms: list[rv.Alarm] = []
        for alarm_register in HuaweiSolarAlarmSensorEntity.ALARM_REGISTERS:
            alarm_register = self.coordinator.data.get(alarm_register)
            if alarm_register:
                alarms.extend(alarm_register.value)
        if len(alarms) == 0:
            self._attr_native_value = "None"
        else:
            self._attr_native_value = ", ".join(
                [f"[{alarm.level}] {alarm.id}: {alarm.name}" for alarm in alarms]
            )

        self.async_write_ha_state()


def _days_effective_to_str(days: tuple[bool, bool, bool, bool, bool, bool, bool]):
    value = ""
    for i in range(0, 7):  # Sunday is on index 0, but we want to name it day 7
        if days[(i + 1) % 7]:
            value += f"{i+1}"

    return value


def _time_int_to_str(time):
    return f"{time//60:02d}:{time%60:02d}"


class HuaweiSolarTOUPricePeriodsSensorEntity(
    CoordinatorEntity, HuaweiSolarEntity, SensorEntity
):
    """Huawei Solar Sensor for configured TOU periods.

    It shows the number of configured TOU periods, and has the
    contents of them as extended attributes
    """

    def __init__(
        self,
        coordinator: HuaweiSolarConfigurationUpdateCoordinator,
        bridge: HuaweiSolarBridge,
        device_info,
    ) -> None:
        """Huawei Solar TOU Sensor Entity constructor."""
        super().__init__(coordinator)
        self.coordinator = coordinator

        self.entity_description = HuaweiSolarSensorEntityDescription(
            key=rn.STORAGE_TIME_OF_USE_CHARGING_AND_DISCHARGING_PERIODS,
            icon="mdi:calendar-text",
        )

        self._bridge = bridge
        self._attr_device_info = device_info
        self._attr_unique_id = f"{bridge.serial_number}_{self.entity_description.key}"

    def _lg_resu_period_to_text(self, period: LG_RESU_TimeOfUsePeriod):
        return (
            f"{_time_int_to_str(period.start_time)}-{_time_int_to_str(period.end_time)}"
            f"/{period.electricity_price}"
        )

    def _huawei_luna2000_period_to_text(self, period: HUAWEI_LUNA2000_TimeOfUsePeriod):
        return (
            f"{_time_int_to_str(period.start_time)}-{_time_int_to_str(period.end_time)}"
            f"/{_days_effective_to_str(period.days_effective)}"
            f"/{'+' if period.charge_flag == ChargeFlag.CHARGE else '-'}"
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        result: Result = self.coordinator.data.get(
            rn.STORAGE_TIME_OF_USE_CHARGING_AND_DISCHARGING_PERIODS
        )
        data: list[LG_RESU_TimeOfUsePeriod] | list[HUAWEI_LUNA2000_TimeOfUsePeriod] = (
            result.value if result else []
        )

        self._attr_native_value = len(data)

        if len(data) == 0:
            self._attr_extra_state_attributes.clear()
        elif isinstance(data[0], LG_RESU_TimeOfUsePeriod):
            self._attr_extra_state_attributes = {
                f"Period {idx+1}": self._lg_resu_period_to_text(cast(LG_RESU_TimeOfUsePeriod, period))
                for idx, period in enumerate(data)
            }
        elif isinstance(data[0], HUAWEI_LUNA2000_TimeOfUsePeriod):
            self._attr_extra_state_attributes = {
                f"Period {idx+1}": self._huawei_luna2000_period_to_text(period)
                for idx, period in enumerate(data)
            }
        self.async_write_ha_state()


class HuaweiSolarCapacityControlPeriodsSensorEntity(
    CoordinatorEntity, HuaweiSolarEntity, SensorEntity
):
    """Huawei Solar Sensor for configured Capacity Control periods.

    It shows the number of configured capacity control periods, and has the
    contents of them as extended attributes
    """

    def __init__(
        self,
        coordinator: HuaweiSolarConfigurationUpdateCoordinator,
        bridge: HuaweiSolarBridge,
        device_info,
    ) -> None:
        """Huawei Solar Capacity Control Periods Sensor Entity constructor."""
        super().__init__(coordinator)
        self.coordinator = coordinator

        self.entity_description = HuaweiSolarSensorEntityDescription(
            key=rn.STORAGE_CAPACITY_CONTROL_PERIODS,
            icon="mdi:calendar-text",
        )

        self._bridge = bridge
        self._attr_device_info = device_info
        self._attr_unique_id = f"{bridge.serial_number}_{self.entity_description.key}"

    def _period_to_text(self, psp: PeakSettingPeriod):
        return (
            f"{_time_int_to_str(psp.start_time)}"
            f"-{_time_int_to_str(psp.end_time)}"
            f"/{_days_effective_to_str(psp.days_effective)}"
            f"/{psp.power}W"
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        result = self.coordinator.data.get(rn.STORAGE_CAPACITY_CONTROL_PERIODS)

        if result:
            data: list[PeakSettingPeriod] = result.value

            self._attr_native_value = len(data)
            self._attr_extra_state_attributes = {
                f"Period {idx+1}": self._period_to_text(period)
                for idx, period in enumerate(data)
            }
            self._attr_available = True
        else:
            self._attr_native_value = None
            self._attr_extra_state_attributes.clear()
            self._attr_available = False

        self.async_write_ha_state()


class HuaweiSolarFixedChargingPeriodsSensorEntity(
    CoordinatorEntity, HuaweiSolarEntity, SensorEntity
):
    """Huawei Solar Sensor for configured Fixed Charging and Discharging periods.

    It shows the number of configured fixed charging and discharging periods, and has the
    contents of them as extended attributes
    """

    def __init__(
        self,
        coordinator: HuaweiSolarConfigurationUpdateCoordinator,
        bridge: HuaweiSolarBridge,
        device_info,
    ) -> None:
        """Huawei Solar Capacity Control Periods Sensor Entity constructor."""
        super().__init__(coordinator)
        self.coordinator = coordinator

        self.entity_description = HuaweiSolarSensorEntityDescription(
            key=rn.STORAGE_FIXED_CHARGING_AND_DISCHARGING_PERIODS,
            icon="mdi:calendar-text",
        )

        self._bridge = bridge
        self._attr_device_info = device_info
        self._attr_unique_id = f"{bridge.serial_number}_{self.entity_description.key}"

    def _period_to_text(self, cdp: ChargeDischargePeriod):
        return (
            f"{_time_int_to_str(cdp.start_time)}"
            f"-{_time_int_to_str(cdp.end_time)}"
            f"/{cdp.power}W"
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        result: Result = self.coordinator.data.get(
            rn.STORAGE_FIXED_CHARGING_AND_DISCHARGING_PERIODS
        )

        if result:
            data: list[ChargeDischargePeriod] = result.value
            self._attr_native_value = len(data)
            self._attr_extra_state_attributes = {
                f"Period {idx+1}": self._period_to_text(period)
                for idx, period in enumerate(data)
            }
            self._attr_available = True
        else:
            self._attr_native_value = None
            self._attr_extra_state_attributes.clear()
            self._attr_available = False
        self.async_write_ha_state()


class HuaweiSolarOptimizerSensorEntity(
    CoordinatorEntity, HuaweiSolarEntity, SensorEntity
):
    """Huawei Solar Optimizer Sensor which receives its data via an DataUpdateCoordinator."""

    entity_description: HuaweiSolarSensorEntityDescription

    def __init__(
        self,
        coordinator: HuaweiSolarOptimizerUpdateCoordinator,
        description: HuaweiSolarSensorEntityDescription,
        optimizer_id,
        device_info,
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


def get_pv_entity_descriptions(count: int) -> list[HuaweiSolarSensorEntityDescription]:
    """Create the entity descriptions for a PV string."""
    assert 1 <= count <= 24
    result = []

    for idx in range(1, count + 1):
        result.extend(
            [
                HuaweiSolarSensorEntityDescription(
                    key=getattr(rn, f"PV_{idx:02}_VOLTAGE"),
                    icon="mdi:lightning-bolt",
                    native_unit_of_measurement=UnitOfElectricPotential.VOLT,
                    device_class=SensorDeviceClass.VOLTAGE,
                    state_class=SensorStateClass.MEASUREMENT,
                ),
                HuaweiSolarSensorEntityDescription(
                    key=getattr(rn, f"PV_{idx:02}_CURRENT"),
                    icon="mdi:lightning-bolt-outline",
                    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
                    device_class=SensorDeviceClass.CURRENT,
                    state_class=SensorStateClass.MEASUREMENT,
                ),
            ]
        )

    return result
