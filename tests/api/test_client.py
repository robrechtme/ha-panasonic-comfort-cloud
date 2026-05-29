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
