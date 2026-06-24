"""Command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import sys
from dataclasses import replace
from pathlib import Path

from scale_relay.ble.xiaomi_s400 import debug_scan_ble
from scale_relay.config import (
    AppConfig,
    DeviceConfig,
    HistoryConfig,
    ListenConfig,
    PromptConfig,
    RetryConfig,
    SinkConfig,
    ProfileConfig,
    XiaomiConfig,
    load_config,
    with_device_credentials,
    write_config,
)
from scale_relay.errors import ScaleRelayError
from scale_relay.doctor import check_ble_environment, log_ble_environment_check
from scale_relay.security import mask_secret
from scale_relay.service import run_listen, run_once
from scale_relay.xiaomi_cloud.client import XiaomiCloudClient, normalize_regions
from scale_relay.xiaomi_cloud.extract_key import extract_scale_credentials
from scale_relay.xiaomi_cloud.session_store import load_session, save_session


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.log_level)
    try:
        return int(args.func(args) or 0)
    except ScaleRelayError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scale-relay")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--hci", type=int, help="Linux HCI adapter index")
    doctor_parser.set_defaults(func=_doctor)

    config_parser = subparsers.add_parser("config")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    validate_parser = config_subparsers.add_parser("validate")
    validate_parser.set_defaults(func=_config_validate)
    init_parser = config_subparsers.add_parser("init")
    init_parser.set_defaults(func=_config_init)

    xiaomi_parser = subparsers.add_parser("xiaomi")
    xiaomi_subparsers = xiaomi_parser.add_subparsers(dest="xiaomi_command", required=True)
    login_parser = xiaomi_subparsers.add_parser("login")
    login_parser.add_argument("--host", default="127.0.0.1", help="Host shown for QR image URL")
    login_parser.add_argument("--image-port", type=int, default=31415, help="Local QR image server port")
    login_parser.set_defaults(func=_xiaomi_login)

    devices_parser = xiaomi_subparsers.add_parser("devices")
    devices_parser.add_argument("--region", default="cn", help="Xiaomi region")
    devices_parser.add_argument("--all-regions", action="store_true", help="Check all known Xiaomi regions")
    devices_parser.set_defaults(func=_xiaomi_devices)

    extract_parser = xiaomi_subparsers.add_parser("extract-key")
    extract_parser.add_argument("--region", default="cn", help="Xiaomi region")
    extract_parser.add_argument("--all-regions", action="store_true", help="Check all known Xiaomi regions")
    extract_parser.add_argument("--mac", help="Filter by MAC address")
    extract_parser.add_argument("--did", help="Filter by Xiaomi device ID")
    extract_parser.add_argument(
        "--write-config",
        action="store_true",
        help="Write extracted MAC and BLE KEY into the configured config file",
    )
    extract_parser.set_defaults(func=_xiaomi_extract_key)

    once_parser = subparsers.add_parser("once")
    once_parser.add_argument(
        "--sink",
        choices=["stdout", "hermes_webhook"],
        help="Temporarily override sink.type from config",
    )
    once_parser.set_defaults(func=_once)

    listen_parser = subparsers.add_parser("listen")
    listen_parser.add_argument(
        "--sink",
        choices=["stdout", "hermes_webhook"],
        help="Temporarily override sink.type from config",
    )
    listen_parser.set_defaults(func=_listen)

    debug_parser = subparsers.add_parser("debug")
    debug_subparsers = debug_parser.add_subparsers(dest="debug_command", required=True)
    scan_parser = debug_subparsers.add_parser("scan-ble")
    scan_parser.add_argument("--seconds", type=float, default=20.0, help="Scan duration")
    scan_parser.add_argument("--hci", type=int, default=0, help="Linux HCI adapter index")
    scan_parser.set_defaults(func=_debug_scan_ble)

    return parser


def _config_validate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print("config ok")
    print(f"device.mac={config.device.mac.upper()}")
    print(f"device.ble_key={mask_secret(config.device.ble_key)}")
    print(f"sink.type={config.sink.type}")
    return 0


def _config_init(_: argparse.Namespace) -> int:
    print("Initializing Scale Relay config.")
    output = _prompt("Config path", "config.yaml")
    region = _prompt("Xiaomi region", "cn")
    name = "Xiaomi Body Composition Scale S400"
    model = "yunmai.scales.ms104"
    mac = "00:00:00:00:00:00"
    ble_key = "0" * 32
    print("using temporary device placeholders; run xiaomi extract-key --write-config later")
    hci = int(_prompt("BLE adapter index", "0"))
    user_id = _prompt("Profile user_id", "default")
    gender = _prompt("Profile gender", "female")
    height_cm = float(_prompt("Profile height_cm", "160"))
    history_storage_path = _prompt("History storage path", "data/measurements.sqlite3")
    prompt_text = PromptConfig().text
    print("using default prompt.text; edit config.yaml if you need a different analysis intent")
    sink_type = _prompt("Sink type", "stdout")
    if sink_type not in {"stdout", "hermes_webhook"}:
        raise ScaleRelayError("Sink type must be stdout or hermes_webhook")

    webhook_url = None
    webhook_secret = None
    if sink_type == "hermes_webhook":
        webhook_url = _prompt("Hermes Webhook URL", "http://127.0.0.1:8644/webhooks/events")
        webhook_secret = getpass.getpass("Hermes Webhook secret (hidden): ").strip()

    config = AppConfig(
        xiaomi=XiaomiConfig(region=region),
        device=DeviceConfig(
            type="xiaomi_s400",
            name=name,
            model=model,
            mac=mac,
            ble_key=ble_key,
            hci=hci,
        ),
        listen=ListenConfig(),
        profile=ProfileConfig(user_id=user_id, gender=gender, height_cm=height_cm),
        history=HistoryConfig(storage_path=history_storage_path),
        prompt=PromptConfig(text=prompt_text),
        sink=SinkConfig(
            type=sink_type,
            url=webhook_url,
            secret=webhook_secret,
            retry=RetryConfig(),
        ),
    )
    write_config(config, Path(output))
    print(f"config written: {output}")
    return 0


def _xiaomi_login(args: argparse.Namespace) -> int:
    client = XiaomiCloudClient()
    qr = client.begin_qr_login(host=args.host, image_port=args.image_port)
    print("Scan the Xiaomi QR code with Xiaomi Home / Mi Home.")
    if qr.local_image_url:
        print(f"QR image URL: {qr.local_image_url}")
    if qr.image_file:
        print(f"QR image file: {qr.image_file}")
    print(f"Login URL: {qr.login_url}")
    print("Waiting for QR login confirmation...")
    session = client.finish_qr_login()
    path = save_session(session)
    print(f"xiaomi session saved: {path}")
    return 0


def _xiaomi_devices(args: argparse.Namespace) -> int:
    client = XiaomiCloudClient(load_session())
    regions = normalize_regions(args.region, all_regions=args.all_regions)
    devices = client.list_devices(regions)
    if not devices:
        print("no devices found")
        return 0
    for device in devices:
        marker = " [S400]" if device.is_s400 else ""
        print(
            f"{device.region}\t{device.did}\t{device.mac or '-'}\t"
            f"{device.model or '-'}\t{device.name or '-'}{marker}"
        )
    return 0


def _xiaomi_extract_key(args: argparse.Namespace) -> int:
    credentials = extract_scale_credentials(
        region=args.region,
        all_regions=args.all_regions,
        mac=args.mac,
        did=args.did,
    )
    print(f"name={credentials.name or ''}")
    print(f"model={credentials.model or ''}")
    print(f"did={credentials.did}")
    print(f"region={credentials.region}")
    print(f"mac={credentials.mac.upper()}")
    print(f"ble_key={mask_secret(credentials.ble_key)}")

    if args.write_config:
        config_path = Path(args.config or "config.yaml")
        config = load_config(config_path)
        updated = with_device_credentials(
            config,
            name=credentials.name,
            model=credentials.model,
            mac=credentials.mac,
            ble_key=credentials.ble_key,
        )
        write_config(updated, config_path)
        print(f"config updated: {config_path}")
    return 0


def _once(args: argparse.Namespace) -> int:
    config = _load_config_with_overrides(args)
    asyncio.run(run_once(config))
    return 0


def _listen(args: argparse.Namespace) -> int:
    config = _load_config_with_overrides(args)
    asyncio.run(run_listen(config))
    return 0


def _debug_scan_ble(args: argparse.Namespace) -> int:
    log_ble_environment_check(args.hci)
    asyncio.run(debug_scan_ble(duration_seconds=args.seconds, hci=args.hci))
    return 0


def _doctor(args: argparse.Namespace) -> int:
    hci = args.hci
    if hci is None:
        try:
            hci = load_config(args.config).device.hci
        except ScaleRelayError:
            hci = 0
    has_warning = False
    for check in check_ble_environment(hci):
        print(f"{check.level.upper()}: {check.message}")
        if check.level == "warning":
            has_warning = True
    if has_warning:
        print("environment check completed with warnings")
    else:
        print("environment check ok")
    return 0


def _prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{label}{suffix}: ").strip()
    if value:
        return value
    if default is not None:
        return default
    raise ScaleRelayError(f"{label} is required")


def _configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def _load_config_with_overrides(args: argparse.Namespace) -> AppConfig:
    config = load_config(args.config)
    sink_type = getattr(args, "sink", None)
    if not sink_type:
        return config
    if sink_type == config.sink.type:
        return config
    return replace(config, sink=replace(config.sink, type=sink_type))


if __name__ == "__main__":
    raise SystemExit(main())
