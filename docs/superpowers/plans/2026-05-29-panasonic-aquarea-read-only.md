# Panasonic Aquarea (read-only) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working, read-only Home Assistant integration (`panasonic_aquarea`) that signs into Panasonic Comfort Cloud and exposes a Panasonic Aquarea heat pump's status as HA sensors/binary_sensors.

**Architecture:** A HA-agnostic async Python client (`api/`) ported from our verified `index.js` handles OAuth2+PKCE auth, CFC request signing, and the Comfort Cloud `transfer` proxy. A `DataUpdateCoordinator` polls it every 5 min (`deviceDirect=0`) and feeds entity platforms. No runtime dependency on any community Panasonic library — stdlib + HA's bundled `aiohttp` only.

**Tech Stack:** Python 3.13, Home Assistant custom integration, `aiohttp` (HA-provided), stdlib (`hashlib`, `secrets`, `base64`, `html.parser`, `datetime`); dev: `pytest`, `aioresponses`, `pytest-homeassistant-custom-component`, `ruff`.

**Companion docs:** Spec at `docs/superpowers/specs/2026-05-29-panasonic-aquarea-ha-integration-design.md`. API facts and the proven request shapes in `NOTES.md`. Control is a separate follow-on plan.

---

## File Structure

```
panasonic-cc/
├── custom_components/panasonic_aquarea/
│   ├── __init__.py          # entry setup/unload, build client, start coordinator
│   ├── manifest.json        # domain metadata; requirements: []
│   ├── const.py             # DOMAIN, endpoints, scopes, client ids, app-version fallback
│   ├── config_flow.py       # one entry per account; validates by logging in
│   ├── coordinator.py       # DataUpdateCoordinator; deviceDirect=0; token persistence
│   ├── entity.py            # base entity: coordinator wiring + device_info
│   ├── sensor.py            # outdoor temp, water pressure, pump duty, op mode, per-zone temp, tank temp
│   ├── binary_sensor.py     # defrost active, fault
│   ├── api/
│   │   ├── __init__.py
│   │   ├── const.py         # client-only constants (URLs, headers, FIXED_KEY)
│   │   ├── signing.py       # CFC key + timestamp (pure functions)
│   │   ├── client.py        # PanasonicCloudClient (login, refresh, get_devices, get_status)
│   │   └── models.py        # AquareaDevice / Zone / Tank dataclasses + parsing + enums
│   └── translations/en.json
├── tests/
│   ├── conftest.py
│   ├── fixtures/aquarea_status.json   # real captured payload (golden fixture)
│   ├── api/test_signing.py
│   ├── api/test_models.py
│   ├── api/test_client.py
│   └── test_config_flow.py
├── pyproject.toml
├── hacs.json
├── .tool-versions
└── NOTES.md
```

Each `api/` file is HA-free and unit-testable in isolation. HA glue (`config_flow`, `coordinator`, `entity`, platforms) imports from `api/` but never the reverse.

---

## Phase A — Scaffold

### Task 1: Repo cleanup and tooling

**Files:**
- Delete: `index.js`, `package.json`, `pnpm-lock.yaml`
- Create: `.tool-versions`, `pyproject.toml`, `hacs.json`
- Modify: `.gitignore`

- [ ] **Step 1: Remove the Node diagnostic and its artifacts**

```bash
rm -f index.js package.json pnpm-lock.yaml
rm -rf node_modules .cache.json
```

- [ ] **Step 2: Replace `.gitignore` with Python-appropriate ignores**

```gitignore
# Python
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
*.egg-info/

# Secrets / local
.env
.env.local

# HA test artifacts
.storage/
```

- [ ] **Step 3: Create `.tool-versions`**

```
python 3.13
```

- [ ] **Step 4: Create `pyproject.toml`**

```toml
[project]
name = "panasonic-aquarea"
version = "0.1.0"
description = "Home Assistant integration for Panasonic Aquarea heat pumps via Comfort Cloud"
requires-python = ">=3.13"

[tool.ruff]
target-version = "py313"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "aioresponses>=0.7",
    "pytest-homeassistant-custom-component>=0.13",
    "ruff>=0.6",
]
```

- [ ] **Step 5: Create `hacs.json`**

```json
{
  "name": "Panasonic Aquarea",
  "render_readme": true,
  "homeassistant": "2024.1.0"
}
```

- [ ] **Step 6: Create the dev environment and verify tooling**

Run:
```bash
mise install
python -m venv .venv && . .venv/bin/activate
pip install -U pip
pip install pytest pytest-asyncio aioresponses pytest-homeassistant-custom-component ruff
ruff --version && pytest --version
```
Expected: both print versions without error.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: scaffold python integration, remove node diagnostic"
```

### Task 2: Integration manifest and constants

**Files:**
- Create: `custom_components/panasonic_aquarea/__init__.py` (empty package marker for now — real content in Task 11)
- Create: `custom_components/panasonic_aquarea/manifest.json`
- Create: `custom_components/panasonic_aquarea/const.py`
- Create: `custom_components/panasonic_aquarea/api/__init__.py` (empty)
- Create: `custom_components/panasonic_aquarea/api/const.py`

- [ ] **Step 1: Create `manifest.json`**

```json
{
  "domain": "panasonic_aquarea",
  "name": "Panasonic Aquarea",
  "version": "0.1.0",
  "documentation": "https://github.com/robrechtme/panasonic-aquarea",
  "issue_tracker": "https://github.com/robrechtme/panasonic-aquarea/issues",
  "codeowners": ["@robrechtme"],
  "config_flow": true,
  "iot_class": "cloud_polling",
  "integration_type": "hub",
  "requirements": []
}
```

- [ ] **Step 2: Create `api/const.py`** (client-only constants, ported from `index.js` + `OAuthClient.ts`)

```python
"""Constants for the Panasonic Comfort Cloud client (HA-agnostic)."""

