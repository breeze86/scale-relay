"""Hermes Agent Webhook sink."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from scale_relay.config import SinkConfig
from scale_relay.errors import SinkError
from scale_relay.security import hmac_sha256_hex, mask_secret
from scale_relay.sinks.base import MeasurementSink

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class HermesWebhookRequest:
    url: str
    body: bytes
    headers: dict[str, str]


class HermesWebhookSink(MeasurementSink):
    """Send measurements to a Hermes Agent Webhook route."""

    def __init__(self, config: SinkConfig) -> None:
        if not config.url:
            raise SinkError("Hermes Webhook url is required")
        if not config.secret:
            raise SinkError("Hermes Webhook secret is required")
        self._config = config

    async def send(self, event: dict[str, Any]) -> None:
        request = self.build_request(event)
        attempts = self._config.retry.attempts
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                await asyncio.to_thread(self._send_once, request)
                LOGGER.info("Hermes Webhook sent request_id=%s", request.headers["X-Request-ID"])
                return
            except Exception as exc:  # noqa: BLE001 - normalized as SinkError below.
                last_error = exc
                LOGGER.warning(
                    "Hermes Webhook send failed attempt=%s/%s request_id=%s error=%s",
                    attempt,
                    attempts,
                    request.headers["X-Request-ID"],
                    exc,
                )
                if attempt >= attempts:
                    break
                await asyncio.sleep(self._config.retry.backoff_seconds)

        secret = mask_secret(self._config.secret)
        LOGGER.error(
            "Hermes Webhook failed after %s attempts request_id=%s secret=%s error=%s",
            attempts,
            request.headers["X-Request-ID"],
            secret,
            last_error,
        )
        print(
            "Hermes Webhook failed; falling back to stdout measurement output "
            f"request_id={request.headers['X-Request-ID']} error={last_error}",
            file=sys.stderr,
        )
        print(json.dumps(event, ensure_ascii=False, sort_keys=True))

    def build_request(self, event: dict[str, Any]) -> HermesWebhookRequest:
        body = json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac_sha256_hex(self._config.secret or "", body)
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
            "X-Request-ID": _request_id_from_event(event),
            "User-Agent": "scale-relay/0.1.0",
        }
        return HermesWebhookRequest(url=self._config.url or "", body=body, headers=headers)

    def _send_once(self, request_data: HermesWebhookRequest) -> None:
        request = urllib.request.Request(
            request_data.url,
            data=request_data.body,
            headers=request_data.headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310 - user-configured local webhook URL.
                request,
                timeout=self._config.timeout_seconds,
            ) as response:
                status = response.getcode()
                if status < 200 or status >= 300:
                    raise SinkError(f"Hermes Webhook returned non-2xx status: {status}")
        except urllib.error.HTTPError as exc:
            body = exc.read(512).decode("utf-8", errors="replace")
            raise SinkError(f"Hermes Webhook returned {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise SinkError(f"Hermes Webhook request failed: {exc.reason}") from exc


def _request_id_from_event(event: dict[str, Any]) -> str:
    payload = event.get("payload")
    if isinstance(payload, dict):
        current = payload.get("current")
        if isinstance(current, dict):
            device_type = str(current.get("device_type", "unknown"))
            device_mac = str(current.get("device_mac", "unknown")).upper().replace(":", "")
            timestamp = str(current.get("timestamp", "0"))
            weight = current.get("weight_kg", "unknown")
            impedance_high = current.get("impedance_high", "unknown")
            impedance_low = current.get("impedance_low", "unknown")
            return (
                "scale-relay:"
                f"{device_type}:"
                f"{device_mac}:"
                f"{timestamp}:"
                f"{weight}:"
                f"{impedance_high}:"
                f"{impedance_low}"
            )
    return "scale-relay:unknown"
