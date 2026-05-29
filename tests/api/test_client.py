import base64
import hashlib
import re

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.panasonic_aquarea.api.client import PanasonicCloudClient
from custom_components.panasonic_aquarea.api.const import PLAY_STORE_URL, APP_VERSION_FALLBACK
from custom_components.panasonic_aquarea.api import const as c


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


async def test_login_full_flow(session):
    client = PanasonicCloudClient(session, "user", "pass")
    with aioresponses() as m:
        m.get(PLAY_STORE_URL, body='["4.3.0"]', status=200)
        m.get(
            re.compile(rf"{re.escape(c.AUTH_BASE)}/authorize.*"),
            status=302,
            headers={"Location": f"{c.AUTH_BASE}/login?state=STATE123"},
        )
        m.get(
            re.compile(rf"{re.escape(c.AUTH_BASE)}/login.*"),
            status=200,
            headers={"Set-Cookie": "_csrf=CSRF123; Path=/"},
            body="<html></html>",
        )
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
        m.post(
            f"{c.AUTH_BASE}/login/callback",
            status=302,
            headers={"Location": f"{c.REDIRECT_URI}?code=AUTHCODE&state=STATE123"},
        )
        m.post(
            f"{c.AUTH_BASE}/oauth/token",
            status=200,
            payload={"access_token": "ACCESS", "refresh_token": "REFRESH"},
        )
        m.post(
            f"{c.API_BASE}/auth/v2/login",
            status=200,
            payload={"clientId": "CID"},
        )
        await client.login()

    assert client._token == "ACCESS"
    assert client._refresh_token == "REFRESH"
    assert client._client_id == "CID"


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
