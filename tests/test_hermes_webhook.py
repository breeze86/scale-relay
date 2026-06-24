import json
import logging
import unittest
from contextlib import redirect_stdout
from contextlib import redirect_stderr
from io import StringIO

from scale_relay.config import (
    AppConfig,
    DeviceConfig,
    HistoryConfig,
    ListenConfig,
    ProfileConfig,
    PromptConfig,
    RetryConfig,
    SinkConfig,
    XiaomiConfig,
)
from scale_relay.events import build_measurement_event
from scale_relay.models import WeightMeasurement
from scale_relay.security import hmac_sha256_hex
from scale_relay.sinks.hermes_webhook import HermesWebhookSink


def measurement():
    return WeightMeasurement(
        device_type="xiaomi_s400",
        device_name="Xiaomi Body Composition Scale S400",
        device_mac="E3:2B:13:0A:37:D9",
        timestamp=1782205025,
        weight_kg=48.9,
        impedance_high=428,
        impedance_low=462,
        heart_rate=None,
        stabilized=True,
    )


def app_config(profile=None, sink=None):
    return AppConfig(
        xiaomi=XiaomiConfig(region="cn"),
        device=DeviceConfig(
            type="xiaomi_s400",
            name="Xiaomi Body Composition Scale S400",
            model="yunmai.scales.ms104",
            mac="E3:2B:13:0A:37:D9",
            ble_key="0123456789abcdef0123456789abcdef",
        ),
        listen=ListenConfig(),
        profile=profile or ProfileConfig(),
        history=HistoryConfig(enabled=False),
        prompt=PromptConfig(text="请分析本次称重。"),
        sink=sink
        or SinkConfig(
            type="hermes_webhook",
            url="http://127.0.0.1:8644/webhooks/events",
            secret="scale-relay-secret",
        ),
    )


class HermesWebhookTests(unittest.TestCase):
    def test_build_event(self):
        event = build_measurement_event(
            measurement=measurement(),
            config=app_config(),
            history_store=None,
        )
        self.assertEqual(event["event_type"], "weight_measurement")
        self.assertEqual(event["payload"]["current"]["weight_kg"], 48.9)
        self.assertIn("history", event["payload"])
        self.assertNotIn("delivery", event)
        self.assertIn("message", event)

    def test_build_event_with_profile_message(self):
        event = build_measurement_event(
            measurement=measurement(),
            config=app_config(profile=ProfileConfig(gender="male", height_cm=170)),
            history_store=None,
        )
        self.assertEqual(event["profile"], {"user_id": "default", "gender": "male", "height_cm": 170})
        self.assertIn("性别：男", event["message"])
        self.assertIn("身高：170 cm", event["message"])
        self.assertIn("BMI：16.9", event["message"])

    def test_build_request_signature(self):
        config = SinkConfig(
            type="hermes_webhook",
            url="http://127.0.0.1:8644/webhooks/events",
            secret="scale-relay-secret",
            retry=RetryConfig(attempts=1, backoff_seconds=0),
        )
        event = build_measurement_event(
            measurement=measurement(),
            config=app_config(sink=config),
            history_store=None,
        )
        request = HermesWebhookSink(config).build_request(event)
        self.assertEqual(
            request.headers["X-Webhook-Signature"],
            hmac_sha256_hex("scale-relay-secret", request.body),
        )
        self.assertIn("X-Request-ID", request.headers)
        decoded = json.loads(request.body.decode("utf-8"))
        self.assertEqual(decoded["payload"]["current"]["device_type"], "xiaomi_s400")

    def test_send_failure_falls_back_to_stdout(self):
        class FailingHermesWebhookSink(HermesWebhookSink):
            def _send_once(self, request_data):
                raise OSError("connection refused")

        config = SinkConfig(
            type="hermes_webhook",
            url="http://127.0.0.1:1/webhooks/events",
            secret="scale-relay-secret",
            retry=RetryConfig(attempts=1, backoff_seconds=0),
        )
        output = StringIO()
        error_output = StringIO()
        event = build_measurement_event(
            measurement=measurement(),
            config=app_config(sink=config),
            history_store=None,
        )
        logging.disable(logging.CRITICAL)
        with redirect_stdout(output), redirect_stderr(error_output):
            import asyncio

            asyncio.run(FailingHermesWebhookSink(config).send(event))
        logging.disable(logging.NOTSET)

        decoded = json.loads(output.getvalue())
        self.assertEqual(decoded["payload"]["current"]["weight_kg"], 48.9)
        self.assertEqual(decoded["payload"]["current"]["device_type"], "xiaomi_s400")
        self.assertIn("falling back to stdout", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
