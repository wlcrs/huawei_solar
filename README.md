# Huawei Solar Sensors

This integration splits out the various values that are fetched from your
Huawei Solar inverter into separate HomeAssistant sensors. These are properly
configured  to allow immediate integration into the HA Energy view.

![sensors](images/sensors-screenshot.png)
![energy-config](images/energy-config.png)

## Installation

1. Install this integration with HACS, or copy the contents of this
repository into the `custom_components/huawei_solar` directory
2. Restart HA
3. Go to `Configuration` -> `Integrations` and click the `+ Add Integration` 
button
4. Select `Huawei Solar` from the list
5. Enter the IP address of your inverter (192.168.200.1 if you are connected to 
its WiFi AP). Select if you have a battery and/or optimizers. The slave id is 
typically 0.

