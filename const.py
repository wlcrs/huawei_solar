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


DATA_UPDATE_COORDINATORS = "update_coordinators"
DATA_OPTIMIZER_UPDATE_COORDINATORS = "optimizer_update_coordinators"

UPDATE_INTERVAL = timedelta(seconds=30)
# optimizer data is only refreshed every 5 minutes by the inverter.
OPTIMIZER_UPDATE_INTERVAL = timedelta(minutes=5)

SERVICE_FORCIBLE_CHARGE = "forcible_charge"
SERVICE_FORCIBLE_DISCHARGE = "forcible_discharge"
SERVICE_FORCIBLE_CHARGE_SOC = "forcible_charge_soc"
SERVICE_FORCIBLE_DISCHARGE_SOC = "forcible_discharge_soc"
SERVICE_STOP_FORCIBLE_CHARGE = "stop_forcible_charge"

SERVICE_RESET_MAXIMUM_FEED_GRID_POWER = "reset_maximum_feed_grid_power"
SERVICE_SET_MAXIMUM_FEED_GRID_POWER = "set_maximum_feed_grid_power"
SERVICE_SET_MAXIMUM_FEED_GRID_POWER_PERCENT = "set_maximum_feed_grid_power_percent"

SERVICES = (
    SERVICE_FORCIBLE_CHARGE,
    SERVICE_FORCIBLE_DISCHARGE,
    SERVICE_FORCIBLE_CHARGE_SOC,
    SERVICE_FORCIBLE_DISCHARGE_SOC,
    SERVICE_STOP_FORCIBLE_CHARGE,
)
