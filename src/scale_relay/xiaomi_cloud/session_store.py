"""Persist Xiaomi Cloud sessions for CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from scale_relay.errors import ConfigError
from scale_relay.xiaomi_cloud.models import XiaomiSession


def default_session_path() -> Path:
    return Path.home() / ".config" / "scale-relay" / "xiaomi_session.json"


def save_session(session: XiaomiSession, path: Path | None = None) -> Path:
    target = path or default_session_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target


def load_session(path: Path | None = None) -> XiaomiSession:
    target = path or default_session_path()
    if not target.exists():
        raise ConfigError(f"Xiaomi session not found: {target}. Run xiaomi login first.")
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError("Xiaomi session file is invalid")
    return XiaomiSession.from_dict(data)
