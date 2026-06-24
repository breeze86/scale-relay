import unittest

from scale_relay.config import ProfileConfig
from scale_relay.message import build_weight_message, calculate_bmi
from test_hermes_webhook import measurement


class MessageTests(unittest.TestCase):
    def test_calculate_bmi(self):
        self.assertAlmostEqual(calculate_bmi(49.0, 170), 16.955, places=3)

    def test_build_weight_message(self):
        message = build_weight_message(
            measurement(),
            ProfileConfig(gender="female", height_cm=165),
            "请分析本次称重。",
            None,
        )
        self.assertIn("性别：女", message)
        self.assertIn("身高：165 cm", message)
        self.assertIn("体重：48.9 kg", message)
        self.assertIn("BMI：18.0", message)


if __name__ == "__main__":
    unittest.main()
