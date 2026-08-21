"""Historical telemetry import for Huawei Solar entities into Home Assistant Long-Term Statistics."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
import logging
from typing import Any

from huawei_solar import (
    HuaweiSolarException,
    PerformanceRequestType,
    ReadException,
    SUN2000Device,
    register_names as rn,
)

from homeassistant.components import persistent_notification
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_last_statistics,
)
from homeassistant.components.sensor import SensorStateClass
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.translation import async_get_translations

from .const import DATA_DEVICE_DATAS, DOMAIN
from .types import HuaweiSolarDeviceData, HuaweiSolarInverterData

_LOGGER = logging.getLogger(__name__)

# Maximum timespan queried per Modbus file download chunk to prevent transport timeouts
CHUNK_TIMESPAN = timedelta(days=7)

# Sleep duration between chunk downloads to ensure data update coordinators can run unhindered
INTER_CHUNK_SLEEP = 1.0

# Supported register keys and their performance request mapping
SUPPORTED_REGISTERS: dict[
    rn.RegisterName,
    tuple[PerformanceRequestType, SensorStateClass, str],
] = {
    rn.DAILY_YIELD_ENERGY: (
        PerformanceRequestType.HOUR_POWER,
        SensorStateClass.TOTAL_INCREASING,
        UnitOfEnergy.KILO_WATT_HOUR,
    ),
    rn.ACCUMULATED_YIELD_ENERGY: (
        PerformanceRequestType.HOUR_POWER,
        SensorStateClass.TOTAL_INCREASING,
        UnitOfEnergy.KILO_WATT_HOUR,
    ),
    rn.ACTIVE_POWER: (
        PerformanceRequestType.OUTPUT_POWER,
        SensorStateClass.MEASUREMENT,
        UnitOfPower.WATT,
    ),
    rn.STORAGE_TOTAL_CHARGE: (
        PerformanceRequestType.BATTERY_CHARGE_DAY_POWER,
        SensorStateClass.TOTAL_INCREASING,
        UnitOfEnergy.KILO_WATT_HOUR,
    ),
    rn.STORAGE_TOTAL_DISCHARGE: (
        PerformanceRequestType.BATTERY_DISCHARGE_DAY_POWER,
        SensorStateClass.TOTAL_INCREASING,
        UnitOfEnergy.KILO_WATT_HOUR,
    ),
    rn.GRID_ACCUMULATED_ENERGY: (
        PerformanceRequestType.ABSORB_DAY_POWER,
        SensorStateClass.TOTAL_INCREASING,
        UnitOfEnergy.KILO_WATT_HOUR,
    ),
}


async def async_get_last_statistic_data(
    hass: HomeAssistant,
    statistic_id: str,
) -> tuple[datetime | None, float]:
    """Retrieve the last recorded statistic timestamp and cumulative sum."""
    try:
        last_stats = await get_instance(hass).async_add_executor_job(
            get_last_statistics,
            hass,
            1,
            statistic_id,
            True,
            {"start", "sum", "state"},
        )
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not fetch last statistics for %s: %s", statistic_id, err)
        return None, 0.0

    if not last_stats or statistic_id not in last_stats or not last_stats[statistic_id]:
        return None, 0.0

    last_stat = last_stats[statistic_id][0]
    raw_start = last_stat.get("start")
    last_sum = float(last_stat.get("sum") or 0.0)

    if isinstance(raw_start, (int, float)):
        last_dt = datetime.fromtimestamp(raw_start, tz=UTC)
    elif isinstance(raw_start, datetime):
        last_dt = raw_start.astimezone(UTC) if raw_start.tzinfo else raw_start.replace(tzinfo=UTC)
    else:
        last_dt = None

    return last_dt, last_sum


def _find_inverter_data_for_entity(
    hass: HomeAssistant,
    entity_entry: er.RegistryEntry,
) -> HuaweiSolarInverterData:
    """Find the HuaweiSolarInverterData associated with an entity."""
    if not entity_entry.device_id:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entity_has_no_device",
            translation_placeholders={"entity_id": entity_entry.entity_id},
        )

    device_registry = dr.async_get(hass)
    device_entry = device_registry.async_get(entity_entry.device_id)
    if not device_entry:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="ha_device_not_found",
            translation_placeholders={"device_id": entity_entry.device_id},
        )

    for entry_id in device_entry.config_entries:
        if (entry := hass.config_entries.async_get_entry(entry_id)) is None:
            continue
        if entry.domain == DOMAIN and entry.runtime_data:
            device_datas: list[HuaweiSolarDeviceData] = entry.runtime_data[DATA_DEVICE_DATAS]
            for dd in device_datas:
                if isinstance(dd, HuaweiSolarInverterData) and isinstance(dd.device, SUN2000Device):
                    for identifier in dd.device_info["identifiers"]:
                        if identifier in device_entry.identifiers:
                            return dd

    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="inverter_not_found_for_entity",
        translation_placeholders={"entity_id": entity_entry.entity_id},
    )


def _get_supported_register(
    entity_entry: er.RegistryEntry,
    device: SUN2000Device,
) -> rn.RegisterName:
    """Extract and validate the supported register from the entity unique_id."""
    unique_id = entity_entry.unique_id
    serial = device.serial_number

    for reg_name in SUPPORTED_REGISTERS:
        if unique_id == f"{serial}_{reg_name}" or unique_id.endswith(f"_{reg_name}"):
            return reg_name

    supported_list = ", ".join(SUPPORTED_REGISTERS.keys())
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unsupported_entity_for_history",
        translation_placeholders={
            "entity_id": entity_entry.entity_id,
            "supported": supported_list,
        },
    )


NOTIFICATION_ID = "huawei_solar_import_history"


def _format_notification(
    translations: dict[str, str],
    key: str,
    default_title: str,
    default_message: str,
    **kwargs: Any,
) -> tuple[str, str]:
    """Retrieve and format translated notification title and message."""
    title_template = translations.get(
        f"component.{DOMAIN}.notification.{key}.title", default_title
    )
    message_template = translations.get(
        f"component.{DOMAIN}.notification.{key}.message", default_message
    )
    try:
        return title_template.format(**kwargs), message_template.format(**kwargs)
    except Exception:
        return default_title, default_message.format(**kwargs)


async def async_import_entity_history(
    hass: HomeAssistant,
    entity_id: str,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    translations: dict[str, str] | None = None,
    progress_context: tuple[int, int, int] | None = None,
) -> dict[str, Any]:
    """Import historical data for a specific Huawei Solar entity."""
    entity_registry = er.async_get(hass)
    entity_entry = entity_registry.async_get(entity_id)

    if not entity_entry or entity_entry.platform != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_a_huawei_solar_entity",
            translation_placeholders={"entity_id": entity_id},
        )

    inverter_data = _find_inverter_data_for_entity(hass, entity_entry)
    device = inverter_data.device

    reg_name = _get_supported_register(entity_entry, device)
    request_type, state_class, default_unit = SUPPORTED_REGISTERS[reg_name]
    unit = entity_entry.unit_of_measurement or default_unit
    entity_name = entity_entry.name or entity_entry.original_name

    end_dt = end_time.astimezone(UTC) if end_time else datetime.now(tz=UTC)

    # Determine time window to query
    last_stat_dt, last_sum = await async_get_last_statistic_data(hass, entity_id)

    if start_time is not None:
        query_start = start_time.astimezone(UTC)
    elif last_stat_dt is not None:
        query_start = last_stat_dt + timedelta(hours=1)
    else:
        query_start = end_dt - timedelta(days=30)

    if query_start >= end_dt:
        _LOGGER.debug(
            "Statistics for %s are already up to date (last: %s, end: %s)",
            entity_id,
            query_start,
            end_dt,
        )
        return {
            "imported_points": 0,
            "start_time": query_start.isoformat(),
            "end_time": end_dt.isoformat(),
            "status": "up_to_date",
        }

    _LOGGER.info(
        "Importing historical telemetry for %s from %s to %s",
        entity_id,
        query_start.isoformat(),
        end_dt.isoformat(),
    )

    running_sum = last_sum
    current_chunk_start = query_start
    total_imported_count = 0

    while current_chunk_start < end_dt:
        current_chunk_end = min(current_chunk_start + CHUNK_TIMESPAN, end_dt)

        if translations is not None and progress_context is not None:
            idx, total_entities, base_points = progress_context
            title, message = _format_notification(
                translations,
                "import_history_progress",
                "Huawei Solar History Import",
                "⏳ **Importing entity {idx}/{total_entities}**\n\n• Entity: `{entity_id}`\n• Querying: {start} to {end}\n• Points imported so far: {total_points}",
                idx=idx,
                total_entities=total_entities,
                entity_id=entity_id,
                start=current_chunk_start.strftime("%Y-%m-%d"),
                end=current_chunk_end.strftime("%Y-%m-%d"),
                total_points=base_points + total_imported_count,
            )
            persistent_notification.async_create(
                hass,
                message,
                title=title,
                notification_id=NOTIFICATION_ID,
            )

        try:
            data_points = await device.get_performance_data(
                request_type=request_type,
                start_time=current_chunk_start,
                end_time=current_chunk_end,
            )
        except (ReadException, HuaweiSolarException) as err:
            _LOGGER.warning(
                "Failed to download history chunk for %s [%s - %s]: %s",
                entity_id,
                current_chunk_start.isoformat(),
                current_chunk_end.isoformat(),
                err,
            )
            current_chunk_start = current_chunk_end
            await asyncio.sleep(INTER_CHUNK_SLEEP)
            continue

        if not data_points:
            current_chunk_start = current_chunk_end
            await asyncio.sleep(INTER_CHUNK_SLEEP)
            continue

        # Aggregate into 1-hour statistic buckets
        if state_class == SensorStateClass.TOTAL_INCREASING:
            hourly_deltas: dict[datetime, float] = defaultdict(float)
            for point in data_points:
                hour_dt = point.time.replace(minute=0, second=0, microsecond=0)
                hourly_deltas[hour_dt] += point.value

            stats: list[StatisticData] = []
            for hour_slot in sorted(hourly_deltas.keys()):
                delta = hourly_deltas[hour_slot]
                running_sum += delta
                stats.append(
                    StatisticData(
                        start=hour_slot,
                        state=delta,
                        sum=running_sum,
                    )
                )
        else:
            hourly_values: dict[datetime, list[float]] = defaultdict(list)
            for point in data_points:
                hour_dt = point.time.replace(minute=0, second=0, microsecond=0)
                hourly_values[hour_dt].append(point.value)

            stats = []
            for hour_slot in sorted(hourly_values.keys()):
                vals = hourly_values[hour_slot]
                stats.append(
                    StatisticData(
                        start=hour_slot,
                        mean=sum(vals) / len(vals),
                        min=min(vals),
                        max=max(vals),
                    )
                )

        if stats:
            metadata = StatisticMetaData(
                has_mean=(state_class != SensorStateClass.TOTAL_INCREASING),
                has_sum=(state_class == SensorStateClass.TOTAL_INCREASING),
                name=entity_name,
                source=DOMAIN,
                statistic_id=entity_id,
                unit_of_measurement=unit,
            )
            async_import_statistics(hass, metadata, stats)
            total_imported_count += len(stats)

        current_chunk_start = current_chunk_end

        # Sufficient sleep between requests so DataUpdateCoordinators can poll normally
        await asyncio.sleep(INTER_CHUNK_SLEEP)

    return {
        "imported_points": total_imported_count,
        "start_time": query_start.isoformat(),
        "end_time": end_dt.isoformat(),
        "status": "success",
    }


async def async_import_history(
    hass: HomeAssistant,
    entity_ids: list[str],
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> dict[str, Any]:
    """Import missing historical telemetry for multiple Huawei Solar entities."""
    results: dict[str, Any] = {}
    total_points = 0
    total_entities = len(entity_ids)

    translations = await async_get_translations(
        hass,
        hass.config.language,
        "notification",
        [DOMAIN],
    )

    start_title, start_msg = _format_notification(
        translations,
        "import_history_start",
        "Huawei Solar History Import",
        "Starting historical telemetry import for {total_entities} entity/entities...",
        total_entities=total_entities,
    )
    persistent_notification.async_create(
        hass,
        start_msg,
        title=start_title,
        notification_id=NOTIFICATION_ID,
    )

    try:
        for idx, entity_id in enumerate(entity_ids, start=1):
            entity_result = await async_import_entity_history(
                hass,
                entity_id=entity_id,
                start_time=start_time,
                end_time=end_time,
                translations=translations,
                progress_context=(idx, total_entities, total_points),
            )
            results[entity_id] = entity_result
            total_points += entity_result["imported_points"]

        complete_title, complete_msg = _format_notification(
            translations,
            "import_history_complete",
            "Huawei Solar History Import",
            "✅ **Import complete!**\n\nSuccessfully imported **{total_points}** data points across {total_entities} entity/entities.",
            total_points=total_points,
            total_entities=total_entities,
        )
        persistent_notification.async_create(
            hass,
            complete_msg,
            title=complete_title,
            notification_id=NOTIFICATION_ID,
        )
    except Exception as err:
        fail_title, fail_msg = _format_notification(
            translations,
            "import_history_failed",
            "Huawei Solar History Import",
            "❌ **Import failed:**\n\n{error}",
            error=str(err),
        )
        persistent_notification.async_create(
            hass,
            fail_msg,
            title=fail_title,
            notification_id=NOTIFICATION_ID,
        )
        raise

    return {
        "imported_points_total": total_points,
        "entities": results,
    }
