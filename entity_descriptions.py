"""Entity descriptions for the Huawei Solar integration.

This is split into a separate file because it contains a mix of different entity types,
due to the need to group and order them properly according to their modbus register number.
"""

from dataclasses import dataclass

import huawei_solar.register_names as rn

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    ELECTRIC_CURRENT_AMPERE,
    ELECTRIC_POTENTIAL_VOLT,
    ENERGY_KILO_WATT_HOUR,
    PERCENTAGE,
    POWER_WATT,
    TEMP_CELSIUS,
)
from homeassistant.helpers.entity import EntityCategory


@dataclass
class HuaweiSolarEntityDescriptionMixin:
    """A Huawei Solar Entity Description."""


@dataclass
class HuaweiSolarSensorEntityDescription(
    HuaweiSolarEntityDescriptionMixin, SensorEntityDescription
):
    """Huawei Solar Sensor Entity."""


# Every list in this file describes a group of entities which are related to each other.
# The order of these lists matters, as they need to be in ascending order wrt. to their modbus-register.


INVERTER_ENTITY_DESCRIPTIONS: list[HuaweiSolarEntityDescriptionMixin] = [
    HuaweiSolarSensorEntityDescription(
        key=rn.INPUT_POWER,
        name="Input Power",
        native_unit_of_measurement=POWER_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_A_B,
        name="A-B line voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_B_C,
        name="B-C line voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_C_A,
        name="C-A line voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_A_VOLTAGE,
        name="Phase A Voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_B_VOLTAGE,
        name="Phase B Voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_C_VOLTAGE,
        name="Phase C Voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_A_CURRENT,
        name="Phase A Current",
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_B_CURRENT,
        name="Phase B Current",
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_C_CURRENT,
        name="Phase C Current",
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.DAY_ACTIVE_POWER_PEAK,
        name="Day Active Power Peak",
        native_unit_of_measurement=POWER_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_POWER,
        name="Active Power",
        native_unit_of_measurement=POWER_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.REACTIVE_POWER,
        name="Reactive Power",
        native_unit_of_measurement="var",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.POWER_FACTOR,
        name="Power Factor",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.EFFICIENCY,
        name="Efficiency",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.INTERNAL_TEMPERATURE,
        name="Internal Temperature",
        native_unit_of_measurement=TEMP_CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.DEVICE_STATUS,
        name="Device Status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STARTUP_TIME,
        name="Startup Time",
        icon="mdi:weather-sunset-up",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SHUTDOWN_TIME,
        name="Shutdown Time",
        icon="mdi:weather-sunset-down",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACCUMULATED_YIELD_ENERGY,
        name="Total Yield",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.DAILY_YIELD_ENERGY,
        name="Daily Yield",
        icon="mdi:solar-power",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
]


SINGLE_PHASE_METER_ENTITY_DESCRIPTIONS: list[HuaweiSolarEntityDescriptionMixin] = [
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_A_VOLTAGE,
        name="Grid Voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_A_CURRENT,
        name="Grid Current",
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.POWER_METER_ACTIVE_POWER,
        name="Active Power",
        icon="mdi:flash",
        native_unit_of_measurement=POWER_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.POWER_METER_REACTIVE_POWER,
        name="Reactive Power",
        icon="mdi:flash-outline",
        native_unit_of_measurement="var",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_POWER_FACTOR,
        name="Power Factor",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_FREQUENCY,
        name="Grid Frequency",
        native_unit_of_measurement="Hz",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_EXPORTED_ENERGY,
        name="Grid Exported",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_ACCUMULATED_ENERGY,
        name="Grid Consumption",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_ACCUMULATED_REACTIVE_POWER,
        name="Grid Reactive Power",
        native_unit_of_measurement="kVarh",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_A_POWER,
        name="Grid Active Power",
        icon="mdi:flash",
        native_unit_of_measurement=POWER_WATT,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
]


THREE_PHASE_METER_ENTITY_DESCRIPTIONS: list[HuaweiSolarEntityDescriptionMixin] = [
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_A_VOLTAGE,
        name="Grid A phase voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_B_VOLTAGE,
        name="Grid B phase voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_C_VOLTAGE,
        name="Grid C phase voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_A_CURRENT,
        name="Grid Phase A Current",
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_B_CURRENT,
        name="Grid Phase B Current",
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_C_CURRENT,
        name="Grid Phase C Current",
        icon="mdi:lightning-bolt-outline",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.POWER_METER_ACTIVE_POWER,
        name="Active Power",
        icon="mdi:flash",
        native_unit_of_measurement=POWER_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.POWER_METER_REACTIVE_POWER,
        name="Reactive Power",
        icon="mdi:flash-outline",
        native_unit_of_measurement="var",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_POWER_FACTOR,
        name="Power Factor",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_FREQUENCY,
        name="Grid Frequency",
        native_unit_of_measurement="Hz",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_EXPORTED_ENERGY,
        name="Grid Exported",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_ACCUMULATED_ENERGY,
        name="Grid Consumption",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_ACCUMULATED_REACTIVE_POWER,
        name="Grid Reactive Power",
        native_unit_of_measurement="kVarh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_A_B_VOLTAGE,
        name="Grid A-B line voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_B_C_VOLTAGE,
        name="Grid B-C line voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_C_A_VOLTAGE,
        name="Grid C-A line voltage",
        icon="mdi:lightning-bolt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_A_POWER,
        name="Grid Phase A Active Power",
        icon="mdi:flash",
        native_unit_of_measurement=POWER_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_B_POWER,
        name="Grid Phase B Active Power",
        icon="mdi:flash",
        native_unit_of_measurement=POWER_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_C_POWER,
        name="Grid Phase C Active Power",
        icon="mdi:flash",
        native_unit_of_measurement=POWER_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
]

BATTERY_ENTITY_DESCRIPTIONS: list[HuaweiSolarEntityDescriptionMixin] = [
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_STATE_OF_CAPACITY,
        name="Battery State of Capacity",
        icon="mdi:home-battery",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_BUS_VOLTAGE,
        name="Storage Bus Voltage",
        icon="mdi:home-lightning-bolt",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_BUS_CURRENT,
        name="Storage Bus Current",
        icon="mdi:home-lightning-bolt-outline",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_CHARGE_DISCHARGE_POWER,
        name="Charge/Discharge Power",
        icon="mdi:home-battery-outline",
        native_unit_of_measurement=POWER_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_TOTAL_CHARGE,
        name="Battery Total Charge",
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.ENERGY,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_TOTAL_DISCHARGE,
        name="Battery Total Discharge",
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.ENERGY,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_CURRENT_DAY_CHARGE_CAPACITY,
        name="Battery Day Charge",
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_CURRENT_DAY_DISCHARGE_CAPACITY,
        name="Battery Day Discharge",
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
]


def get_pv_entity_descriptions(idx: int):
    """Create the entity descriptions for a PV string."""
    assert 1 <= idx <= 24

    return [
        HuaweiSolarSensorEntityDescription(
            key=getattr(rn, f"PV_{idx:02}_VOLTAGE"),
            name=f"PV {idx} Voltage",
            icon="mdi:lightning-bolt",
            native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        HuaweiSolarSensorEntityDescription(
            key=getattr(rn, f"PV_{idx:02}_CURRENT"),
            name=f"PV {idx} Current",
            icon="mdi:lightning-bolt-outline",
            native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ]
