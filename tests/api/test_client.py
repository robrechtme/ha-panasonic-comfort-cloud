import re

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.panasonic_aquarea.api import const as c
from custom_components.panasonic_aquarea.api.client import ApiError, AuthError, PanasonicCloudClient
from custom_components.panasonic_aquarea.api.const import APP_VERSION_FALLBACK, PLAY_STORE_URL


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


async def test_login_raises_autherror_when_authorize_has_no_redirect(session):
    client = PanasonicCloudClient(session, "user", "pass")
    with aioresponses() as m:
        m.get(PLAY_STORE_URL, body='["4.3.0"]', status=200)
        # Auth0 returns 200 with no Location (e.g. throttled / error page)
        m.get(re.compile(rf"{re.escape(c.AUTH_BASE)}/authorize.*"), status=200, body="nope")
        with pytest.raises(AuthError):
            await client.login()


async def test_get_status_raises_apierror_on_error_envelope(session):
    client = PanasonicCloudClient(session, "user", "pass")
    client._token = "TKN"
    client._client_id = "CID"
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload={"result": 4106})
        with pytest.raises(ApiError):
            await client.get_status("HP1")


async def test_get_status_retries_once_on_401(session):
    client = PanasonicCloudClient(session, "user", "pass", refresh_token="R")
    client._token = "TKN"
    client._client_id = "CID"
    status_payload = {"a2wName": "X", "status": {"serviceType": "T", "operationMode": 1,
                      "outdoorNow": 10, "waterPressure": 1.0, "pumpDuty": 0,
                      "deiceStatus": 0, "specialStatus": 0, "forceDHW": 0,
                      "zoneStatus": [], "tankStatus": None}}

    refreshed = {"n": 0}

    async def fake_refresh():
        refreshed["n"] += 1
        client._token = "TKN2"
        return True

    client.refresh = fake_refresh  # type: ignore[assignment]

    with aioresponses() as m:
        # first transfer attempt 401s, second (after refresh) succeeds
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=401)
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload=status_payload)
        device = await client.get_status("HP1")

    assert refreshed["n"] == 1
    assert device.guid == "HP1"
    assert device.operation_mode.name == "HEAT"


async def test_get_status_raises_if_401_persists(session):
    client = PanasonicCloudClient(session, "user", "pass", refresh_token="R")
    client._token = "TKN"
    client._client_id = "CID"

    async def fake_refresh():
        return True

    client.refresh = fake_refresh  # type: ignore[assignment]

    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=401)
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=401)
        with pytest.raises(ApiError):
            await client.get_status("HP1")


async def test_login_handles_relative_callback_resume(session):
    client = PanasonicCloudClient(session, "user", "pass")
    with aioresponses() as m:
        m.get(PLAY_STORE_URL, body='["4.3.0"]', status=200)
        m.get(
            re.compile(rf"{re.escape(c.AUTH_BASE)}/authorize\?.*"),
            status=302,
            headers={"Location": f"{c.AUTH_BASE}/login?state=S"},
        )
        m.get(
            re.compile(rf"{re.escape(c.AUTH_BASE)}/login.*"),
            status=200,
            headers={"Set-Cookie": "_csrf=C; Path=/"},
            body="<html></html>",
        )
        m.post(
            f"{c.AUTH_BASE}/usernamepassword/login",
            status=200,
            body='<input type="hidden" name="wa" value="x"/>',
        )
        # Real cloud: callback redirects to a RELATIVE /authorize/resume
        m.post(
            f"{c.AUTH_BASE}/login/callback",
            status=302,
            headers={"Location": "/authorize/resume?state=S"},
        )
        # Resuming (absolute URL must be formed) yields the auth code
        m.get(
            re.compile(rf"{re.escape(c.AUTH_BASE)}/authorize/resume.*"),
            status=302,
            headers={"Location": f"{c.REDIRECT_URI}?code=CODE&state=S"},
        )
        m.post(
            f"{c.AUTH_BASE}/oauth/token",
            status=200,
            payload={"access_token": "A", "refresh_token": "R"},
        )
        m.post(f"{c.API_BASE}/auth/v2/login", status=200, payload={"clientId": "CID"})
        await client.login()
    assert client._token == "A"
    assert client._client_id == "CID"
