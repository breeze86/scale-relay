"""Runtime environment checks."""

from __future__ import annotations

import logging
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnvironmentCheck:
    level: str
    message: str


def check_ble_environment(hci: int = 0) -> list[EnvironmentCheck]:
    """Return lightweight BLE environment checks without changing the system."""

    system = platform.system().lower()
    checks = [
        EnvironmentCheck("ok", f"platform={platform.system() or 'unknown'}"),
        EnvironmentCheck("ok", f"python={platform.python_version()}"),
    ]

    if system == "linux":
        checks.extend(_check_linux_ble(hci))
    elif system == "darwin":
        checks.append(
            EnvironmentCheck(
                "ok",
                "macOS uses CoreBluetooth; BlueZ and hci adapters are not required",
            )
        )
    else:
        checks.append(
            EnvironmentCheck(
                "warning",
                "BLE environment is not explicitly supported on this platform; tested targets are macOS and Linux",
            )
        )

    return checks


def log_ble_environment_check(hci: int = 0) -> None:
    for check in check_ble_environment(hci):
        if check.level == "warning":
            LOGGER.warning("BLE environment check: %s", check.message)
        else:
            LOGGER.info("BLE environment check: %s", check.message)


def _check_linux_ble(hci: int) -> list[EnvironmentCheck]:
    checks: list[EnvironmentCheck] = []

    adapter_path = Path(f"/sys/class/bluetooth/hci{hci}")
    if adapter_path.exists():
        checks.append(EnvironmentCheck("ok", f"Bluetooth adapter hci{hci} exists"))
    else:
        checks.append(
            EnvironmentCheck(
                "warning",
                f"Bluetooth adapter hci{hci} was not found under /sys/class/bluetooth; check device.hci or USB/BLE adapter availability",
            )
        )

    for command in ("bluetoothctl", "hciconfig"):
        if shutil.which(command):
            checks.append(EnvironmentCheck("ok", f"{command} is available"))
        else:
            checks.append(
                EnvironmentCheck(
                    "warning",
                    f"{command} is not available; install BlueZ tools before running BLE scans on Linux",
                )
            )

    return checks
