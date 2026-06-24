"""Xiaomi Cloud BLE KEY extraction entrypoints."""

from __future__ import annotations

from scale_relay.xiaomi_cloud.client import XiaomiCloudClient, normalize_regions
from scale_relay.xiaomi_cloud.models import XiaomiScaleCredentials
from scale_relay.xiaomi_cloud.session_store import load_session


def extract_scale_credentials(
    region: str | None = "cn",
    all_regions: bool = False,
    mac: str | None = None,
    did: str | None = None,
) -> XiaomiScaleCredentials:
    client = XiaomiCloudClient(load_session())
    return client.extract_scale_credentials(
        regions=normalize_regions(region, all_regions=all_regions),
        mac=mac,
        did=did,
    )
