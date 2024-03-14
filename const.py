"""Constants for the Huawei Solar integration."""
from datetime import timedelta

DOMAIN = "huawei_solar"
DEFAULT_PORT = 502
DEFAULT_SLAVE_ID = 0
DEFAULT_SERIAL_SLAVE_ID = 1
DEFAULT_USERNAME = "installer"
DEFAULT_PASSWORD = "00000a"

CONF_SLAVE_IDS = "slave_ids"
CONF_ENABLE_PARAMETER_CONFIGURATION = "enable_parameter_configuration"
CONF_EXCLUDE_BATTERY = "exclude_battery"
CONF_EXCLUDE_OPTIMIZERS = "exclude_optimizers"
CONF_EXCLUDE_POWER_METER = "exclude_power_meter"

DATA_BRIDGES_WITH_DEVICEINFOS = "bridges"
DATA_UPDATE_COORDINATORS = "update_coordinators"
DATA_CONFIGURATION_UPDATE_COORDINATORS = "configuration_update_coordinators"
DATA_OPTIMIZER_UPDATE_COORDINATORS = "optimizer_update_coordinators"

UPDATE_INTERVAL = timedelta(seconds=30)
UPDATE_TIMEOUT = timedelta(seconds=29)
# configuration can only change when edited through FusionSolar web or app
CONFIGURATION_UPDATE_INTERVAL = timedelta(minutes=15)
CONFIGURATION_UPDATE_TIMEOUT = timedelta(minutes=1)
# optimizer data is only refreshed every 5 minutes by the inverter.
OPTIMIZER_UPDATE_INTERVAL = timedelta(minutes=5)
OPTIMIZER_UPDATE_TIMEOUT = timedelta(minutes=1)

SERVICE_FORCIBLE_CHARGE = "forcible_charge"
SERVICE_FORCIBLE_DISCHARGE = "forcible_discharge"
SERVICE_FORCIBLE_CHARGE_SOC = "forcible_charge_soc"
SERVICE_FORCIBLE_DISCHARGE_SOC = "forcible_discharge_soc"
SERVICE_STOP_FORCIBLE_CHARGE = "stop_forcible_charge"

SERVICE_RESET_MAXIMUM_FEED_GRID_POWER = "reset_maximum_feed_grid_power"
SERVICE_SET_DI_ACTIVE_POWER_SCHEDULING = "set_di_active_power_scheduling"
SERVICE_SET_ZERO_POWER_GRID_CONNECTION = "set_zero_power_grid_connection"
SERVICE_SET_MAXIMUM_FEED_GRID_POWER = "set_maximum_feed_grid_power"
SERVICE_SET_MAXIMUM_FEED_GRID_POWER_PERCENT = "set_maximum_feed_grid_power_percent"
SERVICE_SET_TOU_PERIODS = "set_tou_periods"
SERVICE_SET_CAPACITY_CONTROL_PERIODS = "set_capacity_control_periods"
SERVICE_SET_FIXED_CHARGE_PERIODS = "set_fixed_charge_periods"

SERVICES = (
    SERVICE_FORCIBLE_CHARGE,
    SERVICE_FORCIBLE_DISCHARGE,
    SERVICE_FORCIBLE_CHARGE_SOC,
    SERVICE_FORCIBLE_DISCHARGE_SOC,
    SERVICE_STOP_FORCIBLE_CHARGE,
    SERVICE_RESET_MAXIMUM_FEED_GRID_POWER,
    SERVICE_SET_DI_ACTIVE_POWER_SCHEDULING,
    SERVICE_SET_ZERO_POWER_GRID_CONNECTION,
    SERVICE_SET_MAXIMUM_FEED_GRID_POWER,
    SERVICE_SET_TOU_PERIODS,
    SERVICE_SET_CAPACITY_CONTROL_PERIODS,
    SERVICE_SET_FIXED_CHARGE_PERIODS,
)
