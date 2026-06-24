"""Build outbound measurement events."""

from __future__ import annotations

from typing import Any

from scale_relay.config import AppConfig
from scale_relay.history.stats import build_history_context
from scale_relay.history.store import MeasurementHistoryStore, measurement_to_history_record
from scale_relay.message import build_weight_message
from scale_relay.models import WeightMeasurement


def build_measurement_event(
    *,
    measurement: WeightMeasurement,
    config: AppConfig,
    history_store: MeasurementHistoryStore | None,
) -> dict[str, Any]:
    current = measurement_to_history_record(measurement, config.profile)
    history = _history_payload(current=current, config=config, history_store=history_store)
    current = _current_from_history(current=current, history=history)
    return {
        "event_type": config.sink.event_type,
        "source": "scale-relay",
        "intent": config.sink.intent,
        "payload_schema": {
            "name": "scale_relay.weight_measurement",
            "version": "1.0",
        },
        "message": build_weight_message(
            measurement=measurement,
            profile=config.profile,
            prompt_text=config.prompt.text,
            history=history,
        ),
        "profile": _profile_payload(config),
        "payload": {
            "current": current,
            "history": history,
        },
        "sent_at": measurement.timestamp,
    }


def _history_payload(
    *,
    current: dict[str, Any],
    config: AppConfig,
    history_store: MeasurementHistoryStore | None,
) -> dict[str, Any]:
    if not config.history.enabled or history_store is None:
        return {
            "records": [],
            "statistics": {},
            "weekly_series": [],
            "data_quality": {
                "history_enabled": False,
                "insufficient_history": True,
                "missing_fields": [],
            },
        }

    current_timestamp = int(current["timestamp"])
    statistics_since = current_timestamp - config.history.statistics_days * 86400
    user_id = config.profile.user_id
    recent_records = history_store.recent_records(user_id, config.history.recent_measurements_limit)
    statistics_records = history_store.records_since(user_id, statistics_since)
    all_records = history_store.all_records(user_id)
    return build_history_context(
        current=current,
        recent_records=recent_records,
        statistics_records=statistics_records,
        all_records=all_records,
        statistics_days=config.history.statistics_days,
        include_weekly_series=config.history.include_weekly_series,
    )


def _profile_payload(config: AppConfig) -> dict[str, object]:
    payload: dict[str, object] = {"user_id": config.profile.user_id}
    if config.profile.gender:
        payload["gender"] = config.profile.gender
    if config.profile.height_cm is not None:
        payload["height_cm"] = config.profile.height_cm
    return payload


def _current_from_history(
    *,
    current: dict[str, Any],
    history: dict[str, Any],
) -> dict[str, Any]:
    records = history.get("records")
    if not isinstance(records, list):
        return current
    current_timestamp = int(current["timestamp"])
    for record in reversed(records):
        if isinstance(record, dict) and int(record.get("timestamp", 0)) == current_timestamp:
            return {**current, **record}
    return current
