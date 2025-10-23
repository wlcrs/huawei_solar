"""Support for Huawei inverter monitoring API."""

from collections.abc import Callable
from dataclasses import dataclass
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
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfReactivePower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_DEVICE_DATAS
from .types import (
    HuaweiSolarConfigEntry,
    HuaweiSolarDeviceData,
    HuaweiSolarEntity,
    HuaweiSolarEntityContext,
    HuaweiSolarEntityDescription,
    HuaweiSolarInverterData,
)
from .update_coordinator import (
    HuaweiSolarOptimizerUpdateCoordinator,
    HuaweiSolarUpdateCoordinator,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True)
class HuaweiSolarSensorEntityDescription(
    HuaweiSolarEntityDescription, SensorEntityDescription
):
    """Huawei Solar Sensor Entity."""

    value_conversion_function: Callable[[Any], str] | None = None

    def __post_init__(self) -> None:
        """Defaults the translation_key to the sensor key."""

        # We use this special setter to be able to set/update the translation_key
        # in this frozen dataclass.
        # cfr. https://docs.python.org/3/library/dataclasses.html#frozen-instances
        object.__setattr__(
            self,
            "translation_key",
            self.translation_key or self.key.replace("#", "_").lower(),
        )

    @property
    def context(self) -> HuaweiSolarEntityContext:
        """Context used by DataUpdateCoordinator."""
        return {"register_names": [rn.RegisterName(self.key.split("#")[0])]}


# Every list in this file describes a group of entities which are related to each other.
# The order of these lists matters, as they need to be in ascending order wrt. to their modbus-register.


