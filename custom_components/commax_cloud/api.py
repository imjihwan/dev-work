"""Async COMMAX API; independent of Home Assistant for protocol testing."""

from __future__ import annotations

import asyncio
import json
import ssl
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

import aiohttp
from yarl import URL

from .const import (
    AUTH_SERVER,
    CLIENT_ID,
    CLIENT_SECRET,
    COMMAND_SPACING,
    DEFAULT_TOKEN_LIFETIME,
    REFRESH_MARGIN,
    REQUEST_TIMEOUT,
)

_ANDROID_SAFE = "_-!.~'()*"


class CommaxError(Exception):
    """A sanitized COMMAX protocol error."""


class CommaxAuthError(CommaxError):
    """Credentials or tokens have been rejected."""


class CommaxConnectionError(CommaxError):
    """Temporary transport/server failure."""


class CommaxApiError(CommaxError):
    """An invalid response or non-authentication API error."""


def _query(items: list[tuple[str, str]]) -> str:
    return "&".join(
        quote(key, safe=_ANDROID_SAFE) + "=" + quote(str(value), safe=_ANDROID_SAFE)
        for key, value in items
    )


def _server_url(value: Any) -> str:
    if not isinstance(value, dict) or not value.get("ip"):
        raise CommaxApiError("Missing service address")
    host = str(value["ip"])
    if any(char in host for char in "/?#@ "):
        raise CommaxApiError("Invalid service host")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = ""
    if "port" in value:
        try:
            number = int(value["port"])
        except (ValueError, TypeError):
            raise CommaxApiError("Invalid service port") from None
        if not 0 < number < 65536:
            raise CommaxApiError("Invalid service port")
        port = f":{number}"
    scheme = "https" if str(value.get("ssl", "")).upper() == "Y" else "http"
    return f"{scheme}://{host}{port}"


@dataclass(frozen=True)
class LightChannel:
    """One discovered binary light channel. Raw command fields stay private."""

    gateway_no: str = field(repr=False)
    root_uuid: str = field(repr=False)
    sub_uuid: str = field(repr=False)
    name: str
    model: str
    state: bool | None
    root: dict[str, Any] = field(repr=False, compare=False)
    sub: dict[str, Any] = field(repr=False, compare=False)

    @property
    def unique_id(self) -> str:
        return f"{self.gateway_no}_{self.root_uuid}_{self.sub_uuid}"

    def command(self, on: bool) -> dict[str, Any]:
        """Reproduce RootDeviceData.setJson and SubDeviceData.setJson."""
        sub = {key: self.sub[key] for key in ("subUuid", "type", "sort")}
        for key in ("option1", "option2", "precision"):
            value = self.sub.get(key)
            if value is not None and str(value) not in {"", "-1"}:
                sub[key] = value
        sub.update(funcCommand="set", value="on" if on else "off")
        obj = {
            "rootUuid": self.root_uuid,
            "rootDevice": self.root["rootDevice"],
            "nickname": self.root.get("nickname", ""),
            "subDevice": [sub],
        }
        return {
            "commands": {
                "cgpCommand": [
                    {"gatewayNo": self.gateway_no, "cgp": {"command": "set", "object": obj}}
                ]
            }
        }


def parse_lights(gateway: Mapping[str, Any], response: Any) -> dict[str, LightChannel]:
    """Use the verified gateway.devices.object structure, not arbitrary recursion."""
    try:
        roots = response["gateway"]["devices"]["object"]
        gateway_no = str(gateway["gatewayNo"])
    except (KeyError, TypeError):
        raise CommaxApiError("Unrecognized device response") from None
    if not isinstance(roots, list):
        raise CommaxApiError("Invalid device array")
    result: dict[str, LightChannel] = {}
    for root in roots:
        if not isinstance(root, dict) or root.get("commaxDevice") != "light":
            continue
        if not root.get("rootUuid") or root.get("rootDevice") != "switch":
            continue  # Dimmer control requires a separate implementation.
        subs = root.get("subDevice")
        if not isinstance(subs, list):
            raise CommaxApiError("Invalid light channels")
        channels = [
            sub
            for sub in subs
            if isinstance(sub, dict)
            and sub.get("sort") in {"switchBinary", "switchBinary_01", "switchBinary_02"}
            and sub.get("subUuid")
            and sub.get("type") == "readWrite"
        ]
        for sub in channels:
            name = str(root.get("nickname") or "COMMAX Light")
            if len(channels) > 1:
                name += " " + str(sub["sort"])
            value = str(sub.get("value", "")).lower()
            channel = LightChannel(
                gateway_no=gateway_no,
                root_uuid=str(root["rootUuid"]),
                sub_uuid=str(sub["subUuid"]),
                name=name,
                model=str(gateway.get("model") or "COMMAX Wallpad"),
                state=True if value == "on" else False if value == "off" else None,
                root=deepcopy(root),
                sub=deepcopy(sub),
            )
            if channel.unique_id in result:
                raise CommaxApiError("Duplicate light identifier")
            result[channel.unique_id] = channel
    return result


