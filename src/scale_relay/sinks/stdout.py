"""Stdout sink."""

from __future__ import annotations

import json
from typing import Any

from scale_relay.sinks.base import MeasurementSink


class StdoutSink(MeasurementSink):
    async def send(self, event: dict[str, Any]) -> None:
        print(json.dumps(event, ensure_ascii=False, sort_keys=True))