INVERTER_SENSOR_DESCRIPTIONS: tuple[HuaweiSolarSensorEntityDescription, ...] = (
    HuaweiSolarSensorEntityDescription(
        key=rn.RATED_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.P_MAX,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.INPUT_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_A_B,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_B_C,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_C_A,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_A_VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_B_VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_C_VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_A_CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_B_CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_C_CURRENT,
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
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
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
        key=rn.INSULATION_RESISTANCE,
        icon="mdi:omega",
        native_unit_of_measurement="MOhm",
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
        key=rn.TOTAL_DC_INPUT_POWER,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.CURRENT_ELECTRICITY_GENERATION_STATISTICS_TIME,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.HOURLY_YIELD_ENERGY,
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.DAILY_YIELD_ENERGY,
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.MONTHLY_YIELD_ENERGY,
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.YEARLY_YIELD_ENERGY,
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STATE_1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_conversion_function=", ".join,
    ),
    HuaweiSolarSensorEntityDescription(
        key=f"{rn.STATE_2}#0",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_conversion_function=lambda value: value[0],
    ),
    HuaweiSolarSensorEntityDescription(
        key=f"{rn.STATE_2}#1",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_conversion_function=lambda value: value[1],
    ),
    HuaweiSolarSensorEntityDescription(
        key=f"{rn.STATE_2}#2",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_conversion_function=lambda value: value[2],
    ),
    HuaweiSolarSensorEntityDescription(
        key=f"{rn.STATE_3}#0",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_conversion_function=lambda value: value[0],
    ),
    HuaweiSolarSensorEntityDescription(
        key=f"{rn.STATE_3}#1",
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
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key="output_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key="input_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key="input_current",
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
        value_conversion_function=lambda alarms: ", ".join(alarms)
        if len(alarms)
        else "None",
        icon="mdi:alarm-light",
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
        translation_key="single_phase_meter_voltage",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_A_CURRENT,
        translation_key="single_phase_meter_current",
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
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
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
        icon="mdi:transmission-tower-import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_ACCUMULATED_ENERGY,
        icon="mdi:transmission-tower-export",
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
        state_class=SensorStateClass.MEASUREMENT,
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
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_B_VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_C_VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_A_CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_B_CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_C_CURRENT,
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
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
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
        icon="mdi:transmission-tower-import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.GRID_ACCUMULATED_ENERGY,
        icon="mdi:transmission-tower-export",
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
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_B_C_VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_GRID_C_A_VOLTAGE,
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

BATTERIES_SENSOR_DESCRIPTIONS: tuple[HuaweiSolarSensorEntityDescription, ...] = (
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_MAXIMUM_CHARGE_POWER,
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_MAXIMUM_DISCHARGE_POWER,
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STORAGE_RATED_CAPACITY,
        icon="mdi:home-battery",
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
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


@dataclass(frozen=True)
class BatteryTemplateEntityDescription:
    """Template for Huawei Solar Battery Sensor Entity Description."""

    battery_1_key: str | None
    battery_2_key: str | None

    translation_key: str
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | str | None = None
    native_unit_of_measurement: str | None = None
    icon: str | None = None
    entity_category: EntityCategory | None = None


BATTERY_TEMPLATE_SENSOR_DESCRIPTIONS: tuple[BatteryTemplateEntityDescription, ...] = (
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_WORKING_MODE_B,
        battery_2_key=None,
        translation_key="battery_working_mode",
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_CURRENT_DAY_CHARGE_CAPACITY,
        battery_2_key=rn.STORAGE_UNIT_2_CURRENT_DAY_CHARGE_CAPACITY,
        translation_key="storage_current_day_charge_capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_CURRENT_DAY_DISCHARGE_CAPACITY,
        battery_2_key=rn.STORAGE_UNIT_2_CURRENT_DAY_DISCHARGE_CAPACITY,
        translation_key="storage_current_day_discharge_capacity",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BUS_CURRENT,
        battery_2_key=rn.STORAGE_UNIT_2_BUS_CURRENT,
        translation_key="storage_bus_current",
        icon="mdi:home-lightning-bolt-outline",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.CURRENT,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BUS_VOLTAGE,
        battery_2_key=rn.STORAGE_UNIT_2_BUS_VOLTAGE,
        translation_key="storage_bus_voltage",
        icon="mdi:home-lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.VOLTAGE,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_TEMPERATURE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_TEMPERATURE,
        translation_key="bms_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_REMAINING_CHARGE_DIS_CHARGE_TIME,
        battery_2_key=None,
        translation_key="battery_remaining_charge_discharge_time",
        icon="mdi:timer-sand",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_TOTAL_CHARGE,
        battery_2_key=rn.STORAGE_UNIT_2_TOTAL_CHARGE,
        translation_key="storage_total_charge",
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_TOTAL_DISCHARGE,
        battery_2_key=rn.STORAGE_UNIT_2_TOTAL_DISCHARGE,
        translation_key="storage_total_discharge",
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_STATE_OF_CAPACITY,
        battery_2_key=rn.STORAGE_UNIT_2_STATE_OF_CAPACITY,
        translation_key="storage_state_of_capacity",
        icon="mdi:home-battery",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_RUNNING_STATUS,
        battery_2_key=rn.STORAGE_UNIT_2_RUNNING_STATUS,
        translation_key="running_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_CHARGE_DISCHARGE_POWER,
        battery_2_key=rn.STORAGE_UNIT_2_CHARGE_DISCHARGE_POWER,
        translation_key="storage_charge_discharge_power",
        icon="mdi:home-battery-outline",
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_SOH_CALIBRATION_STATUS,
        battery_2_key=None,
        translation_key="soh_calibration_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_1_MAXIMUM_TEMPERATURE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_1_MAXIMUM_TEMPERATURE,
        translation_key="pack_1_max_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_1_MINIMUM_TEMPERATURE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_1_MINIMUM_TEMPERATURE,
        translation_key="pack_1_min_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_2_MAXIMUM_TEMPERATURE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_2_MAXIMUM_TEMPERATURE,
        translation_key="pack_2_max_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_2_MINIMUM_TEMPERATURE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_2_MINIMUM_TEMPERATURE,
        translation_key="pack_2_min_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_3_MAXIMUM_TEMPERATURE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_3_MAXIMUM_TEMPERATURE,
        translation_key="pack_3_max_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_3_MINIMUM_TEMPERATURE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_3_MINIMUM_TEMPERATURE,
        translation_key="pack_3_min_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_1_WORKING_STATUS,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_1_WORKING_STATUS,
        translation_key="pack_1_working_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_2_WORKING_STATUS,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_2_WORKING_STATUS,
        translation_key="pack_2_working_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_3_WORKING_STATUS,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_3_WORKING_STATUS,
        translation_key="pack_3_working_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_1_FIRMWARE_VERSION,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_1_FIRMWARE_VERSION,
        translation_key="pack_1_firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_1_SERIAL_NUMBER,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_1_SERIAL_NUMBER,
        translation_key="pack_1_serial_number",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_1_STATE_OF_CAPACITY,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_1_STATE_OF_CAPACITY,
        translation_key="pack_1_state_of_capacity",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_1_CHARGE_DISCHARGE_POWER,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_1_CHARGE_DISCHARGE_POWER,
        translation_key="pack_1_charge_discharge_power",
        icon="mdi:home-battery-outline",
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_1_VOLTAGE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_1_VOLTAGE,
        translation_key="pack_1_voltage",
        icon="mdi:home-lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.VOLTAGE,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_1_CURRENT,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_1_CURRENT,
        translation_key="pack_1_current",
        icon="mdi:home-lightning-bolt-outline",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.CURRENT,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_1_SOH_CALIBRATION_STATUS,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_1_SOH_CALIBRATION_STATUS,
        translation_key="pack_1_soh_calibration_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_1_TOTAL_CHARGE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_1_TOTAL_CHARGE,
        translation_key="pack_1_total_charge",
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_1_TOTAL_DISCHARGE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_1_TOTAL_DISCHARGE,
        translation_key="pack_1_total_discharge",
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    # Pack 2 added features
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_2_FIRMWARE_VERSION,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_2_FIRMWARE_VERSION,
        translation_key="pack_2_firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_2_SERIAL_NUMBER,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_2_SERIAL_NUMBER,
        translation_key="pack_2_serial_number",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_2_STATE_OF_CAPACITY,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_2_STATE_OF_CAPACITY,
        translation_key="pack_2_state_of_capacity",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_2_CHARGE_DISCHARGE_POWER,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_2_CHARGE_DISCHARGE_POWER,
        translation_key="pack_2_charge_discharge_power",
        icon="mdi:home-battery-outline",
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_2_VOLTAGE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_2_VOLTAGE,
        translation_key="pack_2_voltage",
        icon="mdi:home-lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.VOLTAGE,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_2_CURRENT,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_2_CURRENT,
        translation_key="pack_2_current",
        icon="mdi:home-lightning-bolt-outline",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.CURRENT,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_2_SOH_CALIBRATION_STATUS,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_2_SOH_CALIBRATION_STATUS,
        translation_key="pack_2_soh_calibration_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_2_TOTAL_CHARGE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_2_TOTAL_CHARGE,
        translation_key="pack_2_total_charge",
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_2_TOTAL_DISCHARGE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_2_TOTAL_DISCHARGE,
        translation_key="pack_2_total_discharge",
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    # Pack 3 added features
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_3_FIRMWARE_VERSION,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_3_FIRMWARE_VERSION,
        translation_key="pack_3_firmware_version",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_3_SERIAL_NUMBER,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_3_SERIAL_NUMBER,
        translation_key="pack_3_serial_number",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_3_WORKING_STATUS,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_3_WORKING_STATUS,
        translation_key="pack_3_working_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_3_STATE_OF_CAPACITY,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_3_STATE_OF_CAPACITY,
        translation_key="pack_3_state_of_capacity",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_3_CHARGE_DISCHARGE_POWER,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_3_CHARGE_DISCHARGE_POWER,
        translation_key="pack_3_charge_discharge_power",
        icon="mdi:home-battery-outline",
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_3_VOLTAGE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_3_VOLTAGE,
        translation_key="pack_3_voltage",
        icon="mdi:home-lightning-bolt",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.VOLTAGE,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_3_CURRENT,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_3_CURRENT,
        translation_key="pack_3_current",
        icon="mdi:home-lightning-bolt-outline",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.CURRENT,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_3_SOH_CALIBRATION_STATUS,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_3_SOH_CALIBRATION_STATUS,
        translation_key="pack_3_soh_calibration_status",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_3_TOTAL_CHARGE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_3_TOTAL_CHARGE,
        translation_key="pack_3_total_charge",
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    BatteryTemplateEntityDescription(
        battery_1_key=rn.STORAGE_UNIT_1_BATTERY_PACK_3_TOTAL_DISCHARGE,
        battery_2_key=rn.STORAGE_UNIT_2_BATTERY_PACK_3_TOTAL_DISCHARGE,
        translation_key="pack_3_total_discharge",
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
)


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

    if ucs.device.power_meter_type == rv.MeterType.SINGLE_PHASE:
        assert ucs.power_meter_update_coordinator
        assert ucs.power_meter
        entities_to_add.extend(
            HuaweiSolarSensorEntity(
                ucs.power_meter_update_coordinator, entity_description, ucs.power_meter
            )
            for entity_description in SINGLE_PHASE_METER_ENTITY_DESCRIPTIONS
        )

    elif ucs.device.power_meter_type == rv.MeterType.THREE_PHASE:
        assert ucs.power_meter_update_coordinator
        assert ucs.power_meter
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

    if ucs.device.battery_type != rv.StorageProductModel.NONE:
        assert ucs.energy_storage_update_coordinator
        assert ucs.connected_energy_storage

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


EMMA_SENSOR_DESCRIPTIONS: tuple[HuaweiSolarSensorEntityDescription, ...] = (
    HuaweiSolarSensorEntityDescription(
        key=rn.INVERTER_TOTAL_ABSORBED_ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ENERGY_CHARGED_TODAY,
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.TOTAL_CHARGED_ENERGY,
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ENERGY_DISCHARGED_TODAY,
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.TOTAL_DISCHARGED_ENERGY,
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ESS_CHARGEABLE_ENERGY,
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ESS_DISCHARGEABLE_ENERGY,
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.RATED_ESS_CAPACITY,
        icon="mdi:home-battery-outline",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.CONSUMPTION_TODAY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.TOTAL_ENERGY_CONSUMPTION,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.FEED_IN_TO_GRID_TODAY,
        icon="mdi:transmission-tower-import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.TOTAL_FEED_IN_TO_GRID,
        icon="mdi:transmission-tower-import",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SUPPLY_FROM_GRID_TODAY,
        icon="mdi:transmission-tower-export",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.TOTAL_SUPPLY_FROM_GRID,
        icon="mdi:transmission-tower-export",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.INVERTER_ENERGY_YIELD_TODAY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.INVERTER_TOTAL_ENERGY_YIELD,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PV_YIELD_TODAY,
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.TOTAL_PV_ENERGY_YIELD,
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PV_OUTPUT_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LOAD_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.FEED_IN_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.BATTERY_CHARGE_DISCHARGE_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.INVERTER_RATED_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.INVERTER_ACTIVE_POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.STATE_OF_CAPACITY,
        icon="mdi:home-battery",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ESS_CHARGEABLE_CAPACITY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ESS_DISCHARGEABLE_CAPACITY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.BACKUP_POWER_STATE_OF_CHARGE,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_A_VOLTAGE_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_B_VOLTAGE_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_C_VOLTAGE_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_A_B_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_B_C_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_C_A_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_A_CURRENT_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_B_CURRENT_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_C_CURRENT_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_POWER_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.POWER_FACTOR_BUILT_IN_ENERGY,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.APPARENT_POWER_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_A_ACTIVE_POWER_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_B_ACTIVE_POWER_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_C_ACTIVE_POWER_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.TOTAL_ACTIVE_ENERGY_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.TOTAL_NEGATIVE_ACTIVE_ENERGY_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.TOTAL_POSITIVE_ACTIVE_ENERGY_BUILT_IN_ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_A_VOLTAGE_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_B_VOLTAGE_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_C_VOLTAGE_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_A_B_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_B_C_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.LINE_VOLTAGE_C_A_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_A_CURRENT_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_B_CURRENT_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_C_CURRENT_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.ACTIVE_POWER_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.POWER_FACTOR_EXTERNAL_ENERGY,
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.APPARENT_POWER_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_A_ACTIVE_POWER_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_B_ACTIVE_POWER_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.PHASE_C_ACTIVE_POWER_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.TOTAL_ACTIVE_ENERGY_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.TOTAL_NEGATIVE_ACTIVE_ENERGY_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.TOTAL_POSITIVE_ACTIVE_ENERGY_EXTERNAL_ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        entity_registry_enabled_default=False,
    ),
)


def create_emma_entities(
    ucs: HuaweiSolarDeviceData,
) -> list["SensorEntity"]:
    """Create EMMA sensor entities."""
    assert isinstance(ucs.device, EMMADevice)

    entities: list[SensorEntity] = [
        HuaweiSolarSensorEntity(
            ucs.update_coordinator, entity_description, ucs.device_info
        )
        for entity_description in EMMA_SENSOR_DESCRIPTIONS
    ]

    assert ucs.configuration_update_coordinator
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


CHARGER_SENSOR_DESCRIPTIONS: tuple[HuaweiSolarSensorEntityDescription, ...] = (
    HuaweiSolarSensorEntityDescription(
        key=rn.CHARGER_RATED_POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.CHARGER_PHASE_A_VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.CHARGER_PHASE_B_VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.CHARGER_PHASE_C_VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.CHARGER_TOTAL_ENERGY_CHARGED,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.CHARGER_TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


SDONGLE_SENSOR_DESCRIPTIONS: tuple[HuaweiSolarSensorEntityDescription, ...] = (
    HuaweiSolarSensorEntityDescription(
        key=rn.SDONGLE_TOTAL_INPUT_POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SDONGLE_LOAD_POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SDONGLE_GRID_POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SDONGLE_TOTAL_BATTERY_POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SDONGLE_TOTAL_ACTIVE_POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

SMARTLOGGER_SENSOR_DESCRIPTIONS: tuple[HuaweiSolarSensorEntityDescription, ...] = (
    HuaweiSolarSensorEntityDescription(
        key=rn.SMARTLOGGER_INPUT_POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SMARTLOGGER_ACTIVE_POWER,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SMARTLOGGER_POWER_SUPPLY_FROM_GRID_TODAY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SMARTLOGGER_TOTAL_POWER_SUPPLY_FROM_GRID,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SMARTLOGGER_ENERGY_CHARGED_TODAY,
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SMARTLOGGER_ENERGY_DISCHARGED_TODAY,
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SMARTLOGGER_TOTAL_ENERGY_CHARGED,
        icon="mdi:battery-plus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SMARTLOGGER_TOTAL_ENERGY_DISCHARGE_D,
        icon="mdi:battery-minus-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SMARTLOGGER_SOC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SMARTLOGGER_SOH,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SMARTLOGGER_SOE,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SMARTLOGGER_TOTAL_ENERGY_YIELD,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
    ),
    HuaweiSolarSensorEntityDescription(
        key=rn.SMARTLOGGER_YIELD_TODAY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
)


def create_charger_entities(
    ucs: HuaweiSolarDeviceData,
) -> list["HuaweiSolarSensorEntity"]:
    """Create Charger sensor entities."""
    assert isinstance(ucs.device, SChargerDevice)

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
    assert isinstance(ucs.device, SDongleDevice)

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
    assert isinstance(ucs.device, SmartLoggerDevice)

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
    ):
        """Huawei Solar Alarm Sensor Entity constructor."""
        super().__init__(
            coordinator,
            HuaweiSolarAlarmSensorEntity.DESCRIPTION,
            device_info,
            {"register_names": HuaweiSolarAlarmSensorEntity.ALARM_REGISTERS},
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        available = False

        if self.coordinator.data:
            alarms: list[rv.Alarm] = []
            for alarm_register in HuaweiSolarAlarmSensorEntity.ALARM_REGISTERS:
                alarm_result = self.coordinator.data.get(alarm_register)
                if alarm_result:
                    available = True
                    alarms.extend(alarm_result.value)
            if len(alarms) == 0:
                self._attr_native_value = "None"
            else:
                self._attr_native_value = ", ".join(
                    [f"[{alarm.level}] {alarm.id}: {alarm.name}" for alarm in alarms]
                )
        else:
            self._attr_native_value = None

        self._attr_available = available
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
            else:
                assert mode == rv.StorageForcibleChargeDischarge.DISCHARGE
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


def get_pv_entity_descriptions(count: int) -> list[HuaweiSolarSensorEntityDescription]:
    """Create the entity descriptions for a PV string."""
    assert 1 <= count <= 24
    result = []

    for idx in range(1, count + 1):
        result.extend(
            [
                HuaweiSolarSensorEntityDescription(
                    key=getattr(rn, f"PV_{idx:02}_VOLTAGE"),
                    native_unit_of_measurement=UnitOfElectricPotential.VOLT,
                    device_class=SensorDeviceClass.VOLTAGE,
                    state_class=SensorStateClass.MEASUREMENT,
                ),
                HuaweiSolarSensorEntityDescription(
                    key=getattr(rn, f"PV_{idx:02}_CURRENT"),
                    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
                    device_class=SensorDeviceClass.CURRENT,
                    state_class=SensorStateClass.MEASUREMENT,
                ),
            ]
        )

    return result
