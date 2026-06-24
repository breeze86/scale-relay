"""Xiaomi Cloud QR login and device APIs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import random
import socket
import tempfile
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from scale_relay.errors import ScaleRelayError
from scale_relay.xiaomi_cloud.models import (
    SUPPORTED_SERVERS,
    XiaomiDevice,
    XiaomiScaleCredentials,
    XiaomiSession,
)
from scale_relay.xiaomi_cloud.rc4 import rc4_crypt


@dataclass(frozen=True)
class QrLoginInfo:
    login_url: str
    qr_image_url: str
    local_image_url: str | None
    image_file: str | None


class XiaomiCloudClient:
    """Minimal Xiaomi Cloud client for QR login and BLE key extraction."""

    def __init__(self, session: XiaomiSession | None = None, timeout: float = 20.0) -> None:
        self._agent = _generate_agent()
        self._device_id = _generate_device_id()
        self._timeout = timeout
        self._cookies = CookieJar()
        self._opener = build_opener(HTTPCookieProcessor(self._cookies))
        self._ssecurity = session.ssecurity if session else None
        self.user_id = session.user_id if session else None
        self._service_token = session.service_token if session else None
        self._qr_login_url: str | None = None
        self._qr_long_polling_url: str | None = None
        self._qr_timeout = 180
        self._location: str | None = None

    def begin_qr_login(self, host: str = "127.0.0.1", image_port: int = 31415) -> QrLoginInfo:
        url = "https://account.xiaomi.com/longPolling/loginUrl"
        data = {
            "_qrsize": "480",
            "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
            "callback": "https://sts.api.io.mi.com/sts",
            "_hasLogo": "false",
            "sid": "xiaomiio",
            "serviceParam": "",
            "_locale": "en_GB",
            "_dc": str(int(time.time() * 1000)),
        }
        response = self._get_json(url, data)
        qr_image_url = str(response["qr"])
        self._qr_login_url = str(response["loginUrl"])
        self._qr_long_polling_url = str(response["lp"])
        self._qr_timeout = int(response.get("timeout", 180))

        image = self._request_bytes(qr_image_url)
        local_image_url: str | None = None
        image_file: str | None = None
        try:
            _start_image_server(image, image_port)
            local_image_url = f"http://{host}:{image_port}"
        except OSError:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                tmp.write(image)
                image_file = tmp.name

        return QrLoginInfo(
            login_url=self._qr_login_url,
            qr_image_url=qr_image_url,
            local_image_url=local_image_url,
            image_file=image_file,
        )

    def finish_qr_login(self) -> XiaomiSession:
        if not self._qr_long_polling_url:
            raise ScaleRelayError("QR login has not been started")

        start = time.time()
        last_error: Exception | None = None
        while time.time() - start <= self._qr_timeout:
            try:
                response = self._request_text(self._qr_long_polling_url, timeout=10)
            except TimeoutError as exc:
                last_error = exc
                continue
            data = _to_json(response)
            self.user_id = str(data["userId"])
            self._ssecurity = str(data["ssecurity"])
            self._location = str(data["location"])
            return self._fetch_service_token()

        raise ScaleRelayError(f"QR login timed out: {last_error}")

    def list_devices(self, regions: list[str]) -> list[XiaomiDevice]:
        devices: list[XiaomiDevice] = []
        for region in regions:
            for home in self._list_homes(region):
                response = self.get_devices(region, home["home_id"], home["home_owner"])
                device_info = ((response or {}).get("result") or {}).get("device_info") or []
                for raw_device in device_info:
                    if not isinstance(raw_device, dict) or "did" not in raw_device:
                        continue
                    devices.append(
                        XiaomiDevice(
                            name=raw_device.get("name"),
                            did=str(raw_device["did"]),
                            mac=raw_device.get("mac"),
                            model=raw_device.get("model"),
                            region=region,
                            raw=raw_device,
                        )
                    )
        return devices

    def extract_scale_credentials(
        self,
        regions: list[str],
        mac: str | None = None,
        did: str | None = None,
    ) -> XiaomiScaleCredentials:
        devices = self.list_devices(regions)
        candidates = [
            device
            for device in devices
            if (did and device.did == did)
            or (mac and device.mac and device.mac.upper() == mac.upper())
            or (not did and not mac and device.is_s400)
        ]
        if not candidates:
            raise ScaleRelayError("No Xiaomi S400 device matched the requested filters")
        if len(candidates) > 1 and not (mac or did):
            names = ", ".join(f"{d.name or d.did}({d.region})" for d in candidates)
            raise ScaleRelayError(f"Multiple S400 devices found, specify --mac or --did: {names}")

        device = candidates[0]
        beacon = self.get_beaconkey(device.region, device.did)
        ble_key = (((beacon or {}).get("result") or {}).get("beaconkey")) or ""
        if not ble_key:
            raise ScaleRelayError(f"Unable to fetch BLE KEY for device {device.did}")
        if not device.mac:
            raise ScaleRelayError(f"Device {device.did} does not include a MAC address")
        return XiaomiScaleCredentials(
            name=device.name,
            model=device.model,
            did=device.did,
            mac=device.mac,
            ble_key=str(ble_key),
            region=device.region,
        )

    def get_homes(self, region: str) -> dict[str, Any] | None:
        url = self._api_url(region) + "/v2/homeroom/gethome"
        return self._execute_api_call_encrypted(
            url,
            {"data": '{"fg": true, "fetch_share": true, "fetch_share_dev": true, "limit": 300, "app_ver": 7}'},
        )

    def get_devices(self, region: str, home_id: str | int, owner_id: str | int) -> dict[str, Any] | None:
        url = self._api_url(region) + "/v2/home/home_device_list"
        data = (
            '{"home_owner": '
            + str(owner_id)
            + ',"home_id": '
            + str(home_id)
            + ', "limit": 200, "get_split_device": true, "support_smart_home": true}'
        )
        return self._execute_api_call_encrypted(url, {"data": data})

    def get_dev_cnt(self, region: str) -> dict[str, Any] | None:
        url = self._api_url(region) + "/v2/user/get_device_cnt"
        return self._execute_api_call_encrypted(url, {"data": '{ "fetch_own": true, "fetch_share": true}'})

    def get_beaconkey(self, region: str, did: str) -> dict[str, Any] | None:
        url = self._api_url(region) + "/v2/device/blt_get_beaconkey"
        return self._execute_api_call_encrypted(url, {"data": '{"did":"' + did + '","pdid":1}'})

    def _list_homes(self, region: str) -> list[dict[str, str | int]]:
        homes: list[dict[str, str | int]] = []
        homes_response = self.get_homes(region)
        for home in (((homes_response or {}).get("result") or {}).get("homelist") or []):
            homes.append({"home_id": home["id"], "home_owner": self.user_id or ""})

        cnt_response = self.get_dev_cnt(region)
        shared = ((((cnt_response or {}).get("result") or {}).get("share") or {}).get("share_family")) or []
        for home in shared:
            homes.append({"home_id": home["home_id"], "home_owner": home["home_owner"]})

        deduped: dict[tuple[str, str], dict[str, str | int]] = {}
        for home in homes:
            deduped[(str(home["home_id"]), str(home["home_owner"]))] = home
        return list(deduped.values())

    def _fetch_service_token(self) -> XiaomiSession:
        if not self._location:
            raise ScaleRelayError("Xiaomi QR login did not return a token location")
        response = self._request(self._location, headers={"content-type": "application/x-www-form-urlencoded"})
        token = _cookie_value(response.headers.get_all("Set-Cookie", []), "serviceToken")
        if not token:
            raise ScaleRelayError("Xiaomi serviceToken was not returned")
        self._service_token = token
        return XiaomiSession(
            user_id=str(self.user_id),
            ssecurity=str(self._ssecurity),
            service_token=token,
        )

    def _execute_api_call_encrypted(
        self,
        url: str,
        params: dict[str, str],
    ) -> dict[str, Any] | None:
        if not self._ssecurity or not self._service_token or not self.user_id:
            raise ScaleRelayError("Xiaomi Cloud session is incomplete")

        headers = {
            "Accept-Encoding": "identity",
            "User-Agent": self._agent,
            "Content-Type": "application/x-www-form-urlencoded",
            "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2",
            "MIOT-ENCRYPT-ALGORITHM": "ENCRYPT-RC4",
            "Cookie": (
                f"userId={self.user_id}; "
                f"yetAnotherServiceToken={self._service_token}; "
                f"serviceToken={self._service_token}; "
                "locale=en_GB; timezone=GMT+02:00; is_daylight=1; "
                "dst_offset=3600000; channel=MI_APP_STORE"
            ),
        }
        millis = round(time.time() * 1000)
        nonce = _generate_nonce(millis)
        signed_nonce = self._signed_nonce(nonce)
        fields = _generate_enc_params(url, "POST", signed_nonce, nonce, dict(params), self._ssecurity)
        full_url = f"{url}?{urlencode(fields)}"
        response = self._request_text(full_url, method="POST", headers=headers)
        decoded = _decrypt_rc4(self._signed_nonce(fields["_nonce"]), response)
        return json.loads(decoded)

    def _signed_nonce(self, nonce: str) -> str:
        digest = hashlib.sha256(base64.b64decode(str(self._ssecurity)) + base64.b64decode(nonce))
        return base64.b64encode(digest.digest()).decode("utf-8")

    @staticmethod
    def _api_url(region: str) -> str:
        if region not in SUPPORTED_SERVERS:
            raise ScaleRelayError(f"Unsupported Xiaomi region: {region}")
        return "https://" + ("" if region == "cn" else f"{region}.") + "api.io.mi.com/app"

    def _get_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        return _to_json(self._request_text(f"{url}?{urlencode(params)}"))

    def _request_bytes(self, url: str) -> bytes:
        with self._request(url) as response:
            return response.read()

    def _request_text(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        with self._request(url, method=method, headers=headers, timeout=timeout) as response:
            return response.read().decode("utf-8")

    def _request(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        request = Request(url, headers=headers or {"User-Agent": self._agent}, method=method)
        try:
            return self._opener.open(request, timeout=timeout or self._timeout)
        except HTTPError as exc:
            raise ScaleRelayError(f"Xiaomi Cloud HTTP error {exc.code}: {url}") from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError(str(exc.reason)) from exc
            raise ScaleRelayError(f"Xiaomi Cloud request failed: {exc.reason}") from exc


def normalize_regions(region: str | None, all_regions: bool = False) -> list[str]:
    if all_regions or not region:
        return list(SUPPORTED_SERVERS)
    if region not in SUPPORTED_SERVERS:
        raise ScaleRelayError(f"Unsupported Xiaomi region: {region}")
    return [region]


def _to_json(response_text: str) -> dict[str, Any]:
    return json.loads(response_text.replace("&&&START&&&", ""))


def _generate_agent() -> str:
    agent_id = "".join(chr(random.randint(65, 69)) for _ in range(13))
    random_text = "".join(chr(random.randint(97, 122)) for _ in range(18))
    return f"{random_text}-{agent_id} APP/com.xiaomi.mihome APPV/10.5.201"


def _generate_device_id() -> str:
    return "".join(chr(random.randint(97, 122)) for _ in range(6))


def _generate_nonce(millis: int) -> str:
    nonce_bytes = os.urandom(8) + (int(millis / 60000)).to_bytes(4, byteorder="big")
    return base64.b64encode(nonce_bytes).decode()


def _generate_enc_signature(
    url: str,
    method: str,
    signed_nonce: str,
    params: dict[str, str],
) -> str:
    signature_params = [str(method).upper(), url.split("com")[1].replace("/app/", "/")]
    for key, value in params.items():
        signature_params.append(f"{key}={value}")
    signature_params.append(signed_nonce)
    signature_string = "&".join(signature_params)
    return base64.b64encode(hashlib.sha1(signature_string.encode("utf-8")).digest()).decode()


def _generate_enc_params(
    url: str,
    method: str,
    signed_nonce: str,
    nonce: str,
    params: dict[str, str],
    ssecurity: str,
) -> dict[str, str]:
    params["rc4_hash__"] = _generate_enc_signature(url, method, signed_nonce, params)
    for key, value in list(params.items()):
        params[key] = _encrypt_rc4(signed_nonce, value)
    params.update(
        {
            "signature": _generate_enc_signature(url, method, signed_nonce, params),
            "ssecurity": ssecurity,
            "_nonce": nonce,
        }
    )
    return params


def _encrypt_rc4(password: str, payload: str) -> str:
    encrypted = rc4_crypt(base64.b64decode(password), payload.encode("utf-8"))
    return base64.b64encode(encrypted).decode()


def _decrypt_rc4(password: str, payload: str) -> bytes:
    return rc4_crypt(base64.b64decode(password), base64.b64decode(payload))


def _cookie_value(set_cookie_headers: list[str], name: str) -> str | None:
    prefix = f"{name}="
    for header in set_cookie_headers:
        for part in header.split(";"):
            stripped = part.strip()
            if stripped.startswith(prefix):
                return stripped[len(prefix) :]
    return None


def _start_image_server(image: bytes, port: int) -> None:
    class ImageHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            self.wfile.write(image)

        def log_message(self, _format: str, *args: Any) -> None:
            return

    server = HTTPServer(("", port), ImageHandler)
    # Touch server address early so bind errors surface before the thread starts.
    socket.gethostname()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