# Auth (Auth0 / Panasonic ID)
AUTH_BASE = "https://authglb.digital.panasonic.com"
CLIENT_ID = "Xmy6xIYIitMxngjB2rHvlm6HSDNnaMJx"
AUTH0_CLIENT = (
    "eyJuYW1lIjoiQXV0aDAuQW5kcm9pZCIsImVudiI6eyJhbmRyb2lkIjoiMzAifSwidmVyc2lvbiI6IjIuOS4zIn0="
)
REDIRECT_URI = (
    "panasonic-iot-cfc://authglb.digital.panasonic.com/android/com.panasonic.ACCsmart/callback"
)
SCOPE = "openid offline_access comfortcloud.control a2w.control"

# Comfort Cloud API
API_BASE = "https://accsmart.panasonic.com"
FIXED_KEY = "521325fb2dd486bf4831b47644317fca"
APP_VERSION_FALLBACK = "4.3.0"
PLAY_STORE_URL = (
    "https://play.google.com/store/apps/details?id=com.panasonic.ACCsmart&hl=en"
)

AQUAREA_DEVICE_TYPE = "2"  # deviceType for air-to-water (Aquarea) units
```

- [ ] **Step 3: Create `const.py`** (HA-side constants)

```python
"""Constants for the Panasonic Aquarea integration."""
from datetime import timedelta

DOMAIN = "panasonic_aquarea"
DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_REFRESH_TOKEN = "refresh_token"
```

- [ ] **Step 4: Commit**

```bash
git add custom_components
git commit -m "feat: add manifest and constants"
```

---

## Phase B — Client read path (TDD)

### Task 3: CFC request signing

**Files:**
- Create: `custom_components/panasonic_aquarea/api/signing.py`
- Test: `tests/api/test_signing.py`, `tests/conftest.py`

- [ ] **Step 1: Write the failing test**

`tests/api/test_signing.py`:
```python
from custom_components.panasonic_aquarea.api.signing import cfc_key, app_timestamp


def test_app_timestamp_format():
    ts = app_timestamp(epoch_seconds=1717000000)  # fixed instant
    # "YYYY-MM-DD HH:MM:SS", 19 chars, space separator
    assert len(ts) == 19
    assert ts[4] == "-" and ts[7] == "-" and ts[10] == " " and ts[13] == ":"


def test_cfc_key_is_deterministic_and_inserts_cfc():
    # Known vector: timestamp interpreted as UTC, token "TKN"
    key = cfc_key("2024-05-29 12:00:00", "TKN")
    assert key[9:12] == "cfc"
    assert len(key) == 64 + 3  # sha256 hex (64) + inserted "cfc"
    # deterministic
    assert key == cfc_key("2024-05-29 12:00:00", "TKN")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_signing.py -v`
Expected: FAIL — `ModuleNotFoundError` / cannot import `signing`.

- [ ] **Step 3: Write minimal implementation**

`custom_components/panasonic_aquarea/api/signing.py`:
```python
"""Comfort Cloud request signing — pure functions, ported from index.js."""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone

from .const import FIXED_KEY

_APP_NAME = "Comfort Cloud"


