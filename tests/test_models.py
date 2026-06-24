import unittest

from scale_relay.models import WeightMeasurement


class ModelTests(unittest.TestCase):
    def test_request_id_is_stable(self):
        measurement = WeightMeasurement(
            device_type="xiaomi_s400",
            device_name=None,
            device_mac="E3:2B:13:0A:37:D9",
            timestamp=1782205025,
            weight_kg=48.9,
            impedance_high=428,
            impedance_low=462,
            heart_rate=None,
            stabilized=True,
        )
        self.assertEqual(
            measurement.request_id(),
            "scale-relay:xiaomi_s400:E41B430C12D2:1782205025:48.9:428:462",
        )

    def test_invalid_weight(self):
        with self.assertRaises(ValueError):
            WeightMeasurement(
                device_type="xiaomi_s400",
                device_name=None,
                device_mac="E3:2B:13:0A:37:D9",
                timestamp=1782205025,
                weight_kg=0,
                impedance_high=428,
                impedance_low=462,
                heart_rate=None,
                stabilized=True,
            )


if __name__ == "__main__":
    unittest.main()
