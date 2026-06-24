"""Xiaomi Cloud data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


SUPPORTED_SERVERS = ("cn", "de", "us", "ru", "tw", "sg", "in", "i2")
S400_MODEL = "yunmai.scales.ms104"


@dataclass(frozen=True)
class XiaomiSession:
    user_id: str
    ssecurity: str
    service_token: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "XiaomiSession":
        return cls(
            user_id=str(data["user_id"]),
            ssecurity=str(data["ssecurity"]),
            service_token=str(data["service_token"]),
        )


@dataclass(frozen=True)
class XiaomiDevice:
    name: str | None
    did: str
    mac: str | None
    model: str | None
    region: str
    raw: dict[str, Any]

    @property
    def is_s400(self) -> bool:
        model = (self.model or "").lower()
        name = (self.name or "").lower()
        return model == S400_MODEL or "s400" in name


@dataclass(frozen=True)
class XiaomiScaleCredentials:
    name: str | None
    model: str | None
    did: str
    mac: str
    ble_key: str
    region: str

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)
