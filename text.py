"""This component provides switch entities for Huawei Solar."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Generic, TypeVar
from collections.abc import Callable

from homeassistant.components.text import TextEntity, TextEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from huawei_solar import HuaweiSolarBridge
from huawei_solar import register_names as rn
from huawei_solar import register_values as rv
from huawei_solar.registers import PeakSettingPeriod

from . import HuaweiSolarEntity, HuaweiSolarUpdateCoordinator
from .const import CONF_ENABLE_PARAMETER_CONFIGURATION, DATA_UPDATE_COORDINATORS, DOMAIN

_LOGGER = logging.getLogger(__name__)


T = TypeVar("T")
V = TypeVar("V")


@dataclass
class HuaweiSolarTextEntityDescription(Generic[T, V], TextEntityDescription):
    """Huawei Solar Switch Entity Description."""

    to_text: Callable[[V], str] = None
    parse_text: Callable[[str], V] = None
    text_pattern: str = None


def _days_effective_to_text(days: tuple(bool, bool, bool, bool, bool, bool, bool)):
    value = ""
    for i in range(0, 7):  # Sunday is on index 0, but we want to name it day 7
        if days[(i + 1) % 7]:
            value += f"{i+1}"

    return value


def _text_to_days_effective(days_text):
    days = [False, False, False, False, False, False, False]
    for day in days_text:
        days[int(day)] = True

    return tuple(days)


def _peak_periods_to_text(periods: list[PeakSettingPeriod]) -> str:
    return "\n".join(
        f"{psp.start_time//60:02d}:{psp.start_time%60:02d}"
        f"-{psp.end_time//60:02d}:{psp.end_time%60:02d}"
        f"/{_days_effective_to_text(psp.days_effective)}"
        f"/{psp.power}W"
        for psp in periods
    )


def _text_to_peak_periods(text: str) -> list[PeakSettingPeriod]:
    result = []

    def time_to_int(value: str):
        hours, minutes = value.split(":")

        minutes_since_midnight = int(hours) * 60 + int(minutes)

        if not 0 <= minutes_since_midnight <= 1440:
            raise ValueError(f"Invalid time '{value}': must be between 00:00 and 23:59")
        return minutes_since_midnight

    for line in text.split("\n"):
        start_end_time_str, days_str, wattage_str = line.split("/")
        start_time_str, end_time_str = start_end_time_str.split("-")

        result.append(
            PeakSettingPeriod(
                time_to_int(start_time_str),
                time_to_int(end_time_str),
                int(wattage_str[:-1]),
                _text_to_days_effective(days_str),
            )
        )

    return result


ENERGY_STORAGE_SWITCH_DESCRIPTIONS: tuple[HuaweiSolarTextEntityDescription, ...] = (
    HuaweiSolarTextEntityDescription(
        key=rn.STORAGE_CAPACITY_CONTROL_PERIODS,
        name="Capacity Control Periods",
        icon="mdi:battery-arrow-up",
        entity_category=EntityCategory.CONFIG,
        to_text=_peak_periods_to_text,
        parse_text=_text_to_peak_periods,
        pattern=r"([0-2]\d:\d\d-[0-2]\d:\d\d/[1-7]{1,7}/\d+W\n?){0,14}",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Huawei Solar Switch Entities Setup."""

    if not entry.data.get(CONF_ENABLE_PARAMETER_CONFIGURATION, False):
        _LOGGER.info("Skipping switch setup, as parameter configuration is not enabled")
        return

    update_coordinators = hass.data[DOMAIN][entry.entry_id][
        DATA_UPDATE_COORDINATORS
    ]  # type: list[HuaweiSolarUpdateCoordinator]

    # When more than one inverter is present, then we suffix all sensors with '#1', '#2', ...
    # The order for these suffixes is the order in which the user entered the slave-ids.
    must_append_inverter_suffix = len(update_coordinators) > 1

    entities_to_add: list[TextEntity] = []
    for idx, update_coordinator in enumerate(update_coordinators):
        slave_entities: list[HuaweiSolarTextEntity] = []

        bridge = update_coordinator.bridge
        device_infos = update_coordinator.device_infos

        if bridge.battery_1_type != rv.StorageProductModel.NONE:
            assert device_infos["connected_energy_storage"]

            for entity_description in ENERGY_STORAGE_SWITCH_DESCRIPTIONS:
                slave_entities.append(
                    await HuaweiSolarTextEntity.create(
                        bridge,
                        entity_description,
                        device_infos["connected_energy_storage"],
                    )
                )
        else:
            _LOGGER.debug(
                "No battery detected on slave %s. Skipping energy storage switch entities",
                bridge.slave_id,
            )

        # Add suffix if multiple inverters are present
        if must_append_inverter_suffix:
            for entity in slave_entities:
                entity.add_name_suffix(f" #{idx+1}")

        entities_to_add.extend(slave_entities)

    async_add_entities(entities_to_add)


class HuaweiSolarTextEntity(HuaweiSolarEntity, TextEntity):
    """Huawei Solar Switch Entity."""

    entity_description: HuaweiSolarTextEntityDescription

    def __init__(
        self,
        bridge: HuaweiSolarBridge,
        description: HuaweiSolarTextEntityDescription,
        device_info: DeviceInfo,
        native_value: str,
    ) -> None:
        """Huawei Solar Switch Entity constructor.

        Do not use directly. Use `.create` instead!
        """
        self.bridge = bridge
        self.entity_description = description

        self._attr_device_info = device_info
        self._attr_unique_id = f"{bridge.serial_number}_{description.key}"
        self._attr_native_value = native_value

    @classmethod
    async def create(
        cls,
        bridge: HuaweiSolarBridge,
        description: HuaweiSolarTextEntityDescription,
        device_info: DeviceInfo,
    ):
        """Huawei Solar Text Entity constructor.

        This async constructor fills in the necessary min/max values
        """

        # Assumption: these values are not updated outside of HA.
        # This should hold true as they typically can only be set via the Modbus-interface,
        # which only allows one client at a time.
        initial_value = description.to_text(
            (await bridge.client.get(description.key)).value
        )

        return cls(bridge, description, device_info, initial_value)

    async def async_set_value(self, value: str) -> None:
        """Set the text value"""

        _LOGGER.info("Would set value to %r", self.entity_description.parse_text(value))
