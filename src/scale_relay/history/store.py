"""SQLite-backed measurement history store."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from scale_relay.config import ProfileConfig
from scale_relay.message import calculate_bmi
from scale_relay.models import WeightMeasurement


class MeasurementHistoryStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def add(self, measurement: WeightMeasurement, profile: ProfileConfig) -> None:
        record = measurement_to_history_record(measurement, profile)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO measurements (
                    request_id,
                    user_id,
                    captured_at,
                    device_mac,
                    device_name,
                    device_type,
                    weight_kg,
                    bmi,
                    impedance_high,
                    impedance_low,
                    heart_rate,
                    stabilized,
                    source,
                    raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _user_request_id(profile.user_id, measurement.request_id()),
                    profile.user_id,
                    measurement.timestamp,
                    measurement.device_mac,
                    measurement.device_name,
                    measurement.device_type,
                    measurement.weight_kg,
                    record.get("bmi"),
                    measurement.impedance_high,
                    measurement.impedance_low,
                    measurement.heart_rate,
                    1 if measurement.stabilized else 0,
                    measurement.source,
                    json.dumps(record, ensure_ascii=False, sort_keys=True),
                ),
            )

    def recent_records(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT raw_json
                FROM measurements
                WHERE user_id = ?
                ORDER BY captured_at DESC, id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        records = [json.loads(row["raw_json"]) for row in rows]
        return list(reversed(records))

    def records_since(self, user_id: str, timestamp: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT raw_json
                FROM measurements
                WHERE user_id = ? AND captured_at >= ?
                ORDER BY captured_at ASC, id ASC
                """,
                (user_id, timestamp),
            ).fetchall()
        return [json.loads(row["raw_json"]) for row in rows]

    def all_records(self, user_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT raw_json
                FROM measurements
                WHERE user_id = ?
                ORDER BY captured_at ASC, id ASC
                """,
                (user_id,),
            ).fetchall()
        return [json.loads(row["raw_json"]) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS measurements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL UNIQUE,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    captured_at INTEGER NOT NULL,
                    device_mac TEXT NOT NULL,
                    device_name TEXT,
                    device_type TEXT NOT NULL,
                    weight_kg REAL NOT NULL,
                    bmi REAL,
                    impedance_high INTEGER,
                    impedance_low INTEGER,
                    heart_rate INTEGER,
                    stabilized INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    raw_json TEXT NOT NULL
                )
                """
            )
            self._ensure_user_id_column(connection)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_measurements_user_captured_at
                ON measurements (user_id, captured_at)
                """
            )

    def _ensure_user_id_column(self, connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(measurements)").fetchall()
        }
        if "user_id" not in columns:
            connection.execute(
                "ALTER TABLE measurements ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'"
            )


def measurement_to_history_record(
    measurement: WeightMeasurement,
    profile: ProfileConfig,
) -> dict[str, Any]:
    record = measurement.to_dict()
    record["user_id"] = profile.user_id
    record["bmi"] = calculate_bmi(measurement.weight_kg, profile.height_cm)
    return record


def _user_request_id(user_id: str, request_id: str) -> str:
    return f"{user_id}:{request_id}"
