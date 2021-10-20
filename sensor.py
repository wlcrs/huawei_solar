"""Support for Huawei inverter monitoring API."""
import logging
import backoff

from huawei_solar import HuaweiSolar, ConnectionException, ReadException

from .const import (
    DOMAIN,
    DATA_MODBUS_CLIENT,
    CONF_BATTERY,
    CONF_OPTIMIZERS,
    OPTIMIZER_SENSOR_TYPES,
    HuaweiSolarSensorEntityDescription,
    SENSOR_TYPES,
    BATTERY_SENSOR_TYPES,
)

import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import SensorEntity


async def async_setup_entry(hass, entry, async_add_entities):
    """Add Huawei Solar entry"""
    inverter = hass.data[DOMAIN][entry.entry_id][DATA_MODBUS_CLIENT]

    serial_number = inverter.get("serial_number").value
    name = inverter.get("model_name").value

    device_info = {
        "identifiers": {(DOMAIN, name, serial_number)},
        "name": name,
        "manufacturer": "Huawei",
        "serial_number": serial_number,
    }

    async_add_entities(
        [HuaweiSolarSensor(inverter, descr, device_info) for descr in SENSOR_TYPES],
        True,
    )

    if entry.data[CONF_BATTERY]:
        async_add_entities(
            [
                HuaweiSolarSensor(inverter, descr, device_info)
                for descr in BATTERY_SENSOR_TYPES
            ],
            True,
        )

    if entry.data[CONF_OPTIMIZERS]:
        async_add_entities(
            [
                HuaweiSolarSensor(inverter, descr, device_info)
                for descr in OPTIMIZER_SENSOR_TYPES
            ],
            True,
        )


class HuaweiSolarSensor(SensorEntity):

    entity_description: HuaweiSolarSensorEntityDescription

    def __init__(
        self,
        inverter: HuaweiSolar,
        description: HuaweiSolarSensorEntityDescription,
        device_info,
    ):

        self._inverter = inverter
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{device_info['serial_number']}_{description.key}"

        self._state = None

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    def update(self):
        """Get the latest data from the Huawei solar inverter."""

        @backoff.on_exception(backoff.expo, (ConnectionException, ReadException), max_time=120)
        def _get_value():
            return self._inverter.get(self.entity_description.key).value

        self._state = _get_value()
