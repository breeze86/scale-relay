import tempfile
import unittest
from pathlib import Path

from scale_relay.config import (
    AppConfig,
    DeviceConfig,
    HistoryConfig,
    ListenConfig,
    ProfileConfig,
    PromptConfig,
    SinkConfig,
    XiaomiConfig,
)
from scale_relay.events import build_measurement_event
from scale_relay.history.stats import build_history_context
from scale_relay.history.store import MeasurementHistoryStore
from scale_relay.models import WeightMeasurement


def measurement(timestamp, weight, high=420, low=460):
    return WeightMeasurement(
        device_type="xiaomi_s400",
        device_name="Xiaomi Body Composition Scale S400",
        device_mac="E3:2B:13:0A:37:D9",
        timestamp=timestamp,
        weight_kg=weight,
        impedance_high=high,
        impedance_low=low,
        heart_rate=None,
        stabilized=True,
    )


class HistoryTests(unittest.TestCase):
    def test_store_deduplicates_and_returns_recent_records_chronologically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MeasurementHistoryStore(Path(temp_dir) / "measurements.sqlite3")
            profile = ProfileConfig(height_cm=160)
            first = measurement(1_800_000_000, 56.0)
            second = measurement(1_800_086_400, 56.3)
            store.add(first, profile)
            store.add(first, profile)
            store.add(second, profile)

            records = store.recent_records("default", 10)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["weight_kg"], 56.0)
            self.assertEqual(records[1]["weight_kg"], 56.3)
            self.assertEqual(records[0]["user_id"], "default")
            self.assertAlmostEqual(records[0]["bmi"], 21.875)

    def test_store_filters_records_by_user_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MeasurementHistoryStore(Path(temp_dir) / "measurements.sqlite3")
            store.add(measurement(1_800_000_000, 56.0), ProfileConfig(user_id="a"))
            store.add(measurement(1_800_086_400, 62.0), ProfileConfig(user_id="b"))

            a_records = store.recent_records("a", 10)
            b_records = store.recent_records("b", 10)

            self.assertEqual(len(a_records), 1)
            self.assertEqual(a_records[0]["weight_kg"], 56.0)
            self.assertEqual(a_records[0]["user_id"], "a")
            self.assertEqual(len(b_records), 1)
            self.assertEqual(b_records[0]["weight_kg"], 62.0)
            self.assertEqual(b_records[0]["user_id"], "b")

    def test_event_current_includes_sampling_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MeasurementHistoryStore(Path(temp_dir) / "measurements.sqlite3")
            profile = ProfileConfig(user_id="jj", height_cm=160)
            first = measurement(1_800_000_000, 56.0)
            second = measurement(1_800_003_600, 56.2)
            store.add(first, profile)
            store.add(second, profile)
            config = AppConfig(
                xiaomi=XiaomiConfig(region="cn"),
                device=DeviceConfig(
                    type="xiaomi_s400",
                    mac="E3:2B:13:0A:37:D9",
                    ble_key="0123456789abcdef0123456789abcdef",
                ),
                listen=ListenConfig(),
                profile=profile,
                history=HistoryConfig(storage_path=str(Path(temp_dir) / "measurements.sqlite3")),
                prompt=PromptConfig(text="请分析本次称重。"),
                sink=SinkConfig(type="stdout"),
            )

            event = build_measurement_event(
                measurement=second,
                config=config,
                history_store=store,
            )

            current = event["payload"]["current"]
            self.assertEqual(current["interval_from_previous_minutes"], 60)
            self.assertEqual(current["same_day_sequence"], 2)

    def test_history_context_contains_statistics_and_weekly_series(self):
        records = [
            {
                "timestamp": 1_800_000_000,
                "weight_kg": 56.0,
                "bmi": 21.875,
                "impedance_high": 420,
                "impedance_low": 460,
                "heart_rate": None,
            },
            {
                "timestamp": 1_800_086_400,
                "weight_kg": 56.3,
                "bmi": 21.992,
                "impedance_high": 422,
                "impedance_low": 462,
                "heart_rate": None,
            },
        ]
        context = build_history_context(
            current=records[-1],
            recent_records=records,
            statistics_records=records,
            all_records=records,
            statistics_days=30,
            include_weekly_series=True,
        )
        self.assertEqual(context["statistics"]["sample_count"], 2)
        self.assertEqual(context["statistics"]["previous_weight_kg"], 56.0)
        self.assertEqual(context["statistics"]["delta_since_previous_kg"], 0.3)
        self.assertFalse(context["data_quality"]["insufficient_history"])
        self.assertGreaterEqual(len(context["weekly_series"]), 1)
        self.assertIsNone(context["records"][0]["interval_from_previous_minutes"])
        self.assertEqual(context["records"][0]["same_day_sequence"], 1)
        self.assertEqual(context["records"][1]["interval_from_previous_minutes"], 1440)
        self.assertEqual(context["records"][1]["same_day_sequence"], 1)

    def test_history_context_marks_same_day_sequence(self):
        records = [
            {"timestamp": 1_800_000_000, "weight_kg": 56.0, "bmi": 21.875},
            {"timestamp": 1_800_003_600, "weight_kg": 56.2, "bmi": 21.953},
            {"timestamp": 1_800_007_200, "weight_kg": 56.1, "bmi": 21.914},
        ]
        context = build_history_context(
            current=records[-1],
            recent_records=records,
            statistics_records=records,
            all_records=records,
            statistics_days=30,
            include_weekly_series=True,
        )
        self.assertEqual(context["records"][0]["same_day_sequence"], 1)
        self.assertEqual(context["records"][1]["same_day_sequence"], 2)
        self.assertEqual(context["records"][2]["same_day_sequence"], 3)
        self.assertEqual(context["records"][1]["interval_from_previous_minutes"], 60)
        self.assertEqual(context["records"][2]["interval_from_previous_minutes"], 60)


if __name__ == "__main__":
    unittest.main()
