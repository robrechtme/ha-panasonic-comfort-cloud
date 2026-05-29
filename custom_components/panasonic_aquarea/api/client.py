"""Self-contained async Panasonic Comfort Cloud client (HA-agnostic).

Ported from the verified index.js. Handles OAuth2+PKCE login, token refresh,
CFC request signing, and the Comfort Cloud transfer proxy used to read Aquarea
heat-pump status. No dependency on any community Panasonic library.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable

import aiohttp

from . import const
from .signing import app_timestamp, cfc_key

_LOGGER = logging.getLogger(__name__)

_VERSION_RE = re.compile(r'\["(\d+\.\d+\.\d+)"\]')


class AuthError(Exception):
    """Raised when authentication fails (bad credentials / unrecoverable)."""


class ApiError(Exception):
    """Raised on a non-auth API failure."""


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
