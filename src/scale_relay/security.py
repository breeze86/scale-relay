"""Security helpers."""

from __future__ import annotations

import hmac
from hashlib import sha256


def mask_secret(value: str | None, visible: int = 4) -> str:
    """Mask a secret while keeping a short prefix and suffix."""
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}{'*' * (len(value) - visible * 2)}{value[-visible:]}"


def hmac_sha256_hex(secret: str, body: bytes) -> str:
    """Return Hermes Generic Webhook HMAC-SHA256 hex digest."""
    return hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()


def constant_time_equal(left: str, right: str) -> bool:
    """Compare two strings in constant time."""
    return hmac.compare_digest(left, right)
