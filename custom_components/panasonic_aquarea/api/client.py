"""Self-contained async Panasonic Comfort Cloud client (HA-agnostic).

Ported from the verified index.js. Handles OAuth2+PKCE login, token refresh,
CFC request signing, and the Comfort Cloud transfer proxy used to read Aquarea
heat-pump status. No dependency on any community Panasonic library.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import aiohttp

from . import const
from .const import AQUAREA_DEVICE_TYPE
from .models import AquareaDevice
from .signing import app_timestamp, cfc_key

_LOGGER = logging.getLogger(__name__)

_VERSION_RE = re.compile(r'\["(\d+\.\d+\.\d+)"\]')


class AuthError(Exception):
    """Raised when authentication fails (bad credentials / unrecoverable)."""


class ApiError(Exception):
    """Raised on a non-auth API failure."""


class _HiddenInputParser(HTMLParser):
    """Collects <input type=hidden name=.. value=..> pairs from the login response."""

    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        a = dict(attrs)
        if a.get("type") == "hidden" and a.get("name") is not None:
            self.fields[a["name"]] = a.get("value") or ""


class PanasonicCloudClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        *,
        refresh_token: str | None = None,
        on_token_refresh: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._token: str | None = None
        self._refresh_token = refresh_token
        self._client_id: str | None = None
        self._app_version = const.APP_VERSION_FALLBACK
        self._on_token_refresh = on_token_refresh

    def _headers(self, *, client_id: bool = False) -> dict[str, str]:
        ts = app_timestamp()
        headers = {
            "Accept": "application/json; charset=UTF-8",
            "Content-Type": "application/json",
            "User-Agent": "G-RAC",
            "X-APP-NAME": "Comfort Cloud",
            "X-APP-TIMESTAMP": ts,
            "X-APP-TYPE": "1",
            "X-APP-VERSION": self._app_version,
            "X-CFC-API-KEY": cfc_key(ts, self._token or ""),
            "X-User-Authorization-V2": f"Bearer {self._token}",
        }
        if client_id and self._client_id:
            headers["X-Client-Id"] = self._client_id
        return headers

    async def _fetch_app_version(self) -> str:
        try:
            async with self._session.get(const.PLAY_STORE_URL) as resp:
                text = await resp.text()
            match = _VERSION_RE.search(text)
            if match:
                return match.group(1)
        except aiohttp.ClientError as err:
            _LOGGER.debug("App version fetch failed: %s", err)
        return const.APP_VERSION_FALLBACK

    @staticmethod
    def _pkce_pair() -> tuple[str, str]:
        verifier = secrets.token_urlsafe(32)
        digest = hashlib.sha256(verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        return verifier, challenge

    @staticmethod
    def _query_param(location: str, key: str) -> str | None:
        return parse_qs(urlparse(location).query).get(key, [None])[0]

    async def login(self) -> None:
        """Run the full OAuth2 + PKCE login and resolve a client id."""
        self._app_version = await self._fetch_app_version()
        verifier, challenge = self._pkce_pair()
        state = secrets.token_urlsafe(16)

        params = {
            "scope": const.SCOPE,
            "audience": f"https://digital.panasonic.com/{const.CLIENT_ID}/api/v1/",
            "protocol": "oauth2",
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "auth0Client": const.AUTH0_CLIENT,
            "client_id": const.CLIENT_ID,
            "redirect_uri": const.REDIRECT_URI,
            "state": state,
        }
        async with self._session.get(
            f"{const.AUTH_BASE}/authorize", params=params, allow_redirects=False
        ) as resp:
            location = resp.headers["Location"]
        real_state = self._query_param(location, "state") or state

        login_url = location if location.startswith("http") else f"{const.AUTH_BASE}{location}"
        async with self._session.get(login_url, allow_redirects=False) as resp:
            csrf = ""
            for cookie in resp.headers.getall("Set-Cookie", []):
                m = re.search(r"_csrf=([^;]+)", cookie)
                if m:
                    csrf = m.group(1)
                    break

        auth_headers = {"Auth0-Client": const.AUTH0_CLIENT, "User-Agent": "okhttp/4.10.0"}
        async with self._session.post(
            f"{const.AUTH_BASE}/usernamepassword/login",
            json={
                "client_id": const.CLIENT_ID,
                "redirect_uri": const.REDIRECT_URI,
                "tenant": "pdpauthglb-a1",
                "response_type": "code",
                "scope": const.SCOPE,
                "audience": f"https://digital.panasonic.com/{const.CLIENT_ID}/api/v1/",
                "_csrf": csrf,
                "state": real_state,
                "_intstate": "deprecated",
                "username": self._username,
                "password": self._password,
                "lang": "en",
                "connection": "PanasonicID-Authentication",
            },
            headers=auth_headers,
        ) as resp:
            if resp.status not in (200, 302):
                raise AuthError(f"login rejected: HTTP {resp.status}")
            body = await resp.text()
        parser = _HiddenInputParser()
        parser.feed(body)
        if not parser.fields:
            raise AuthError("no callback parameters in login response")

        async with self._session.post(
            f"{const.AUTH_BASE}/login/callback",
            data=parser.fields,
            allow_redirects=False,
        ) as resp:
            callback_location = resp.headers["Location"]
        code = self._query_param(callback_location, "code")
        if not code:
            async with self._session.get(callback_location, allow_redirects=False) as resp:
                code = self._query_param(resp.headers["Location"], "code")
        if not code:
            raise AuthError("no authorization code returned")

        async with self._session.post(
            f"{const.AUTH_BASE}/oauth/token",
            json={
                "scope": "openid",
                "client_id": const.CLIENT_ID,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": const.REDIRECT_URI,
                "code_verifier": verifier,
            },
            headers=auth_headers,
        ) as resp:
            data = await resp.json()
        self._token = data["access_token"]
        self._refresh_token = data.get("refresh_token")
        if self._refresh_token and self._on_token_refresh:
            await self._on_token_refresh(self._refresh_token)

        await self._resolve_client_id()

    async def _resolve_client_id(self) -> None:
        async with self._session.post(
            f"{const.API_BASE}/auth/v2/login",
            json={"language": 0},
            headers=self._headers(),
        ) as resp:
            data = await resp.json()
        self._client_id = data["clientId"]

    async def get_devices(self) -> list[tuple[str, str]]:
        """Return [(guid, name)] for Aquarea (air-to-water) devices on the account."""
        async with self._session.get(
            f"{const.API_BASE}/device/group/", headers=self._headers(client_id=True)
        ) as resp:
            if resp.status != 200:
                raise ApiError(f"device list failed: HTTP {resp.status}")
            data = await resp.json()
        devices: list[tuple[str, str]] = []
        for group in data.get("groupList", []):
            for dev in group.get("deviceList", []):
                if dev.get("deviceType") == AQUAREA_DEVICE_TYPE:
                    devices.append((dev["deviceGuid"], dev.get("deviceName", dev["deviceGuid"])))
        return devices

    async def get_status(self, guid: str, *, direct: bool = False) -> AquareaDevice:
        """Fetch live status for one Aquarea device via the Comfort Cloud transfer proxy."""
        body = {
            "apiName": f"/remote/v1/api/devices?gwid={guid}&deviceDirect={1 if direct else 0}",
            "requestMethod": "GET",
        }
        async with self._session.post(
            f"{const.API_BASE}/remote/v1/app/common/transfer",
            json=body,
            headers=self._headers(client_id=True),
        ) as resp:
            if resp.status != 200:
                raise ApiError(f"status fetch failed: HTTP {resp.status}")
            data = await resp.json()
        return AquareaDevice.from_status(guid, data)

    async def refresh(self) -> bool:
        """Refresh the access token using the stored refresh token. Returns success."""
        if not self._refresh_token:
            return False
        try:
            async with self._session.post(
                f"{const.AUTH_BASE}/oauth/token",
                json={
                    "scope": const.SCOPE,
                    "client_id": const.CLIENT_ID,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Auth0-Client": const.AUTH0_CLIENT, "User-Agent": "okhttp/4.10.0"},
            ) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
        except aiohttp.ClientError:
            return False
        self._token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        if self._on_token_refresh:
            await self._on_token_refresh(self._refresh_token)
        return True
