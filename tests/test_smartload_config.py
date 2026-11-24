"""Tests for the writable SmartLoad settings (number, select and switch entities)."""

from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from custom_components.huawei_solar.number import (
    SMARTLOAD_NUMBER_DESCRIPTIONS,
    HuaweiSolarNumberEntity,
    get_number_registers,
)
from custom_components.huawei_solar.select import (
    SMARTLOAD_SELECT_DESCRIPTIONS,
    HuaweiSolarSelectEntity,
    get_select_registers,
)
from custom_components.huawei_solar.switch import (
    SMARTLOAD_SWITCH_DESCRIPTIONS,
    HuaweiSolarSwitchEntity,
    get_switch_registers,
)
from huawei_solar import SmartLoadDevice
from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.registers import REGISTERS

RAW_VALUES = {
    rn.SMARTLOAD_RATED_POWER: 3000,
    rn.SMARTLOAD_MIN_SWITCHING_INTERVAL: 5,
    rn.SMARTLOAD_OFF_GRID_MODE: 0,
    rn.SMARTLOAD_OFF_GRID_RESUME_SOC: 80,
    rn.SMARTLOAD_OFF_GRID_STOP_SOC: 70,
    rn.SMARTLOAD_OFF_GRID_AUTO_CONTROL: 1,
}


def _device() -> Mock:
    device = Mock(spec=SmartLoadDevice)
    device.serial_number = "LD26EMMA_SN"
    device.set = AsyncMock(return_value=True)
    return device


def _coordinator(device: Mock) -> Mock:
    coordinator = Mock()
    coordinator.device = device
    coordinator.async_request_refresh = AsyncMock()
    coordinator.data = {
        name: REGISTERS[name].decode((raw,)) for name, raw in RAW_VALUES.items()
    }
    return coordinator


def _update(entity: Any) -> None:
    with patch.object(entity, "async_write_ha_state"):
        entity._handle_coordinator_update()


def test_all_smartload_settings_registers_are_writeable() -> None:
    """Every register behind a SmartLoad number, select or switch must be writeable in the library."""
    keys = [
        d.key
        for d in (
            *SMARTLOAD_NUMBER_DESCRIPTIONS,
            *SMARTLOAD_SELECT_DESCRIPTIONS,
            *SMARTLOAD_SWITCH_DESCRIPTIONS,
        )
    ]

    assert all(REGISTERS[rn.RegisterName(key)].writeable for key in keys)


def test_configuration_registers_include_smartload_settings() -> None:
    """The configuration coordinator reads every register a SmartLoad entity needs."""
    device = _device()
    registers = (
        get_number_registers(device)
        | get_select_registers(device)
        | get_switch_registers(device)
    )

    assert registers == set(RAW_VALUES)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (rn.SMARTLOAD_RATED_POWER, 3000),
        (rn.SMARTLOAD_MIN_SWITCHING_INTERVAL, 5),
        (rn.SMARTLOAD_OFF_GRID_RESUME_SOC, 80),
        (rn.SMARTLOAD_OFF_GRID_STOP_SOC, 70),
    ],
)
async def test_number_reads_and_writes(key: str, expected: int) -> None:
    """A number shows the register value and writes the new value to the same register."""
    device = _device()
    description = next(d for d in SMARTLOAD_NUMBER_DESCRIPTIONS if d.key == key)
    entity = HuaweiSolarNumberEntity(_coordinator(device), device, description, Mock())
    _update(entity)

    assert entity.native_value == expected

    await entity.async_set_native_value(expected + 1)

    device.set.assert_awaited_once_with(rn.RegisterName(key), float(expected + 1))


@pytest.mark.asyncio
async def test_off_grid_soc_limits_follow_each_other() -> None:
    """The stop SOC can not be set above the resume SOC and vice versa."""
    device = _device()
    coordinator = _coordinator(device)
    resume, stop = (
        HuaweiSolarNumberEntity(coordinator, device, d, Mock())
        for d in SMARTLOAD_NUMBER_DESCRIPTIONS
        if d.key in (rn.SMARTLOAD_OFF_GRID_RESUME_SOC, rn.SMARTLOAD_OFF_GRID_STOP_SOC)
    )
    _update(resume)
    _update(stop)

    assert resume.native_min_value == 70
    assert stop.native_max_value == 80


@pytest.mark.asyncio
async def test_off_grid_mode_select() -> None:
    """The off-grid mode select shows the mode and writes the enum value."""
    device = _device()
    entity = HuaweiSolarSelectEntity(
        _coordinator(device), device, SMARTLOAD_SELECT_DESCRIPTIONS[0], Mock()
    )
    _update(entity)

    assert entity.options == ["basic", "battery"]
    assert entity.current_option == "basic"

    with patch.object(entity, "async_write_ha_state"):
        await entity.async_select_option("battery")

    device.set.assert_awaited_once_with(
        rn.SMARTLOAD_OFF_GRID_MODE, rv.SmartLoadOffGridMode.BATTERY
    )


@pytest.mark.asyncio
async def test_off_grid_auto_control_switch() -> None:
    """The automatic control switch shows the setting and writes a bool."""
    device = _device()
    entity = HuaweiSolarSwitchEntity(
        _coordinator(device), device, SMARTLOAD_SWITCH_DESCRIPTIONS[0], Mock()
    )
    _update(entity)

    assert entity.is_on is True

    with patch.object(entity, "async_write_ha_state"):
        await entity.async_turn_off()

    device.set.assert_awaited_once_with(rn.SMARTLOAD_OFF_GRID_AUTO_CONTROL, False)
