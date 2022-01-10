"""Constants for the Huawei Solar integration."""
from dataclasses import dataclass

from homeassistant.const import (
    POWER_WATT,
    ENERGY_KILO_WATT_HOUR,
    PERCENTAGE,
)

from homeassistant.components.sensor import (
    SensorStateClass,
    SensorEntityDescription,
    SensorDeviceClass,
)

DOMAIN = "huawei_solar"

# don't overload the poor thing
DEFAULT_COOLDOWN_INTERVAL = 0.1

DATA_MODBUS_CLIENT = "client"


ATTR_MODEL_ID = "model_id"
ATTR_MODEL_NAME = "model_name"
ATTR_SERIAL_NUMBER = "serial_number"

CONF_OPTIMIZERS = "optimizers"
CONF_BATTERY = "battery"
CONF_SLAVE = "slave"

ATTR_DAILY_YIELD = "daily_yield_energy"
ATTR_TOTAL_YIELD = "accumulated_yield_energy"

ATTR_POWER_FACTOR = "power_factor"

ATTR_STORAGE_RUNNING_STATUS = "storage_running_status"

ATTR_STORAGE_TOTAL_CHARGE = "storage_total_charge"
ATTR_STORAGE_TOTAL_DISCHARGE = "storage_total_discharge"

ATTR_STORAGE_DAY_CHARGE = "storage_current_day_charge_capacity"
ATTR_STORAGE_DAY_DISCHARGE = "storage_current_day_discharge_capacity"

ATTR_STORAGE_STATE_OF_CAPACITY = "storage_state_of_capacity"
ATTR_STORAGE_CHARGE_DISCHARGE_POWER = "storage_charge_discharge_power"

ATTR_GRID_EXPORTED = "grid_exported_energy"
ATTR_GRID_ACCUMULATED = "grid_accumulated_energy"

ATTR_ACTIVE_POWER = "active_power"
ATTR_INPUT_POWER = "input_power"
ATTR_POWER_METER_ACTIVE_POWER = "power_meter_active_power"

ATTR_NB_OPTIMIZERS = "nb_optimizers"
ATTR_NB_ONLINE_OPTIMIZERS = "nb_online_optimizers"

ATTR_NB_PV_STRINGS = "nb_pv_strings"
ATTR_RATED_POWER = "rated_power"
ATTR_GRID_STANDARD = "grid_standard"
ATTR_GRID_COUNTRY = "grid_country"

ATTR_DAY_POWER_PEAK = "day_active_power_peak"
ATTR_REACTIVE_POWER = "reactive_power"
ATTR_EFFICIENCY = "efficiency"
ATTR_GRID_FREQUENCY = "grid_frequency"
ATTR_GRID_VOLTAGE = "grid_voltage"
ATTR_GRID_CURRENT = "grid_current"
ATTR_STARTUP_TIME = "startup_time"
ATTR_SHUTDOWN_TIME = "shutdown_time"
ATTR_INTERNAL_TEMPERATURE = "internal_temperature"
ATTR_DEVICE_STATUS = "device_status"
ATTR_SYSTEM_TIME = "system_time"


@dataclass
class HuaweiSolarSensorEntityDescription(SensorEntityDescription):
    pass


SENSOR_TYPES: tuple[HuaweiSolarSensorEntityDescription] = (
    HuaweiSolarSensorEntityDescription(
        key=ATTR_DAILY_YIELD,
        name="Daily Yield",
        icon="mdi:solar-power",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=ATTR_TOTAL_YIELD,
        name="Total Yield",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=ATTR_ACTIVE_POWER,
        name="Active Power",
        native_unit_of_measurement=POWER_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=ATTR_INPUT_POWER,
        name="Input Power",
        native_unit_of_measurement=POWER_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=ATTR_POWER_METER_ACTIVE_POWER,
        name="Power Meter Active Power",
        native_unit_of_measurement=POWER_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=ATTR_POWER_FACTOR,
        name="Power Factor",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=ATTR_GRID_ACCUMULATED,
        name="Grid Consumption",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=ATTR_GRID_EXPORTED,
        name="Grid Exported",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
)

BATTERY_SENSOR_TYPES = (
    HuaweiSolarSensorEntityDescription(
        key=ATTR_STORAGE_TOTAL_CHARGE,
        name="Battery Total Charge",
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.ENERGY,
    ),
    HuaweiSolarSensorEntityDescription(
        key=ATTR_STORAGE_DAY_CHARGE,
        name="Battery Day Charge",
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    HuaweiSolarSensorEntityDescription(
        key=ATTR_STORAGE_TOTAL_DISCHARGE,
        name="Battery Total Discharge",
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        device_class=SensorDeviceClass.ENERGY,
    ),
    HuaweiSolarSensorEntityDescription(
        key=ATTR_STORAGE_DAY_DISCHARGE,
        name="Battery Day Discharge",
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    HuaweiSolarSensorEntityDescription(
        key=ATTR_STORAGE_STATE_OF_CAPACITY,
        name="Battery State of Capacity",
        icon="mdi:home-battery",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=ATTR_STORAGE_CHARGE_DISCHARGE_POWER,
        name="Charge/Discharge Power",
        icon="mdi:flash",
        native_unit_of_measurement=POWER_WATT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
    ),
)

OPTIMIZER_SENSOR_TYPES = (
    HuaweiSolarSensorEntityDescription(
        key=ATTR_NB_ONLINE_OPTIMIZERS,
        name="Optimizers Online",
        icon="mdi:solar-panel",
        native_unit_of_measurement="count",
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.ENERGY,
    ),
)
