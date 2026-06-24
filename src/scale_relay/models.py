"""Core data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class WeightMeasurement:
    """A normalized weight measurement collected from a scale."""

    device_type: str
    device_name: str | None
    device_mac: str
    timestamp: int
    weight_kg: float
    impedance_high: int
    impedance_low: int
    heart_rate: int | None
    stabilized: bool
    source: str = "ble"

    def __post_init__(self) -> None:
        if self.device_type != "xiaomi_s400":
            raise ValueError("device_type must be xiaomi_s400")
        if not self.device_mac:
            raise ValueError("device_mac is required")
        if self.timestamp <= 0:
            raise ValueError("timestamp must be greater than 0")
        if self.weight_kg <= 0:
            raise ValueError("weight_kg must be greater than 0")
        if self.impedance_high <= 0:
            raise ValueError("impedance_high must be greater than 0")
        if self.impedance_low <= 0:
            raise ValueError("impedance_low must be greater than 0")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def request_id(self) -> str:
        normalized_mac = self.device_mac.upper().replace(":", "")
        return (
            "scale-relay:"
            f"{self.device_type}:"
            f"{normalized_mac}:"
            f"{self.timestamp}:"
            f"{self.weight_kg:.1f}:"
            f"{self.impedance_high}:"
            f"{self.impedance_low}"
        )
