import unittest
from pathlib import Path

from scale_relay.config import ConfigError, app_config_from_dict, app_config_to_yaml
from scale_relay.config import load_config


def valid_config():
    return {
        "xiaomi": {"region": "cn"},
        "device": {
            "type": "xiaomi_s400",
            "name": "Xiaomi Body Composition Scale S400",
            "model": "yunmai.scales.ms104",
            "mac": "E3:2B:13:0A:37:D9",
            "ble_key": "0123456789abcdef0123456789abcdef",
            "hci": 0,
        },
        "listen": {"scan_timeout_seconds": 180, "cooldown_seconds": 10},
        "profile": {
            "user_id": "jj",
            "gender": "male",
            "height_cm": 170,
        },
        "sink": {
            "type": "hermes_webhook",
            "url": "http://127.0.0.1:8644/webhooks/events",
            "secret": "scale-relay-secret",
            "event_type": "weight_measurement",
            "intent": "analyze_and_notify",
        },
    }


class ConfigTests(unittest.TestCase):
    def test_valid_config(self):
        config = app_config_from_dict(valid_config())
        self.assertEqual(config.device.mac, "E3:2B:13:0A:37:D9")
        self.assertEqual(config.sink.type, "hermes_webhook")
        self.assertEqual(config.profile.user_id, "jj")
        self.assertEqual(config.profile.height_cm, 170)

    def test_invalid_ble_key(self):
        data = valid_config()
        data["device"]["ble_key"] = "bad"
        with self.assertRaises(ConfigError):
            app_config_from_dict(data)

    def test_stdout_sink_does_not_require_url(self):
        data = valid_config()
        data["sink"] = {"type": "stdout"}
        config = app_config_from_dict(data)
        self.assertEqual(config.sink.type, "stdout")

    def test_load_example_config_without_pyyaml(self):
        config = load_config(Path("config.example.yaml"))
        self.assertEqual(config.sink.type, "hermes_webhook")

    def test_config_roundtrip_simple_yaml(self):
        config = app_config_from_dict(valid_config())
        yaml_text = app_config_to_yaml(config)
        self.assertIn('type: "hermes_webhook"', yaml_text)
        self.assertIn('user_id: "jj"', yaml_text)
        self.assertIn('ble_key: "0123456789abcdef0123456789abcdef"', yaml_text)
        self.assertIn('height_cm: 170', yaml_text)


if __name__ == "__main__":
    unittest.main()
