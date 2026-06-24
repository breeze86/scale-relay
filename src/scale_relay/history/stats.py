"""Build historical measurement context."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime
from typing import Any


SECONDS_PER_DAY = 86400


def build_history_context(
    *,
    current: dict[str, Any],
    recent_records: list[dict[str, Any]],
    statistics_records: list[dict[str, Any]],
    all_records: list[dict[str, Any]],
    statistics_days: int,
    include_weekly_series: bool,
) -> dict[str, Any]:
    annotated_recent_records = annotate_sampling_context(recent_records)
    annotated_statistics_records = annotate_sampling_context(statistics_records)
    annotated_all_records = annotate_sampling_context(all_records)
    current = _current_from_annotated_records(current, annotated_all_records)
    missing_fields = [
        field
        for field in ("heart_rate", "impedance_high", "impedance_low", "bmi")
        if current.get(field) is None
    ]
    statistics_payload = build_statistics(
        current=current,
        records=annotated_statistics_records,
        statistics_days=statistics_days,
    )
    return {
        "records": annotated_recent_records,
        "statistics": statistics_payload,
        "weekly_series": build_weekly_series(annotated_all_records) if include_weekly_series else [],
        "data_quality": {
            "sample_count": len(annotated_all_records),
            "recent_sample_count": len(annotated_recent_records),
            "statistics_sample_count": len(annotated_statistics_records),
            "statistics_days": statistics_days,
            "insufficient_history": len(annotated_all_records) < 2,
            "missing_fields": missing_fields,
            "measurement_interval_irregular": measurement_interval_irregular(
                annotated_recent_records
            ),
        },
    }


def annotate_sampling_context(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    daily_counts: dict[str, int] = defaultdict(int)
    previous_timestamp: int | None = None

    for record in records:
        current = dict(record)
        timestamp = int(current["timestamp"])
        local_date = datetime.fromtimestamp(timestamp).date().isoformat()
        daily_counts[local_date] += 1
        current["same_day_sequence"] = daily_counts[local_date]
        if previous_timestamp is None:
            current["interval_from_previous_minutes"] = None
        else:
            current["interval_from_previous_minutes"] = round(
                (timestamp - previous_timestamp) / 60,
                3,
            )
        previous_timestamp = timestamp
        annotated.append(current)

    return annotated


def build_statistics(
    *,
    current: dict[str, Any],
    records: list[dict[str, Any]],
    statistics_days: int,
) -> dict[str, Any]:
    weights = [_float_value(record.get("weight_kg")) for record in records]
    weights = [value for value in weights if value is not None]
    bmis = [_float_value(record.get("bmi")) for record in records]
    bmis = [value for value in bmis if value is not None]
    high_values = [_float_value(record.get("impedance_high")) for record in records]
    high_values = [value for value in high_values if value is not None]
    low_values = [_float_value(record.get("impedance_low")) for record in records]
    low_values = [value for value in low_values if value is not None]

    current_timestamp = int(current["timestamp"])
    previous = _previous_record(records, current_timestamp)
    oldest = records[0] if records else None
    latest_weight = _float_value(current.get("weight_kg"))

    return {
        "sample_count": len(records),
        "days_covered": statistics_days,
        "previous_weight_kg": _float_value(previous.get("weight_kg")) if previous else None,
        "delta_since_previous_kg": _delta(
            latest_weight,
            _float_value(previous.get("weight_kg")) if previous else None,
        ),
        "weight": {
            "latest_kg": latest_weight,
            "avg_7d_kg": _average_weight_since(records, current_timestamp - 7 * SECONDS_PER_DAY),
            "avg_30d_kg": _average(weights),
            "min_30d_kg": min(weights) if weights else None,
            "max_30d_kg": max(weights) if weights else None,
            "delta_7d_kg": _delta_since(records, current, 7),
            "delta_30d_kg": _delta(
                latest_weight,
                _float_value(oldest.get("weight_kg")) if oldest else None,
            ),
        },
        "bmi": {
            "latest": _float_value(current.get("bmi")),
            "avg_30d": _average(bmis),
        },
        "impedance": {
            "high_latest": current.get("impedance_high"),
            "low_latest": current.get("impedance_low"),
            "high_avg_30d": _average(high_values),
            "low_avg_30d": _average(low_values),
        },
    }


def build_weekly_series(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        timestamp = int(record["timestamp"])
        year, week, _ = datetime.fromtimestamp(timestamp).isocalendar()
        grouped[(year, week)].append(record)

    series = []
    for key in sorted(grouped):
        week_records = grouped[key]
        weights = [_float_value(record.get("weight_kg")) for record in week_records]
        weights = [value for value in weights if value is not None]
        bmis = [_float_value(record.get("bmi")) for record in week_records]
        bmis = [value for value in bmis if value is not None]
        week_start = date.fromisocalendar(key[0], key[1], 1).isoformat()
        series.append(
            {
                "week_start": week_start,
                "sample_count": len(week_records),
                "avg_weight_kg": _average(weights),
                "min_weight_kg": min(weights) if weights else None,
                "max_weight_kg": max(weights) if weights else None,
                "avg_bmi": _average(bmis),
            }
        )
    return series


def measurement_interval_irregular(records: list[dict[str, Any]]) -> bool:
    if len(records) < 4:
        return False
    timestamps = [int(record["timestamp"]) for record in records]
    intervals = [
        later - earlier
        for earlier, later in zip(timestamps, timestamps[1:], strict=False)
        if later > earlier
    ]
    if len(intervals) < 3:
        return False
    median_interval = statistics.median(intervals)
    return bool(median_interval > 0 and max(intervals) > median_interval * 3)


def _current_from_annotated_records(
    current: dict[str, Any],
    annotated_records: list[dict[str, Any]],
) -> dict[str, Any]:
    current_timestamp = int(current["timestamp"])
    for record in reversed(annotated_records):
        if int(record["timestamp"]) == current_timestamp:
            return record
    return current


def _previous_record(records: list[dict[str, Any]], current_timestamp: int) -> dict[str, Any] | None:
    previous_records = [record for record in records if int(record["timestamp"]) < current_timestamp]
    if not previous_records:
        return None
    return previous_records[-1]


def _average_weight_since(records: list[dict[str, Any]], since_timestamp: int) -> float | None:
    values = [
        _float_value(record.get("weight_kg"))
        for record in records
        if int(record["timestamp"]) >= since_timestamp
    ]
    return _average([value for value in values if value is not None])


def _delta_since(records: list[dict[str, Any]], current: dict[str, Any], days: int) -> float | None:
    since_timestamp = int(current["timestamp"]) - days * SECONDS_PER_DAY
    candidates = [record for record in records if int(record["timestamp"]) >= since_timestamp]
    if not candidates:
        return None
    return _delta(_float_value(current.get("weight_kg")), _float_value(candidates[0].get("weight_kg")))


def _delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return round(current - previous, 3)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 3)


def _float_value(value: object) -> float | None:
    if value is None:
        return None
    return float(value)
