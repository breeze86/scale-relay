"""Configuration loading and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scale_relay.errors import ConfigError

MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")
HEX32_RE = re.compile(r"^[0-9A-Fa-f]{32}$")


@dataclass(frozen=True)
class XiaomiConfig:
    region: str = "cn"


@dataclass(frozen=True)
class DeviceConfig:
    type: str
    mac: str
    ble_key: str
    hci: int = 0
    name: str | None = None
    model: str | None = None
    ble_address: str | None = None


@dataclass(frozen=True)
class ListenConfig:
    scan_timeout_seconds: int = 180
    cooldown_seconds: int = 10


@dataclass(frozen=True)
class ProfileConfig:
    user_id: str = "default"
    gender: str | None = None
    height_cm: float | None = None


@dataclass(frozen=True)
class HistoryConfig:
    enabled: bool = True
    storage_path: str = "data/measurements.sqlite3"
    recent_measurements_limit: int = 21
    statistics_days: int = 30
    include_weekly_series: bool = True


@dataclass(frozen=True)
class PromptConfig:
    text: str = (
        "目标用户正在进行减脂体重管理，目标是在保证健康和生活可持续的前提下，"
        "逐步降低体重并保持稳定习惯。\n\n"
        "请结合本次称重数据、最近称重记录、统计摘要和每周趋势，"
        "分析本次体重变化。\n"
        "输出适合微信阅读的简短中文消息。\n\n"
        "要求：\n"
        "1. 重点关注体重变化趋势、波动是否正常、是否需要调整节奏。\n"
        "2. 可以给出饮食、运动、作息和称重习惯等日常建议。\n"
        "3. 不要做医疗诊断。\n"
        "4. 如果历史数据不足，请明确说明暂时无法判断长期趋势。\n"
        "5. 不要鼓励极端节食、过度运动或短期快速减重。"
    )


@dataclass(frozen=True)
class RetryConfig:
    attempts: int = 3
    backoff_seconds: float = 2.0


@dataclass(frozen=True)
class SinkConfig:
    type: str
    url: str | None = None
    secret: str | None = None
    event_type: str = "weight_measurement"
    intent: str = "analyze_and_notify"
    timeout_seconds: float = 10.0
    retry: RetryConfig = field(default_factory=RetryConfig)


@dataclass(frozen=True)
class AppConfig:
    xiaomi: XiaomiConfig
    device: DeviceConfig
    listen: ListenConfig
    profile: ProfileConfig
    history: HistoryConfig
    prompt: PromptConfig
    sink: SinkConfig


def default_config_paths() -> list[Path]:
    return [
        Path("config.yaml"),
        Path.home() / ".config" / "scale-relay" / "config.yaml",
        Path("/etc/scale-relay/config.yaml"),
    ]


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path) if path else _first_existing_config_path()
    data = _load_yaml(config_path)
    return app_config_from_dict(data)


def write_config(config: AppConfig, path: str | Path) -> None:
    validate_config(config)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(app_config_to_yaml(config), encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass


def with_device_credentials(
    config: AppConfig,
    *,
    name: str | None,
    model: str | None,
    mac: str,
    ble_key: str,
) -> AppConfig:
    updated = AppConfig(
        xiaomi=config.xiaomi,
        device=DeviceConfig(
            type="xiaomi_s400",
            name=name or config.device.name,
            model=model or config.device.model,
            mac=mac,
            ble_key=ble_key,
            hci=config.device.hci,
            ble_address=config.device.ble_address,
        ),
        listen=config.listen,
        profile=config.profile,
        history=config.history,
        prompt=config.prompt,
        sink=config.sink,
    )
    validate_config(updated)
    return updated


def app_config_from_dict(data: dict[str, Any]) -> AppConfig:
    try:
        xiaomi_data = data.get("xiaomi") or {}
        device_data = data["device"]
        listen_data = data.get("listen") or {}
        history_data = data.get("history") or {}
        prompt_data = data.get("prompt") or {}
        sink_data = data["sink"]
    except KeyError as exc:
        raise ConfigError(f"Missing required config section: {exc.args[0]}") from exc

    retry_data = sink_data.get("retry") or {}
    # Backward compatibility for configs briefly using sink.extra.
    profile_data = data.get("profile") or sink_data.get("extra") or {}
    sink = SinkConfig(
        type=str(sink_data["type"]),
        url=sink_data.get("url"),
        secret=sink_data.get("secret"),
        event_type=str(sink_data.get("event_type", "weight_measurement")),
        intent=str(sink_data.get("intent", "analyze_and_notify")),
        timeout_seconds=float(sink_data.get("timeout_seconds", 10.0)),
        retry=RetryConfig(
            attempts=int(retry_data.get("attempts", 3)),
            backoff_seconds=float(retry_data.get("backoff_seconds", 2.0)),
        ),
    )
    config = AppConfig(
        xiaomi=XiaomiConfig(region=str(xiaomi_data.get("region", "cn"))),
        device=DeviceConfig(
            type=str(device_data["type"]),
            name=device_data.get("name"),
            model=device_data.get("model"),
            mac=str(device_data["mac"]),
            ble_key=str(device_data["ble_key"]),
            hci=int(device_data.get("hci", 0)),
            ble_address=device_data.get("ble_address"),
        ),
        listen=ListenConfig(
            scan_timeout_seconds=int(listen_data.get("scan_timeout_seconds", 180)),
            cooldown_seconds=int(listen_data.get("cooldown_seconds", 10)),
        ),
        profile=ProfileConfig(
            user_id=str(profile_data.get("user_id", "default")),
            gender=profile_data.get("gender"),
            height_cm=(
                float(profile_data["height_cm"])
                if profile_data.get("height_cm") is not None
                else None
            ),
        ),
        history=HistoryConfig(
            enabled=bool(history_data.get("enabled", True)),
            storage_path=str(history_data.get("storage_path", "data/measurements.sqlite3")),
            recent_measurements_limit=int(history_data.get("recent_measurements_limit", 21)),
            statistics_days=int(history_data.get("statistics_days", 30)),
            include_weekly_series=bool(history_data.get("include_weekly_series", True)),
        ),
        prompt=PromptConfig(text=str(prompt_data.get("text", PromptConfig().text))),
        sink=sink,
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    if config.device.type != "xiaomi_s400":
        raise ConfigError("Only device.type=xiaomi_s400 is supported in the first version")
    if not MAC_RE.match(config.device.mac):
        raise ConfigError("device.mac must be a valid MAC address")
    if not HEX32_RE.match(config.device.ble_key):
        raise ConfigError("device.ble_key must be 32 hex characters")
    if config.device.hci < 0:
        raise ConfigError("device.hci must be a non-negative integer")
    if config.listen.scan_timeout_seconds <= 0:
        raise ConfigError("listen.scan_timeout_seconds must be greater than 0")
    if config.listen.cooldown_seconds < 0:
        raise ConfigError("listen.cooldown_seconds must be non-negative")
    if config.profile.height_cm is not None and config.profile.height_cm <= 0:
        raise ConfigError("profile.height_cm must be greater than 0")
    if not config.profile.user_id.strip():
        raise ConfigError("profile.user_id is required")
    if config.history.recent_measurements_limit <= 0:
        raise ConfigError("history.recent_measurements_limit must be greater than 0")
    if config.history.statistics_days <= 0:
        raise ConfigError("history.statistics_days must be greater than 0")
    if not config.history.storage_path:
        raise ConfigError("history.storage_path is required")
    if not config.prompt.text.strip():
        raise ConfigError("prompt.text is required")
    if config.sink.type not in {"stdout", "hermes_webhook"}:
        raise ConfigError("sink.type must be one of: stdout, hermes_webhook")
    if config.sink.retry.attempts <= 0:
        raise ConfigError("sink.retry.attempts must be greater than 0")
    if config.sink.retry.backoff_seconds < 0:
        raise ConfigError("sink.retry.backoff_seconds must be non-negative")
    if config.sink.type == "hermes_webhook":
        if not config.sink.url:
            raise ConfigError("sink.url is required for hermes_webhook")
        if not config.sink.secret:
            raise ConfigError("sink.secret is required for hermes_webhook")


def app_config_to_yaml(config: AppConfig) -> str:
    lines = [
        "xiaomi:",
        f"  region: {_quote_yaml_scalar(config.xiaomi.region)}",
        "",
        "device:",
        f"  type: {_quote_yaml_scalar(config.device.type)}",
        f"  name: {_quote_yaml_scalar(config.device.name or '')}",
        f"  model: {_quote_yaml_scalar(config.device.model or '')}",
        f"  mac: {_quote_yaml_scalar(config.device.mac.upper())}",
    ]
    if config.device.ble_address:
        lines.append(f"  ble_address: {_quote_yaml_scalar(config.device.ble_address)}")
    lines.extend(
        [
            f"  ble_key: {_quote_yaml_scalar(config.device.ble_key)}",
            f"  hci: {config.device.hci}",
            "",
            "listen:",
            f"  scan_timeout_seconds: {config.listen.scan_timeout_seconds}",
            f"  cooldown_seconds: {config.listen.cooldown_seconds}",
            "",
            "profile:",
            f"  user_id: {_quote_yaml_scalar(config.profile.user_id)}",
            f"  gender: {_quote_yaml_scalar(config.profile.gender or '')}",
            f"  height_cm: {_format_yaml_scalar(config.profile.height_cm)}",
            "",
            "history:",
            f"  enabled: {_format_yaml_scalar(config.history.enabled)}",
            f"  storage_path: {_quote_yaml_scalar(config.history.storage_path)}",
            f"  recent_measurements_limit: {config.history.recent_measurements_limit}",
            f"  statistics_days: {config.history.statistics_days}",
            f"  include_weekly_series: {_format_yaml_scalar(config.history.include_weekly_series)}",
            "",
            "prompt:",
            "  text: |",
        ]
    )
    lines.extend(f"    {line}" for line in config.prompt.text.splitlines())
    lines.extend(
        [
            "",
            "sink:",
            f"  type: {_quote_yaml_scalar(config.sink.type)}",
            f"  url: {_quote_yaml_scalar(config.sink.url or '')}",
            f"  secret: {_quote_yaml_scalar(config.sink.secret or '')}",
            f"  event_type: {_quote_yaml_scalar(config.sink.event_type)}",
            f"  intent: {_quote_yaml_scalar(config.sink.intent)}",
        ]
    )
    lines.extend(
        [
            f"  timeout_seconds: {config.sink.timeout_seconds:g}",
            "  retry:",
            f"    attempts: {config.sink.retry.attempts}",
            f"    backoff_seconds: {config.sink.retry.backoff_seconds:g}",
            "",
        ]
    )
    return "\n".join(lines)


def _first_existing_config_path() -> Path:
    for path in default_config_paths():
        if path.exists():
            return path
    candidates = ", ".join(str(path) for path in default_config_paths())
    raise ConfigError(f"No config file found. Checked: {candidates}")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file does not exist: {path}")
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        loaded = _load_simple_yaml(path.read_text(encoding="utf-8"))
    else:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ConfigError("Config file must contain a YAML mapping")
    return loaded


def _quote_yaml_scalar(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return _quote_yaml_scalar(str(value))


def _load_simple_yaml(content: str) -> dict[str, Any]:
    """Parse the small YAML subset used by config.example.yaml.

    This fallback keeps config validation usable before optional dependencies are
    installed. It intentionally supports only nested mappings with scalar values.
    """
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    lines = content.splitlines()
    line_index = 0

    while line_index < len(lines):
        raw_line = lines[line_index]
        line_number = line_index + 1
        line_index += 1
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if "\t" in raw_line:
            raise ConfigError(f"Tabs are not supported in config YAML at line {line_number}")

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if ":" not in stripped:
            raise ConfigError(f"Invalid config YAML at line {line_number}")

        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key:
            raise ConfigError(f"Empty config key at line {line_number}")

        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ConfigError(f"Invalid indentation at line {line_number}")

        parent = stack[-1][1]
        if raw_value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        elif raw_value in {"|", ">"}:
            block_lines: list[str] = []
            block_indent: int | None = None
            while line_index < len(lines):
                next_line = lines[line_index]
                if not next_line.strip():
                    block_lines.append("")
                    line_index += 1
                    continue
                next_indent = len(next_line) - len(next_line.lstrip(" "))
                if next_indent <= indent:
                    break
                if block_indent is None:
                    block_indent = next_indent
                block_lines.append(next_line[block_indent:])
                line_index += 1
            if raw_value == ">":
                parent[key] = " ".join(line.strip() for line in block_lines)
            else:
                parent[key] = "\n".join(block_lines)
        else:
            parent[key] = _parse_simple_scalar(raw_value)

    return root


def _parse_simple_scalar(value: str) -> Any:
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
