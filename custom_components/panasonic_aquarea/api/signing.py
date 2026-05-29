"""Comfort Cloud request signing — pure functions, ported from index.js."""
from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime

from .const import FIXED_KEY

_APP_NAME = "Comfort Cloud"


def app_timestamp(epoch_seconds: float | None = None) -> str:
    """Return a 'YYYY-MM-DD HH:MM:SS' timestamp (UTC) used for X-APP-TIMESTAMP."""
    t = epoch_seconds if epoch_seconds is not None else time.time()
    return datetime.fromtimestamp(t, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")


def cfc_key(timestamp: str, token: str) -> str:
    """Compute the X-CFC-API-KEY for a given timestamp string and bearer token.

    SHA-256 over: "Comfort Cloud" + FIXED_KEY + epoch_ms(timestamp) + "Bearer " + token,
    then literal "cfc" inserted at offset 9. The timestamp string is interpreted as UTC,
    matching the X-APP-TIMESTAMP we send alongside it.
    """
    ms = int(
        datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        .replace(tzinfo=UTC)
        .timestamp()
        * 1000
    )
    raw = b"".join(
        [
            _APP_NAME.encode(),
            FIXED_KEY.encode(),
            str(ms).encode(),
            b"Bearer ",
            token.encode(),
        ]
    )
    digest = hashlib.sha256(raw).hexdigest()
    return digest[:9] + "cfc" + digest[9:]
