"""Sink factory."""

from __future__ import annotations

from scale_relay.config import SinkConfig
from scale_relay.errors import ConfigError
from scale_relay.sinks.base import MeasurementSink
from scale_relay.sinks.hermes_webhook import HermesWebhookSink
from scale_relay.sinks.stdout import StdoutSink


def create_sink(config: SinkConfig) -> MeasurementSink:
    if config.type == "stdout":
        return StdoutSink()
    if config.type == "hermes_webhook":
        return HermesWebhookSink(config)
    raise ConfigError(f"Unsupported sink type: {config.type}")
