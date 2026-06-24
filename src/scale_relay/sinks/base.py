"""Sink abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MeasurementSink(ABC):
    """Base interface for sending measurement events."""

    @abstractmethod
    async def send(self, event: dict[str, Any]) -> None:
        """Send one measurement event."""
