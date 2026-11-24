"""Tests for the value conversion of the SmartLoad sensors."""

from typing import Any
from unittest.mock import Mock, patch

import pytest
from custom_components.huawei_solar.sensor import (
    SMARTLOAD_SENSOR_DESCRIPTIONS,
    HuaweiSolarSensorEntity,
)
from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.registers import REGISTERS

DESCRIPTIONS = {
    description.key: description for description in SMARTLOAD_SENSOR_DESCRIPTIONS
}


def _state(key: str, raw: int) -> Any:
    """Decode a raw register value like the library and pass it through the sensor entity."""
    coordinator = Mock()
    coordinator.device.serial_number = "SN"
    coordinator.data = {
        rn.RegisterName(key): REGISTERS[rn.RegisterName(key)].decode((raw,))
    }
    entity = HuaweiSolarSensorEntity(coordinator, DESCRIPTIONS[key], Mock())
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()
    assert entity.available
    return entity.native_value


@pytest.mark.parametrize(
    "key", [rn.SMARTLOAD_SWITCH_STATUS, rn.SMARTLOAD_OFF_GRID_AUTO_CONTROL]
)
@pytest.mark.parametrize(("raw", "expected"), [(0, "off"), (1, "on"), (0xFFFF, None)])
def test_on_off_sensors(key: str, raw: int, expected: str | None) -> None:
    """0 and 1 map to off/on, the invalid value 65535 stays unknown instead of off."""
    value = _state(key, raw)

    assert value == expected
    assert value is None or value in DESCRIPTIONS[key].options


@pytest.mark.parametrize(
    ("raw", "expected"), [(0, "basic"), (1, "battery"), (0xFFFF, None)]
)
def test_off_grid_mode_sensor(raw: int, expected: str | None) -> None:
    """The off-grid mode maps to its options and does not fail on the invalid value."""
    value = _state(rn.SMARTLOAD_OFF_GRID_MODE, raw)

    assert value == expected
    assert value is None or value in DESCRIPTIONS[rn.SMARTLOAD_OFF_GRID_MODE].options


@pytest.mark.parametrize(
    ("key", "raw", "expected"),
    [
        (rn.SMARTLOAD_RATED_POWER, 3000, 3000),
        (rn.SMARTLOAD_RATED_POWER, 0xFFFF, None),
        (rn.SMARTLOAD_OFF_GRID_STOP_SOC, 70, 70),
        (rn.SMARTLOAD_OFF_GRID_RESUME_SOC, 0xFFFF, None),
    ],
)
def test_numeric_sensors(key: str, raw: int, expected: int | None) -> None:
    """Numeric values pass through, the invalid value 65535 stays unknown."""
    assert _state(key, raw) == expected


def test_off_grid_mode_options_cover_all_values() -> None:
    """Every library enum value has a matching option."""
    options = DESCRIPTIONS[rn.SMARTLOAD_OFF_GRID_MODE].options
    assert sorted(mode.name.lower() for mode in rv.SmartLoadOffGridMode) == sorted(
        options
    )
