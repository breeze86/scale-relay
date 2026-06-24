"""Service orchestration."""

from __future__ import annotations

import asyncio
import logging

from scale_relay.ble.xiaomi_s400 import XiaomiS400Listener
from scale_relay.config import AppConfig
from scale_relay.doctor import log_ble_environment_check
from scale_relay.events import build_measurement_event
from scale_relay.history.store import MeasurementHistoryStore
from scale_relay.sinks.factory import create_sink

LOGGER = logging.getLogger(__name__)


async def run_once(config: AppConfig) -> None:
    LOGGER.info("Running once with sink=%s", config.sink.type)
    log_ble_environment_check(config.device.hci)
    listener = XiaomiS400Listener(config.device, config.listen)
    sink = create_sink(config.sink)
    history_store = _create_history_store(config)
    measurement = await listener.once()
    if history_store:
        history_store.add(measurement, config.profile)
    event = build_measurement_event(
        measurement=measurement,
        config=config,
        history_store=history_store,
    )
    await sink.send(event)


async def run_listen(config: AppConfig) -> None:
    LOGGER.info("Running continuously with sink=%s", config.sink.type)
    log_ble_environment_check(config.device.hci)
    listener = XiaomiS400Listener(config.device, config.listen)
    sink = create_sink(config.sink)
    history_store = _create_history_store(config)
    while True:
        async for measurement in listener.listen():
            if history_store:
                history_store.add(measurement, config.profile)
            event = build_measurement_event(
                measurement=measurement,
                config=config,
                history_store=history_store,
            )
            await sink.send(event)
        await asyncio.sleep(0.5)


def _create_history_store(config: AppConfig) -> MeasurementHistoryStore | None:
    if not config.history.enabled:
        return None
    return MeasurementHistoryStore(config.history.storage_path)