class CommaxApi:
    """Serialize requests, persist token rotation and recover expired refresh tokens."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        device_uuid: str,
        *,
        tokens: Mapping[str, Any] | None = None,
        on_tokens: Callable[[dict[str, Any]], None] | None = None,
        auth_server: str = AUTH_SERVER,
        clock: Callable[[], float] = time.time,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._device_uuid = device_uuid
        self._tokens = dict(tokens or {})
        self._on_tokens = on_tokens
        self._auth_server = auth_server.rstrip("/")
        self._ssl_context = ssl_context
        self._clock = clock
        self._lock = asyncio.Lock()
        self._last_command = 0.0
        self._auth_failed = False

    @property
    def user_no(self) -> str | None:
        return self._tokens.get("user_no")

    @property
    def token_data(self) -> dict[str, Any]:
        return dict(self._tokens)

    @property
    def expires_at(self) -> float:
        return float(self._tokens.get("expires_at", 0))

    def _app_headers(self) -> dict[str, str]:
        return {
            "cmx-dvc-os": "AND",
            "cmx-dvc-uuid": self._device_uuid,
            "cmx-app-version": "0.0.0.1",
        }

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
        auth_endpoint: bool = False,
    ) -> dict[str, Any]:
        parsed = urlsplit(url)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username:
            raise CommaxApiError("Invalid request address")
        try:
            async with self._session.request(
                method,
                URL(url, encoded=True),
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                allow_redirects=False,
                ssl=self._ssl_context or True,
            ) as response:
                status = response.status
                # Never include URLs, exception text or response bodies in errors/logs.
                if status == 401 or (auth_endpoint and status in {400, 403}):
                    raise CommaxAuthError("Authentication rejected")
                if status == 429 or status >= 500:
                    raise CommaxConnectionError(f"Service temporarily unavailable (HTTP {status})")
                if status >= 300:
                    raise CommaxApiError(f"Request rejected (HTTP {status})")
                raw = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise CommaxApiError("Service response exceeds size limit")
                try:
                    data = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise CommaxApiError("Service returned invalid JSON") from None
        except (aiohttp.ClientError, TimeoutError, OSError):
            raise CommaxConnectionError("Unable to reach COMMAX") from None
        if not isinstance(data, dict):
            raise CommaxApiError("Service returned an invalid object")
        if data.get("error"):
            if auth_endpoint:
                raise CommaxAuthError("Authentication rejected")
            raise CommaxApiError("Command rejected by service")
        return data

    def _adopt(self, response: dict[str, Any]) -> None:
        if not response.get("access_token"):
            raise CommaxApiError("Missing access token")
        updated = dict(self._tokens)
        for key in ("access_token", "refresh_token", "token_type"):
            if response.get(key):
                updated[key] = str(response[key])
        if not updated.get("token_type") or not updated.get("refresh_token"):
            raise CommaxApiError("Incomplete authentication response")
        servers = response.get("server", {})
        if not isinstance(servers, dict):
            raise CommaxApiError("Invalid service metadata")
        if "iot" in servers:
            updated["iot_server"] = _server_url(servers["iot"])
        if not updated.get("iot_server"):
            raise CommaxApiError("Missing IoT service address")
        user = response.get("user", {})
        if isinstance(user, dict) and user.get("userNo"):
            user_no = str(user["userNo"])
            if self.user_no and self.user_no != user_no:
                self._auth_failed = True
                raise CommaxAuthError("Account identity changed; reauthentication required")
            updated["user_no"] = user_no
        if not updated.get("user_no"):
            raise CommaxApiError("Missing account identifier")
        try:
            lifetime = float(
                response.get(
                    "expire_in",
                    response.get("expires_in", updated.get("expires_in", DEFAULT_TOKEN_LIFETIME)),
                )
            )
        except (ValueError, TypeError):
            raise CommaxApiError("Invalid token lifetime") from None
        if not 0 < lifetime < 10 * 365 * 86400:
            raise CommaxApiError("Invalid token lifetime")
        updated["expires_in"] = lifetime
        updated["expires_at"] = self._clock() + lifetime
        self._tokens = updated
        if self._on_tokens:
            self._on_tokens(dict(updated))

    async def _login(self) -> None:
        query = _query(
            [
                ("client_id", CLIENT_ID),
                ("client_secret", CLIENT_SECRET),
                ("grant_type", "password"),
                ("username", self._username),
                ("password", quote(self._password, safe=_ANDROID_SAFE)),
            ]
        )
        try:
            response = await self._request(
                "GET",
                self._auth_server + "/oauth/authorize?" + query,
                headers=self._app_headers(),
                auth_endpoint=True,
            )
        except CommaxAuthError:
            self._auth_failed = True
            raise
        self._adopt(response)
        self._auth_failed = False

    async def async_login(self) -> None:
        async with self._lock:
            await self._login()

    async def _renew(self) -> None:
        """Refresh first; only rejected refresh credentials trigger password login."""
        refresh_token = self._tokens.get("refresh_token")
        if refresh_token:
            query = _query(
                [
                    ("client_id", CLIENT_ID),
                    ("client_secret", CLIENT_SECRET),
                    ("grant_type", "refresh_token"),
                    ("refresh_token", refresh_token),
                ]
            )
            try:
                response = await self._request(
                    "GET",
                    self._auth_server + "/oauth/token?" + query,
                    headers=self._app_headers(),
                    auth_endpoint=True,
                )
            except CommaxAuthError:
                pass
            else:
                self._adopt(response)
                return
        await self._login()

    async def _ensure_token(self, *, force: bool = False) -> None:
        if self._auth_failed:
            raise CommaxAuthError("Reauthentication required")
        margin = min(
            REFRESH_MARGIN, float(self._tokens.get("expires_in", DEFAULT_TOKEN_LIFETIME)) / 10
        )
        if (
            force
            or not self._tokens.get("access_token")
            or self._clock() >= self.expires_at - margin
        ):
            await self._renew()

    async def async_ensure_token(self) -> None:
        async with self._lock:
            await self._ensure_token()

    async def _authorized(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        # Caller owns _lock. Network failures never replay a command automatically.
        await self._ensure_token()
        for attempt in range(2):
            headers = {
                "Content-Type": "application/json",
                "Authorization": self._tokens["token_type"] + " " + self._tokens["access_token"],
            }
            try:
                return await self._request(
                    method, self._tokens["iot_server"] + path, headers=headers, payload=payload
                )
            except CommaxAuthError:
                if attempt:
                    self._auth_failed = True
                    raise
                await self._ensure_token(force=True)
        raise CommaxAuthError("Authentication rejected")

    async def async_lights(self) -> dict[str, LightChannel]:
        async with self._lock:
            response = await self._authorized("GET", "/v1/gateways")
            try:
                gateways = response["gateways"]["gateway"]
            except (KeyError, TypeError):
                raise CommaxApiError("Invalid gateway response") from None
            if not isinstance(gateways, list):
                raise CommaxApiError("Invalid gateway array")
            lights: dict[str, LightChannel] = {}
            for gateway in gateways:
                if not isinstance(gateway, dict) or not gateway.get("gatewayNo"):
                    raise CommaxApiError("Invalid gateway record")
                detail = await self._authorized(
                    "GET", "/v1/gateways/" + quote(str(gateway["gatewayNo"]), safe="")
                )
                lights.update(parse_lights(gateway, detail))
            return lights

    async def async_set_light(self, channel: LightChannel, on: bool) -> None:
        async with self._lock:
            delay = COMMAND_SPACING - (time.monotonic() - self._last_command)
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                response = await self._authorized("POST", "/v1/command", channel.command(on))
                ids = response.get("commands", {}).get("cgpCommand")
                if not isinstance(ids, list) or not ids:
                    raise CommaxApiError("Missing command acknowledgement")
            finally:
                self._last_command = time.monotonic()