def app_timestamp(epoch_seconds: float | None = None) -> str:
    """Return a 'YYYY-MM-DD HH:MM:SS' timestamp (UTC) used for X-APP-TIMESTAMP."""
    t = epoch_seconds if epoch_seconds is not None else time.time()
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def cfc_key(timestamp: str, token: str) -> str:
    """Compute the X-CFC-API-KEY for a given timestamp string and bearer token.

    SHA-256 over: "Comfort Cloud" + FIXED_KEY + epoch_ms(timestamp) + "Bearer " + token,
    then literal "cfc" inserted at offset 9. The timestamp string is interpreted as UTC,
    matching the X-APP-TIMESTAMP we send alongside it.
    """
    ms = int(
        datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
        .replace(tzinfo=timezone.utc)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_signing.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Create `tests/conftest.py`** (shared fixtures path helper)

```python
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def aquarea_status() -> dict:
    return json.loads((FIXTURES / "aquarea_status.json").read_text())
```

- [ ] **Step 6: Commit**

```bash
git add custom_components/panasonic_aquarea/api/signing.py tests/api/test_signing.py tests/conftest.py
git commit -m "feat: add cfc request signing"
```

### Task 4: Status models and parsing

**Files:**
- Create: `custom_components/panasonic_aquarea/api/models.py`
- Create: `tests/fixtures/aquarea_status.json`
- Test: `tests/api/test_models.py`

- [ ] **Step 1: Create the golden fixture** `tests/fixtures/aquarea_status.json` (the real captured payload)

```json
{
  "operation": "FFFFFFFF",
  "ownerFlg": false,
  "a2wName": "Warmtepomp",
  "status": {
    "serviceType": "STD_ADP-TAW1",
    "operationMode": 2,
    "direction": 1,
    "quietMode": 0,
    "powerful": 0,
    "forceDHW": 0,
    "forceHeater": 0,
    "tank": 1,
    "pumpDuty": 0,
    "waterPressure": 1.32,
    "deiceStatus": 0,
    "specialStatus": 0,
    "outdoorNow": 31,
    "holidayTimer": 0,
    "modelSeriesSelection": 4,
    "zoneStatus": [
      {"zoneId": 1, "zoneName": "Boven", "zoneType": 0, "zoneSensor": 0,
       "operationStatus": 0, "temperatureNow": 14,
       "heatMin": -5, "heatMax": 5, "coolMin": -5, "coolMax": 5,
       "heatSet": -5, "coolSet": 0},
      {"zoneId": 2, "zoneName": "Beneden", "zoneType": 0, "zoneSensor": 2,
       "operationStatus": 1, "temperatureNow": 24,
       "heatMin": 10, "heatMax": 30, "coolMin": 18, "coolMax": 35,
       "heatSet": 20, "coolSet": 22}
    ],
    "tankStatus": {"operationStatus": 1, "temperatureNow": 46, "heatMin": 40, "heatMax": 65, "heatSet": 52}
  }
}
```

- [ ] **Step 2: Write the failing test** `tests/api/test_models.py`

```python
from custom_components.panasonic_aquarea.api.models import AquareaDevice, OperationMode, ZoneMode


def test_parses_top_level(aquarea_status):
    dev = AquareaDevice.from_status("B218954411", aquarea_status)
    assert dev.guid == "B218954411"
    assert dev.name == "Warmtepomp"
    assert dev.service_type == "STD_ADP-TAW1"
    assert dev.operation_mode is OperationMode.COOL
    assert dev.outdoor_temperature == 31
    assert dev.water_pressure == 1.32
    assert dev.pump_duty == 0
    assert dev.defrost is False
    assert dev.fault is False
    assert dev.force_dhw is False


def test_parses_zones_with_mode_detection(aquarea_status):
    dev = AquareaDevice.from_status("B218954411", aquarea_status)
    boven = dev.zones[0]
    beneden = dev.zones[1]
    # Beneden: absolute room temp (range 10-30) -> ABSOLUTE
    assert beneden.name == "Beneden"
    assert beneden.mode is ZoneMode.ABSOLUTE
    assert beneden.on is True
    assert beneden.current_temperature == 24
    assert beneden.heat_setpoint == 20
    assert beneden.heat_min == 10 and beneden.heat_max == 30
    # Boven: compensation offset (range -5..5) -> OFFSET
    assert boven.name == "Boven"
    assert boven.mode is ZoneMode.OFFSET
    assert boven.on is False


def test_parses_tank(aquarea_status):
    dev = AquareaDevice.from_status("B218954411", aquarea_status)
    assert dev.tank is not None
    assert dev.tank.on is True
    assert dev.tank.current_temperature == 46
    assert dev.tank.target_temperature == 52
    assert dev.tank.heat_min == 40 and dev.tank.heat_max == 65
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/api/test_models.py -v`
Expected: FAIL — cannot import `models`.

- [ ] **Step 4: Write the implementation** `custom_components/panasonic_aquarea/api/models.py`

```python
"""Parsed Aquarea status models (HA-agnostic)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class OperationMode(IntEnum):
    OFF = 0
    HEAT = 1
    COOL = 2
    AUTO = 3
    DHW = 4

    @classmethod
    def parse(cls, value: int) -> "OperationMode":
        try:
            return cls(value)
        except ValueError:
            return cls.OFF


class ZoneMode(IntEnum):
    """Whether a zone's setpoint is an absolute room temp or a compensation offset."""
    ABSOLUTE = 0
    OFFSET = 1


@dataclass(frozen=True)
class Zone:
    zone_id: int
    name: str
    mode: ZoneMode
    on: bool
    current_temperature: int
    heat_setpoint: int
    cool_setpoint: int
    heat_min: int
    heat_max: int
    cool_min: int
    cool_max: int

    @classmethod
    def from_dict(cls, d: dict) -> "Zone":
        heat_min = d["heatMin"]
        heat_max = d["heatMax"]
        # Offset-mode zones use a symmetric range around 0 (e.g. -5..5); absolute
        # zones use real temperatures (e.g. 10..30). Negative min is the tell.
        mode = ZoneMode.OFFSET if heat_min < 0 else ZoneMode.ABSOLUTE
        return cls(
            zone_id=d["zoneId"],
            name=d["zoneName"],
            mode=mode,
            on=bool(d["operationStatus"]),
            current_temperature=d["temperatureNow"],
            heat_setpoint=d["heatSet"],
            cool_setpoint=d["coolSet"],
            heat_min=heat_min,
            heat_max=heat_max,
            cool_min=d["coolMin"],
            cool_max=d["coolMax"],
        )


@dataclass(frozen=True)
class Tank:
    on: bool
    current_temperature: int
    target_temperature: int
    heat_min: int
    heat_max: int

    @classmethod
    def from_dict(cls, d: dict) -> "Tank":
        return cls(
            on=bool(d["operationStatus"]),
            current_temperature=d["temperatureNow"],
            target_temperature=d["heatSet"],
            heat_min=d["heatMin"],
            heat_max=d["heatMax"],
        )


@dataclass(frozen=True)
class AquareaDevice:
    guid: str
    name: str
    service_type: str
    operation_mode: OperationMode
    outdoor_temperature: int
    water_pressure: float
    pump_duty: int
    defrost: bool
    fault: bool
    force_dhw: bool
    zones: tuple[Zone, ...]
    tank: Tank | None

    @classmethod
    def from_status(cls, guid: str, payload: dict) -> "AquareaDevice":
        """Parse a /remote/v1/api/devices transfer response into a device model."""
        status = payload["status"]
        tank_raw = status.get("tankStatus")
        return cls(
            guid=guid,
            name=payload.get("a2wName", guid),
            service_type=status.get("serviceType", ""),
            operation_mode=OperationMode.parse(status.get("operationMode", 0)),
            outdoor_temperature=status.get("outdoorNow"),
            water_pressure=status.get("waterPressure"),
            pump_duty=status.get("pumpDuty", 0),
            defrost=bool(status.get("deiceStatus", 0)),
            fault=bool(status.get("specialStatus", 0)),
            force_dhw=bool(status.get("forceDHW", 0)),
            zones=tuple(Zone.from_dict(z) for z in status.get("zoneStatus", [])),
            tank=Tank.from_dict(tank_raw) if tank_raw else None,
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/api/test_models.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add custom_components/panasonic_aquarea/api/models.py tests/api/test_models.py tests/fixtures/aquarea_status.json
git commit -m "feat: add aquarea status models and parsing"
```

### Task 5: Client — construction, headers, app version

**Files:**
- Create: `custom_components/panasonic_aquarea/api/client.py`
- Test: `tests/api/test_client.py`

- [ ] **Step 1: Write the failing test** `tests/api/test_client.py`

```python
import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.panasonic_aquarea.api.client import PanasonicCloudClient
from custom_components.panasonic_aquarea.api.const import PLAY_STORE_URL, APP_VERSION_FALLBACK


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


async def test_headers_include_required_fields(session):
    client = PanasonicCloudClient(session, "user", "pass")
    client._token = "TKN"
    headers = client._headers()
    assert headers["X-APP-TYPE"] == "1"
    assert headers["X-APP-NAME"] == "Comfort Cloud"
    assert headers["X-User-Authorization-V2"] == "Bearer TKN"
    assert headers["X-CFC-API-KEY"][9:12] == "cfc"
    assert headers["X-APP-VERSION"] == APP_VERSION_FALLBACK  # default before fetch


async def test_fetch_app_version_parses_play_store(session):
    client = PanasonicCloudClient(session, "user", "pass")
    with aioresponses() as m:
        m.get(PLAY_STORE_URL, body='junk ["4.5.1"] more junk', status=200)
        version = await client._fetch_app_version()
    assert version == "4.5.1"


async def test_fetch_app_version_falls_back_on_error(session):
    client = PanasonicCloudClient(session, "user", "pass")
    with aioresponses() as m:
        m.get(PLAY_STORE_URL, status=500)
        version = await client._fetch_app_version()
    assert version == APP_VERSION_FALLBACK
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_client.py -v`
Expected: FAIL — cannot import `client`.

- [ ] **Step 3: Write the implementation** `custom_components/panasonic_aquarea/api/client.py`

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_client.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/panasonic_aquarea/api/client.py tests/api/test_client.py
git commit -m "feat: add client skeleton with headers and app-version fetch"
```

### Task 6: Client — OAuth2 + PKCE login

**Files:**
- Modify: `custom_components/panasonic_aquarea/api/client.py`
- Test: `tests/api/test_client.py`

- [ ] **Step 1: Add the failing test** (append to `tests/api/test_client.py`)

```python
import base64
import hashlib

from custom_components.panasonic_aquarea.api import const as c


async def test_login_full_flow(session):
    client = PanasonicCloudClient(session, "user", "pass")
    with aioresponses() as m:
        # play store version
        m.get(PLAY_STORE_URL, body='["4.3.0"]', status=200)
        # /authorize -> 302 to /login with ?state=STATE
        m.get(
            re.compile(rf"{re.escape(c.AUTH_BASE)}/authorize.*"),
            status=302,
            headers={"Location": f"{c.AUTH_BASE}/login?state=STATE123"},
        )
        # GET the login page -> sets _csrf cookie
        m.get(
            re.compile(rf"{re.escape(c.AUTH_BASE)}/login.*"),
            status=200,
            headers={"Set-Cookie": "_csrf=CSRF123; Path=/"},
            body="<html></html>",
        )
        # /usernamepassword/login -> HTML form with hidden inputs
        m.post(
            f"{c.AUTH_BASE}/usernamepassword/login",
            status=200,
            body=(
                '<form>'
                '<input type="hidden" name="wa" value="wsignin1.0"/>'
                '<input type="hidden" name="wresult" value="RESULT"/>'
                '<input type="hidden" name="wctx" value="CTX"/>'
                "</form>"
            ),
        )
        # /login/callback -> 302 to redirect uri with ?code=
        m.post(
            f"{c.AUTH_BASE}/login/callback",
            status=302,
            headers={"Location": f"{c.REDIRECT_URI}?code=AUTHCODE&state=STATE123"},
        )
        # token exchange
        m.post(
            f"{c.AUTH_BASE}/oauth/token",
            status=200,
            payload={"access_token": "ACCESS", "refresh_token": "REFRESH"},
        )
        # getClientId
        m.post(
            f"{c.API_BASE}/auth/v2/login",
            status=200,
            payload={"clientId": "CID"},
        )
        await client.login()

    assert client._token == "ACCESS"
    assert client._refresh_token == "REFRESH"
    assert client._client_id == "CID"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_client.py::test_login_full_flow -v`
Expected: FAIL — `login` not defined.

- [ ] **Step 3: Implement the PKCE login** (append methods to `PanasonicCloudClient` in `client.py`)

Add these imports at the top of `client.py`:
```python
import base64
import hashlib
import secrets
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse
```

Add a small hidden-input parser (module level in `client.py`):
```python
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
```

Add the login methods to the class:
```python
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

        # 1. /authorize -> 302 to login page (carries the real state)
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

        # 2. GET the login page to obtain the _csrf cookie
        login_url = location if location.startswith("http") else f"{const.AUTH_BASE}{location}"
        async with self._session.get(login_url, allow_redirects=False) as resp:
            csrf = ""
            for cookie in resp.headers.getall("Set-Cookie", []):
                m = re.search(r"_csrf=([^;]+)", cookie)
                if m:
                    csrf = m.group(1)
                    break

        # 3. POST credentials -> HTML form with hidden inputs
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

        # 4. POST the form to /login/callback -> 302 with ?code=
        async with self._session.post(
            f"{const.AUTH_BASE}/login/callback",
            data=parser.fields,
            allow_redirects=False,
        ) as resp:
            callback_location = resp.headers["Location"]
        code = self._query_param(callback_location, "code")
        if not code:
            # one more hop if the callback redirects again
            async with self._session.get(callback_location, allow_redirects=False) as resp:
                code = self._query_param(resp.headers["Location"], "code")
        if not code:
            raise AuthError("no authorization code returned")

        # 5. Exchange the code for tokens
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_client.py::test_login_full_flow -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/panasonic_aquarea/api/client.py tests/api/test_client.py
git commit -m "feat: implement oauth2 pkce login"
```

### Task 7: Client — token refresh

**Files:**
- Modify: `custom_components/panasonic_aquarea/api/client.py`
- Test: `tests/api/test_client.py`

- [ ] **Step 1: Add the failing test**

```python
async def test_refresh_token_updates_access_token(session):
    client = PanasonicCloudClient(session, "user", "pass", refresh_token="OLD")
    with aioresponses() as m:
        m.post(
            f"{c.AUTH_BASE}/oauth/token",
            status=200,
            payload={"access_token": "NEW_ACCESS", "refresh_token": "NEW_REFRESH"},
        )
        ok = await client.refresh()
    assert ok is True
    assert client._token == "NEW_ACCESS"
    assert client._refresh_token == "NEW_REFRESH"


async def test_refresh_returns_false_without_token(session):
    client = PanasonicCloudClient(session, "user", "pass")
    assert await client.refresh() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_client.py::test_refresh_token_updates_access_token -v`
Expected: FAIL — `refresh` not defined.

- [ ] **Step 3: Implement `refresh`** (append to the class)

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_client.py -k refresh -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/panasonic_aquarea/api/client.py tests/api/test_client.py
git commit -m "feat: add token refresh"
```

### Task 8: Client — get_devices and get_status

**Files:**
- Modify: `custom_components/panasonic_aquarea/api/client.py`
- Test: `tests/api/test_client.py`

- [ ] **Step 1: Add the failing test**

```python
async def test_get_devices_returns_aquarea_only(session):
    client = PanasonicCloudClient(session, "user", "pass")
    client._token = "TKN"
    client._client_id = "CID"
    with aioresponses() as m:
        m.get(
            f"{c.API_BASE}/device/group/",
            status=200,
            payload={
                "groupList": [
                    {"groupName": "House", "deviceList": [
                        {"deviceGuid": "AC1", "deviceType": "1", "deviceName": "Airco"},
                        {"deviceGuid": "HP1", "deviceType": "2", "deviceName": "Warmtepomp"},
                    ]}
                ]
            },
        )
        devices = await client.get_devices()
    assert devices == [("HP1", "Warmtepomp")]


async def test_get_status_returns_parsed_device(session, aquarea_status):
    client = PanasonicCloudClient(session, "user", "pass")
    client._token = "TKN"
    client._client_id = "CID"
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload=aquarea_status)
        device = await client.get_status("HP1")
    assert device.guid == "HP1"
    assert device.outdoor_temperature == 31
    assert device.tank.target_temperature == 52
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_client.py -k "get_devices or get_status" -v`
Expected: FAIL — methods not defined.

- [ ] **Step 3: Implement** (append to class; add `from .models import AquareaDevice` and `from .const import AQUAREA_DEVICE_TYPE` at top)

```python
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
```

Note: `AQUAREA_DEVICE_TYPE` is defined in `api/const.py` (Task 2). Import it via `from .const import AQUAREA_DEVICE_TYPE`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_client.py -v`
Expected: PASS (all client tests).

- [ ] **Step 5: Commit**

```bash
git add custom_components/panasonic_aquarea/api/client.py tests/api/test_client.py
git commit -m "feat: add device listing and status fetch"
```

### Task 9: Client — ensure_session wrapper (token lifecycle)

**Files:**
- Modify: `custom_components/panasonic_aquarea/api/client.py`
- Test: `tests/api/test_client.py`

- [ ] **Step 1: Add the failing test**

```python
async def test_ensure_session_logs_in_when_no_token(session):
    client = PanasonicCloudClient(session, "user", "pass")
    calls = {"login": 0, "refresh": 0}

    async def fake_login():
        calls["login"] += 1
        client._token = "ACCESS"

    async def fake_refresh():
        calls["refresh"] += 1
        return True

    client.login = fake_login          # type: ignore[assignment]
    client.refresh = fake_refresh      # type: ignore[assignment]

    await client.ensure_session()
    assert calls == {"login": 1, "refresh": 0}


async def test_ensure_session_refreshes_when_refresh_token_present(session):
    client = PanasonicCloudClient(session, "user", "pass", refresh_token="R")
    calls = {"login": 0, "refresh": 0}

    async def fake_login():
        calls["login"] += 1

    async def fake_refresh():
        calls["refresh"] += 1
        client._token = "ACCESS"
        client._client_id = "CID"
        return True

    client.login = fake_login          # type: ignore[assignment]
    client.refresh = fake_refresh      # type: ignore[assignment]

    await client.ensure_session()
    assert calls == {"login": 0, "refresh": 1}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_client.py -k ensure_session -v`
Expected: FAIL — `ensure_session` not defined.

- [ ] **Step 3: Implement** (append to class)

```python
    async def ensure_session(self) -> None:
        """Make sure we have a usable access token + client id.

        Prefer refreshing an existing refresh token (cheap, avoids the Auth0
        brute-force lockout); only do a full login when there is nothing to
        refresh or the refresh fails.
        """
        if self._token and self._client_id:
            return
        if self._refresh_token and await self.refresh():
            if not self._client_id:
                await self._resolve_client_id()
            return
        await self.login()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_client.py -k ensure_session -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the whole client suite and lint**

Run: `pytest tests/api -v && ruff check custom_components`
Expected: all PASS, no lint errors.

- [ ] **Step 6: Commit**

```bash
git add custom_components/panasonic_aquarea/api/client.py tests/api/test_client.py
git commit -m "feat: add session lifecycle helper"
```

---

## Phase C — HA skeleton (walking skeleton: one live sensor)

### Task 10: Config flow

**Files:**
- Create: `custom_components/panasonic_aquarea/config_flow.py`
- Test: `tests/test_config_flow.py`

- [ ] **Step 1: Write the failing test** `tests/test_config_flow.py`

```python
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.panasonic_aquarea.const import DOMAIN


async def test_user_flow_success(hass: HomeAssistant):
    with patch(
        "custom_components.panasonic_aquarea.config_flow.PanasonicCloudClient"
    ) as mock_client_cls:
        client = mock_client_cls.return_value
        client.login = AsyncMock()
        client.get_devices = AsyncMock(return_value=[("HP1", "Warmtepomp")])
        client._refresh_token = "REFRESH"

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == "form"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "u@example.com", "password": "pw"}
        )
        assert result["type"] == "create_entry"
        assert result["data"]["username"] == "u@example.com"
        assert result["data"]["refresh_token"] == "REFRESH"


async def test_user_flow_invalid_auth(hass: HomeAssistant):
    from custom_components.panasonic_aquarea.api.client import AuthError

    with patch(
        "custom_components.panasonic_aquarea.config_flow.PanasonicCloudClient"
    ) as mock_client_cls:
        client = mock_client_cls.return_value
        client.login = AsyncMock(side_effect=AuthError("bad creds"))

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "u@example.com", "password": "bad"}
        )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_auth"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_flow.py -v`
Expected: FAIL — `config_flow` import error.

- [ ] **Step 3: Implement** `custom_components/panasonic_aquarea/config_flow.py`

```python
"""Config flow for Panasonic Aquarea."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.client import AuthError, PanasonicCloudClient
from .const import CONF_PASSWORD, CONF_REFRESH_TOKEN, CONF_USERNAME, DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
)


class PanasonicAquareaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the Panasonic Aquarea config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = PanasonicCloudClient(
                session, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            try:
                await client.login()
                devices = await client.get_devices()
            except AuthError:
                errors["base"] = "invalid_auth"
            except Exception:  # noqa: BLE001 - surface anything else as a generic error
                errors["base"] = "cannot_connect"
            else:
                if not devices:
                    errors["base"] = "no_devices"
                else:
                    await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=user_input[CONF_USERNAME],
                        data={
                            CONF_USERNAME: user_input[CONF_USERNAME],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                            CONF_REFRESH_TOKEN: client._refresh_token,
                        },
                    )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
```

- [ ] **Step 4: Create `translations/en.json`**

```json
{
  "config": {
    "step": {
      "user": {
        "data": {"username": "Email", "password": "Password"}
      }
    },
    "error": {
      "invalid_auth": "Invalid credentials",
      "cannot_connect": "Failed to connect",
      "no_devices": "No Aquarea devices found on this account"
    },
    "abort": {"already_configured": "This account is already configured"}
  }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_config_flow.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add custom_components/panasonic_aquarea/config_flow.py custom_components/panasonic_aquarea/translations tests/test_config_flow.py
git commit -m "feat: add config flow"
```

### Task 11: Coordinator and entry setup

**Files:**
- Create: `custom_components/panasonic_aquarea/coordinator.py`
- Replace: `custom_components/panasonic_aquarea/__init__.py`

- [ ] **Step 1: Implement the coordinator** `custom_components/panasonic_aquarea/coordinator.py`

```python
"""Data update coordinator for Panasonic Aquarea."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import ApiError, AuthError, PanasonicCloudClient
from .api.models import AquareaDevice
from .const import (
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class PanasonicAquareaCoordinator(DataUpdateCoordinator[dict[str, AquareaDevice]]):
    """Polls Comfort Cloud and exposes {guid: AquareaDevice}."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.entry = entry
        self._guids: list[str] = []
        self.client = PanasonicCloudClient(
            async_get_clientsession(hass),
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
            on_token_refresh=self._persist_refresh_token,
        )

    async def _persist_refresh_token(self, token: str) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_REFRESH_TOKEN: token}
        )

    async def _async_setup(self) -> None:
        try:
            await self.client.ensure_session()
            self._guids = [guid for guid, _ in await self.client.get_devices()]
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ApiError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_update_data(self) -> dict[str, AquareaDevice]:
        result: dict[str, AquareaDevice] = {}
        for guid in self._guids:
            try:
                await self.client.ensure_session()
                result[guid] = await self.client.get_status(guid)
            except AuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except ApiError as err:
                _LOGGER.warning("Failed to update %s: %s", guid, err)
        if not result:
            raise UpdateFailed("No device data retrieved")
        return result
```

- [ ] **Step 2: Replace** `custom_components/panasonic_aquarea/__init__.py`

```python
"""The Panasonic Aquarea integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import PanasonicAquareaCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

type PanasonicAquareaConfigEntry = ConfigEntry[PanasonicAquareaCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: PanasonicAquareaConfigEntry
) -> bool:
    coordinator = PanasonicAquareaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: PanasonicAquareaConfigEntry
) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
```

- [ ] **Step 3: Commit** (entity/sensor files come next; platforms will fail to import until Task 12 — acceptable as an intermediate commit since the integration isn't loaded by tests yet)

```bash
git add custom_components/panasonic_aquarea/coordinator.py custom_components/panasonic_aquarea/__init__.py
git commit -m "feat: add coordinator and entry setup"
```

### Task 12: Base entity and the first sensor (outdoor temperature)

**Files:**
- Create: `custom_components/panasonic_aquarea/entity.py`
- Create: `custom_components/panasonic_aquarea/sensor.py`
- Create: `custom_components/panasonic_aquarea/binary_sensor.py`

- [ ] **Step 1: Implement the base entity** `custom_components/panasonic_aquarea/entity.py`

```python
"""Base entity for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.helpers.device_info import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PanasonicAquareaCoordinator


class AquareaEntity(CoordinatorEntity[PanasonicAquareaCoordinator]):
    """Common base wiring coordinator data + device_info for one heat pump."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PanasonicAquareaCoordinator, guid: str) -> None:
        super().__init__(coordinator)
        self._guid = guid
        device = coordinator.data[guid]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, guid)},
            manufacturer="Panasonic",
            name=device.name,
            model=device.service_type,
        )

    @property
    def device(self):
        return self.coordinator.data[self._guid]

    @property
    def available(self) -> bool:
        return super().available and self._guid in self.coordinator.data
```

- [ ] **Step 2: Implement the sensor platform** `custom_components/panasonic_aquarea/sensor.py`

```python
"""Sensor platform for Panasonic Aquarea."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfPressure, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PanasonicAquareaConfigEntry
from .api.models import AquareaDevice
from .entity import AquareaEntity


@dataclass(frozen=True, kw_only=True)
class AquareaSensorDescription(SensorEntityDescription):
    value_fn: Callable[[AquareaDevice], float | int | str | None]


SENSORS: tuple[AquareaSensorDescription, ...] = (
    AquareaSensorDescription(
        key="outdoor_temperature",
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.outdoor_temperature,
    ),
    AquareaSensorDescription(
        key="water_pressure",
        translation_key="water_pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.BAR,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.water_pressure,
    ),
    AquareaSensorDescription(
        key="pump_duty",
        translation_key="pump_duty",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.pump_duty,
    ),
    AquareaSensorDescription(
        key="operation_mode",
        translation_key="operation_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["off", "heat", "cool", "auto", "dhw"],
        value_fn=lambda d: d.operation_mode.name.lower(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PanasonicAquareaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for guid, device in coordinator.data.items():
        entities += [AquareaSensor(coordinator, guid, desc) for desc in SENSORS]
        # per-zone current temperature
        for zone in device.zones:
            entities.append(AquareaZoneTempSensor(coordinator, guid, zone.zone_id))
        if device.tank is not None:
            entities.append(AquareaTankTempSensor(coordinator, guid))
    async_add_entities(entities)


class AquareaSensor(AquareaEntity, SensorEntity):
    entity_description: AquareaSensorDescription

    def __init__(self, coordinator, guid, description: AquareaSensorDescription) -> None:
        super().__init__(coordinator, guid)
        self.entity_description = description
        self._attr_unique_id = f"{guid}_{description.key}"

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.device)


class AquareaZoneTempSensor(AquareaEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, guid, zone_id: int) -> None:
        super().__init__(coordinator, guid)
        self._zone_id = zone_id
        self._attr_unique_id = f"{guid}_zone{zone_id}_temperature"
        self._attr_translation_key = "zone_temperature"
        self._attr_translation_placeholders = {"zone": self._zone().name}

    def _zone(self):
        return next(z for z in self.device.zones if z.zone_id == self._zone_id)

    @property
    def native_value(self):
        return self._zone().current_temperature


class AquareaTankTempSensor(AquareaEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "tank_temperature"

    def __init__(self, coordinator, guid) -> None:
        super().__init__(coordinator, guid)
        self._attr_unique_id = f"{guid}_tank_temperature"

    @property
    def native_value(self):
        return self.device.tank.current_temperature
```

- [ ] **Step 3: Implement the binary_sensor platform** `custom_components/panasonic_aquarea/binary_sensor.py`

```python
"""Binary sensor platform for Panasonic Aquarea."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PanasonicAquareaConfigEntry
from .api.models import AquareaDevice
from .entity import AquareaEntity


@dataclass(frozen=True, kw_only=True)
class AquareaBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[AquareaDevice], bool]


BINARY_SENSORS: tuple[AquareaBinaryDescription, ...] = (
    AquareaBinaryDescription(
        key="defrost",
        translation_key="defrost",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda d: d.defrost,
    ),
    AquareaBinaryDescription(
        key="fault",
        translation_key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda d: d.fault,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PanasonicAquareaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        AquareaBinarySensor(coordinator, guid, desc)
        for guid in coordinator.data
        for desc in BINARY_SENSORS
    )


class AquareaBinarySensor(AquareaEntity, BinarySensorEntity):
    entity_description: AquareaBinaryDescription

    def __init__(self, coordinator, guid, description: AquareaBinaryDescription) -> None:
        super().__init__(coordinator, guid)
        self.entity_description = description
        self._attr_unique_id = f"{guid}_{description.key}"

    @property
    def is_on(self) -> bool:
        return self.entity_description.value_fn(self.device)
```

- [ ] **Step 4: Add the new entity translation keys** to `translations/en.json` (merge an `entity` block alongside the existing `config` block)

```json
{
  "entity": {
    "sensor": {
      "outdoor_temperature": {"name": "Outdoor temperature"},
      "water_pressure": {"name": "Water pressure"},
      "pump_duty": {"name": "Pump duty"},
      "operation_mode": {"name": "Operation mode"},
      "zone_temperature": {"name": "{zone} temperature"},
      "tank_temperature": {"name": "Tank temperature"}
    },
    "binary_sensor": {
      "defrost": {"name": "Defrost"},
      "fault": {"name": "Fault"}
    }
  }
}
```

(Keep the existing `config` object; this `entity` object is a sibling key in the same JSON.)

- [ ] **Step 5: Add an integration load test** `tests/test_init.py`

```python
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.panasonic_aquarea.api.models import AquareaDevice
from custom_components.panasonic_aquarea.const import DOMAIN


async def test_entities_created(hass: HomeAssistant, aquarea_status):
    device = AquareaDevice.from_status("HP1", aquarea_status)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "u", "password": "p", "refresh_token": "r"},
        unique_id="u",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.panasonic_aquarea.coordinator.PanasonicCloudClient"
    ) as cls:
        client = cls.return_value
        client.ensure_session = AsyncMock()
        client.get_devices = AsyncMock(return_value=[("HP1", "Warmtepomp")])
        client.get_status = AsyncMock(return_value=device)

        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # outdoor temp sensor exists and has the right value
    state = hass.states.get("sensor.warmtepomp_outdoor_temperature")
    assert state is not None
    assert state.state == "31"
```

- [ ] **Step 6: Run the full suite + lint**

Run: `pytest -v && ruff check custom_components`
Expected: all PASS, no lint errors.

- [ ] **Step 7: Commit**

```bash
git add custom_components/panasonic_aquarea tests/test_init.py
git commit -m "feat: add base entity, sensors and binary sensors"
```

---

## Phase D — Live verification

### Task 13: Live smoke test against the real cloud

**Files:**
- Create: `tests/live_smoke.py`

- [ ] **Step 1: Implement the manual smoke script** `tests/live_smoke.py`

```python
"""Manual live check against the real Comfort Cloud. NOT run in CI.

Usage:
    PANASONIC_USERNAME=... PANASONIC_PASSWORD=... python tests/live_smoke.py
"""
import asyncio
import os

import aiohttp

from custom_components.panasonic_aquarea.api.client import PanasonicCloudClient


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        client = PanasonicCloudClient(
            session, os.environ["PANASONIC_USERNAME"], os.environ["PANASONIC_PASSWORD"]
        )
        await client.login()
        devices = await client.get_devices()
        print("Aquarea devices:", devices)
        for guid, name in devices:
            device = await client.get_status(guid)
            print(f"\n{name} ({guid}):")
            print(f"  mode={device.operation_mode.name} outdoor={device.outdoor_temperature}°C")
            print(f"  water_pressure={device.water_pressure} bar pump_duty={device.pump_duty}%")
            for zone in device.zones:
                print(f"  zone {zone.name}: {zone.mode.name} on={zone.on} now={zone.current_temperature}°C")
            if device.tank:
                print(f"  tank: now={device.tank.current_temperature}°C set={device.tank.target_temperature}°C")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run it against the real account** (one-off; this is the true end-to-end proof — mirrors what `index.js` did)

Run:
```bash
PANASONIC_USERNAME="$(grep ^USERNAME .env | cut -d= -f2)" \
PANASONIC_PASSWORD="$(grep ^PASSWORD .env | cut -d= -f2)" \
python tests/live_smoke.py
```
Expected: prints the Aquarea device and live values (outdoor ~31°C, tank temps, two zones). If it errors on login, wait out any Auth0 cooldown before retrying (do not loop).

- [ ] **Step 3: Install into the running HA and confirm entities**

Copy the integration to the ODroid and restart (see `NOTES.md` for the container/SSH pattern):
```bash
# from repo root, on the machine with SSH access to the ODroid
scp -r custom_components/panasonic_aquarea <odroid>:/tmp/
# then on the ODroid:
sudo docker cp /tmp/panasonic_aquarea homeassistant:/config/custom_components/
sudo docker restart homeassistant
```
Then in HA: **Settings → Devices & Services → Add Integration → Panasonic Aquarea**, log in, and confirm the `Warmtepomp` device appears with outdoor temperature, water pressure, pump duty, operation mode, zone temps, tank temp, defrost and fault sensors.

- [ ] **Step 4: Commit**

```bash
git add tests/live_smoke.py
git commit -m "test: add live smoke check"
```

---

## Self-Review

**Spec coverage:**
- Self-contained client, no community lib → Tasks 3–9 (stdlib + aiohttp only; `manifest.json` requirements `[]`). ✓
- OAuth2+PKCE, CFC signing, app-version fetch with `4.3.0` fallback → Tasks 3, 5, 6. ✓
- Token lifecycle (refresh-first, login fallback, `on_token_refresh` persistence, no re-login spam) → Tasks 7, 9, 11. ✓
- `get_devices` (deviceType 2) + `get_status` `deviceDirect=0` → Task 8. ✓
- Models incl. absolute-vs-offset zone detection → Task 4. ✓
- Config flow, one entry per account, reauth error mapping → Task 10. ✓
- Coordinator 5-min `deviceDirect=0`, error mapping, per-device isolation → Task 11. ✓
- Read entities table (outdoor/pressure/pump/op-mode/zone temp/tank temp sensors; defrost/fault binary) → Task 12. ✓
- Golden-fixture parsing test, config-flow tests, live smoke → Tasks 4, 10, 13. ✓
- Repo cleanup (`index.js` removed), `.tool-versions`, `hacs.json`, `ruff` → Tasks 1, 2. ✓
- **Deferred (correctly out of scope here):** climate/water_heater/switch/number control entities and the offset-zone `number` entity — these are Plan 2 (control), gated behind the write spike. Read-only Plan 1 represents zones via temp sensors only; no control surface yet. This is intentional.

**Placeholder scan:** No TBD/TODO; every code step has complete code. ✓

**Type consistency:** `PanasonicCloudClient` signature (Task 5) used consistently in config_flow (Task 10) and coordinator (Task 11). `AquareaDevice.from_status`, `.zones`, `.tank`, `.operation_mode` consistent across models (Task 4), sensors (Task 12), smoke test (Task 13). `ensure_session`/`refresh`/`login`/`get_devices`/`get_status` names consistent across Tasks 6–9 and consumers. ✓

---

## Notes for the implementer

- The CFC timestamp/UTC handling mirrors the proven `index.js`: the same string goes into `X-APP-TIMESTAMP` and into the key derivation. Don't "fix" the timezone independently in one place.
- `client._token` / `client._refresh_token` are accessed by tests and the config flow as needed; keep their names stable. If you prefer public accessors, add them and update all three call sites together.
- Control is **out of scope** here. Do not add write methods or climate/water_heater entities — that's the follow-on plan, which begins with a write-verification spike before any control entity.
```
