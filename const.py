"""Constants for the Huawei Solar integration."""
from datetime import timedelta

DOMAIN = "huawei_solar"
DEFAULT_PORT = 502
DEFAULT_SLAVE_ID = 0

CONF_SLAVE_IDS = "slave_ids"

DATA_UPDATE_COORDINATORS = "update_coordinators"

UPDATE_INTERVAL = timedelta(seconds=30)

SERVICE_FORCIBLE_CHARGE = "forcible_charge"
SERVICE_FORCIBLE_DISCHARGE = "forcible_discharge"
SERVICE_FORCIBLE_CHARGE_SOC = "forcible_charge_soc"
SERVICE_FORCIBLE_DISCHARGE_SOC = "forcible_discharge_soc"

SERVICES = (
    SERVICE_FORCIBLE_CHARGE,
    SERVICE_FORCIBLE_DISCHARGE,
    SERVICE_FORCIBLE_CHARGE_SOC,
    SERVICE_FORCIBLE_DISCHARGE_SOC,
)
