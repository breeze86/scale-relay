"""Xiaomi Mijia Scale S400 BLE listener."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from scale_relay.config import DeviceConfig, ListenConfig
from scale_relay.errors import BleDecryptionError, DependencyMissingError, MeasurementTimeoutError
from scale_relay.models import WeightMeasurement

LOGGER = logging.getLogger(__name__)


class XiaomiS400Listener:
    """Listen for Xiaomi S400 encrypted BLE advertisements."""

    def __init__(self, device: DeviceConfig, listen: ListenConfig) -> None:
        self._device = device
        self._listen = listen
        self._last_emit_key: tuple[float, int, int] | None = None
        self._last_emit_at = 0.0

    async def once(self) -> WeightMeasurement:
        async for measurement in self.listen():
            return measurement
        raise MeasurementTimeoutError("No measurement collected")

    async def listen(self) -> AsyncIterator[WeightMeasurement]:
        deps = _load_ble_dependencies()
        parser = deps.XiaomiBluetoothDeviceData(bindkey=bytes.fromhex(self._device.ble_key))
        queue: asyncio.Queue[WeightMeasurement] = asyncio.Queue()
        stop_event = asyncio.Event()
        started_at = time.time()
        target_mac = self._device.mac.upper()
        last_found_log_at = 0.0

        decryption_handler = _DecryptionFailedHandler(stop_event)
        xiaomi_logger = logging.getLogger("xiaomi_ble.parser")
        xiaomi_logger.addHandler(decryption_handler)

        def detection_callback(device: Any, advertisement_data: Any) -> None:
            nonlocal last_found_log_at
            try:
                if stop_event.is_set():
                    return
                if not _matches_target_device(device, advertisement_data, self._device):
                    return
                ble_address = _to_str(getattr(device, "address", ""))
                parser_address = self._device.mac.upper()
                name = _to_str(getattr(device, "name", "")) or "Mijia Scale S400"
                now = time.time()
                if now - last_found_log_at >= 5:
                    LOGGER.info(
                        "Found target BLE device ble_address=%s parser_mac=%s name=%s rssi=%s",
                        ble_address,
                        parser_address,
                        name,
                        getattr(advertisement_data, "rssi", None),
                    )
                    last_found_log_at = now
                service_info = deps.BluetoothServiceInfo(
                    name=name,
                    address=parser_address,
                    rssi=int(getattr(advertisement_data, "rssi", 0)),
                    manufacturer_data=_normalize_manufacturer_data(
                        getattr(advertisement_data, "manufacturer_data", {}) or {}
                    ),
                    service_data=_normalize_service_data(
                        getattr(advertisement_data, "service_data", {}) or {}
                    ),
                    service_uuids=[
                        _to_str(uuid)
                        for uuid in (getattr(advertisement_data, "service_uuids", []) or [])
                    ],
                    source=parser_address,
                )
                if not parser.supported(service_info):
                    LOGGER.debug("Target advertisement is not supported by xiaomi-ble parser yet")
                    return
                update = parser.update(service_info)
                measurement = self._measurement_from_update(update)
                if measurement and self._should_emit(measurement):
                    LOGGER.info(
                        "Complete S400 measurement parsed weight_kg=%.1f impedance_high=%s impedance_low=%s",
                        measurement.weight_kg,
                        measurement.impedance_high,
                        measurement.impedance_low,
                    )
                    queue.put_nowait(measurement)
                    stop_event.set()
            except Exception:
                LOGGER.exception("Failed to process S400 BLE advertisement")

        scanner = _create_scanner(deps.BleakScanner, detection_callback, self._device.hci)
        LOGGER.info(
            "Starting S400 BLE scan target_mac=%s adapter=hci%s timeout_seconds=%s",
            target_mac,
            self._device.hci,
            self._listen.scan_timeout_seconds,
        )
        await scanner.start()
        LOGGER.info("S400 BLE scan started")
        try:
            while True:
                timeout = max(0.1, self._listen.scan_timeout_seconds - (time.time() - started_at))
                queue_task = asyncio.create_task(queue.get())
                stop_task = asyncio.create_task(stop_event.wait())
                done, pending = await asyncio.wait(
                    {queue_task, stop_task},
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if queue_task in done:
                    yield queue_task.result()
                    return
                if stop_task in done:
                    if decryption_handler.failed:
                        raise BleDecryptionError("S400 BLE decryption failed; check BLE KEY")
                    return
                raise MeasurementTimeoutError("Timed out waiting for S400 measurement")
        finally:
            await scanner.stop()
            LOGGER.info("S400 BLE scan stopped")
            xiaomi_logger.removeHandler(decryption_handler)

    def _measurement_from_update(self, update: Any) -> WeightMeasurement | None:
        values = _entity_values(update)
        binary_values = _binary_entity_values(update)

        mass = values.get("Mass")
        impedance_low = values.get("Impedance Low")
        impedance_high = values.get("Impedance High", values.get("Impedance"))
        stabilized = binary_values.get("Stabilized")
        heart_rate = values.get("Heart Rate")

        if mass is None or impedance_low is None or impedance_high is None:
            return None
        if stabilized is not None and stabilized is not True:
            return None

        return WeightMeasurement(
            device_type="xiaomi_s400",
            device_name=self._device.name,
            device_mac=self._device.mac,
            timestamp=int(time.time()),
            weight_kg=float(mass),
            impedance_high=int(round(float(impedance_high))),
            impedance_low=int(round(float(impedance_low))),
            heart_rate=int(heart_rate) if heart_rate is not None else None,
            stabilized=bool(stabilized) if stabilized is not None else True,
            source="ble",
        )

    def _should_emit(self, measurement: WeightMeasurement) -> bool:
        key = (measurement.weight_kg, measurement.impedance_high, measurement.impedance_low)
        now = time.time()
        if self._last_emit_key == key and now - self._last_emit_at < self._listen.cooldown_seconds:
            return False
        self._last_emit_key = key
        self._last_emit_at = now
        return True


class _DecryptionFailedHandler(logging.Handler):
    def __init__(self, stop_event: asyncio.Event) -> None:
        super().__init__()
        self._stop_event = stop_event
        self.failed = False

    def emit(self, record: logging.LogRecord) -> None:
        if "Decryption failed" in record.getMessage():
            self.failed = True
            self._stop_event.set()
            LOGGER.error("S400 BLE decryption failed; check BLE KEY")


class _BleDependencies:
    def __init__(self, bleak_scanner: Any, service_info: Any, parser: Any) -> None:
        self.BleakScanner = bleak_scanner
        self.BluetoothServiceInfo = service_info
        self.XiaomiBluetoothDeviceData = parser


def _load_ble_dependencies() -> _BleDependencies:
    try:
        from bleak import BleakScanner
        from bluetooth_sensor_state_data import BluetoothServiceInfo
        from xiaomi_ble.parser import XiaomiBluetoothDeviceData
    except ImportError as exc:
        raise DependencyMissingError(
            "BLE collection requires bleak, bluetooth-sensor-state-data, and xiaomi-ble"
        ) from exc
    return _BleDependencies(BleakScanner, BluetoothServiceInfo, XiaomiBluetoothDeviceData)


def _create_scanner(bleak_scanner: Any, detection_callback: Any, hci: int) -> Any:
    adapter = f"hci{hci}"
    try:
        scanner = bleak_scanner(detection_callback=detection_callback, adapter=adapter)
        LOGGER.info("BleakScanner created with adapter=%s", adapter)
        return scanner
    except TypeError:
        LOGGER.info("BleakScanner backend does not accept adapter=%s; using default adapter", adapter)
        return bleak_scanner(detection_callback=detection_callback)


def _matches_target_device(device: Any, advertisement_data: Any, config: DeviceConfig) -> bool:
    address = _to_str(getattr(device, "address", "")).upper()
    name = _to_str(getattr(device, "name", ""))
    configured_mac = config.mac.upper()
    configured_ble_address = (config.ble_address or "").upper()

    if address == configured_mac:
        return True
    if configured_ble_address and address == configured_ble_address:
        return True

    service_data = getattr(advertisement_data, "service_data", {}) or {}
    has_fe95 = any(str(key).lower().startswith("0000fe95") for key in service_data.keys())
    mac_suffix = configured_mac.replace(":", "")[-4:]
    if has_fe95 and "S400" in name.upper() and mac_suffix and mac_suffix in name.upper():
        return True

    return False


def _to_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _normalize_service_data(service_data: dict[Any, Any]) -> dict[str, bytes]:
    return {_to_str(key): bytes(value) for key, value in service_data.items()}


def _normalize_manufacturer_data(manufacturer_data: dict[Any, Any]) -> dict[int, bytes]:
    return {int(key): bytes(value) for key, value in manufacturer_data.items()}


async def debug_scan_ble(duration_seconds: float = 20.0, hci: int = 0) -> None:
    deps = _load_ble_dependencies()
    seen: set[str] = set()

    def detection_callback(device: Any, advertisement_data: Any) -> None:
        key = f"{device.address}|{getattr(advertisement_data, 'rssi', '')}"
        if key in seen:
            return
        seen.add(key)
        service_data = getattr(advertisement_data, "service_data", {}) or {}
        manufacturer_data = getattr(advertisement_data, "manufacturer_data", {}) or {}
        service_uuids = getattr(advertisement_data, "service_uuids", []) or []
        LOGGER.info(
            "BLE device address=%s name=%s rssi=%s service_uuids=%s service_data_keys=%s manufacturer_ids=%s",
            device.address,
            device.name,
            getattr(advertisement_data, "rssi", None),
            service_uuids,
            list(service_data.keys()),
            list(manufacturer_data.keys()),
        )

    scanner = _create_scanner(deps.BleakScanner, detection_callback, hci)
    LOGGER.info("Starting debug BLE scan duration_seconds=%s adapter=hci%s", duration_seconds, hci)
    await scanner.start()
    try:
        await asyncio.sleep(duration_seconds)
    finally:
        await scanner.stop()
        LOGGER.info("Debug BLE scan stopped devices_seen=%s", len(seen))


def _entity_values(update: Any) -> dict[str, Any]:
    if not update or not update.entity_values:
        return {}
    return {value.name: value.native_value for value in update.entity_values.values()}


def _binary_entity_values(update: Any) -> dict[str, Any]:
    if not update or not update.binary_entity_values:
        return {}
    return {value.name: value.native_value for value in update.binary_entity_values.values()}
