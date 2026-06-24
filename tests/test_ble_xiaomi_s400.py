import unittest

from scale_relay.ble.xiaomi_s400 import (
    XiaomiS400Listener,
    _describe_update,
    _matches_target_device,
    _normalize_service_data,
    _to_str,
)
from scale_relay.config import DeviceConfig, ListenConfig


class FakeValue:
    def __init__(self, name, native_value):
        self.name = name
        self.native_value = native_value


class FakeUpdate:
    def __init__(self, values, binary_values):
        self.entity_values = {key: FakeValue(key, value) for key, value in values.items()}
        self.binary_entity_values = {
            key: FakeValue(key, value) for key, value in binary_values.items()
        }


class FakeDevice:
    def __init__(self, address, name):
        self.address = address
        self.name = name


class FakeAdvertisementData:
    def __init__(self, service_data):
        self.service_data = service_data


class XiaomiS400ListenerTests(unittest.TestCase):
    def listener(self):
        return XiaomiS400Listener(
            DeviceConfig(
                type="xiaomi_s400",
                name="Scale",
                model="yunmai.scales.ms104",
                mac="E3:2B:13:0A:37:D9",
                ble_key="0123456789abcdef0123456789abcdef",
            ),
            ListenConfig(scan_timeout_seconds=1, cooldown_seconds=10),
        )

    def test_measurement_from_complete_stabilized_update(self):
        update = FakeUpdate(
            {"Mass": 48.9, "Impedance High": 428.0, "Impedance Low": 462.0},
            {"Stabilized": True},
        )
        measurement = self.listener()._measurement_from_update(update)
        self.assertIsNotNone(measurement)
        self.assertEqual(measurement.weight_kg, 48.9)
        self.assertEqual(measurement.impedance_high, 428)
        self.assertEqual(measurement.impedance_low, 462)
        self.assertIsNone(measurement.heart_rate)

    def test_measurement_ignores_unstable_update(self):
        update = FakeUpdate(
            {"Mass": 48.9, "Impedance High": 428.0, "Impedance Low": 462.0},
            {"Stabilized": False},
        )
        self.assertIsNone(self.listener()._measurement_from_update(update))

    def test_measurement_requires_impedance(self):
        update = FakeUpdate({"Mass": 48.9, "Impedance Low": 462.0}, {"Stabilized": True})
        self.assertIsNone(self.listener()._measurement_from_update(update))

    def test_describes_incomplete_update(self):
        update = FakeUpdate({"Mass": 48.9, "Impedance Low": 462.0}, {"Stabilized": True})
        description = _describe_update(update)
        self.assertIn("Mass", description)
        self.assertIn("Impedance Low", description)
        self.assertIn("Impedance High", description)

    def test_matches_macos_s400_name_and_fe95_suffix(self):
        config = DeviceConfig(
            type="xiaomi_s400",
            name="Scale",
            model="yunmai.scales.ms104",
            mac="E3:2B:13:0A:37:D9",
            ble_key="0123456789abcdef0123456789abcdef",
        )
        self.assertTrue(
            _matches_target_device(
                FakeDevice("B40914D1-8EB7-DB31-5F1A-9C10FDCD8015", "Mijia Scale S400 37D9"),
                FakeAdvertisementData({"0000fe95-0000-1000-8000-00805f9b34fb": b"abc"}),
                config,
            )
        )

    def test_matches_configured_ble_address(self):
        config = DeviceConfig(
            type="xiaomi_s400",
            name="Scale",
            model="yunmai.scales.ms104",
            mac="E3:2B:13:0A:37:D9",
            ble_key="0123456789abcdef0123456789abcdef",
            ble_address="B40914D1-8EB7-DB31-5F1A-9C10FDCD8015",
        )
        self.assertTrue(
            _matches_target_device(
                FakeDevice("B40914D1-8EB7-DB31-5F1A-9C10FDCD8015", None),
                FakeAdvertisementData({}),
                config,
            )
        )

    def test_normalizes_objc_like_strings(self):
        class ObjcLikeString:
            def __str__(self):
                return "0000fe95-0000-1000-8000-00805f9b34fb"

        self.assertEqual(_to_str(ObjcLikeString()), "0000fe95-0000-1000-8000-00805f9b34fb")
        normalized = _normalize_service_data({ObjcLikeString(): bytearray(b"abc")})
        self.assertEqual(normalized, {"0000fe95-0000-1000-8000-00805f9b34fb": b"abc"})


if __name__ == "__main__":
    unittest.main()
