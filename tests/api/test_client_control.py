import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.panasonic_aquarea.api import const as c
from custom_components.panasonic_aquarea.api.client import PanasonicCloudClient


@pytest.fixture
async def client():
    async with aiohttp.ClientSession() as s:
        cl = PanasonicCloudClient(s, "u", "p")
        cl._token = "TKN"
        cl._client_id = "CID"
        yield cl


def _last_transfer_body(mocked):
    for (method, url), calls in mocked.requests.items():
        if method == "POST" and str(url).endswith("/remote/v1/app/common/transfer"):
            return calls[-1].kwargs["json"]
    raise AssertionError("no transfer POST recorded")


async def test_set_tank_temperature_payload(client):
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload={"result": 0})
        await client.set_tank_temperature("HP1", 50)
        body = _last_transfer_body(m)
    assert body["apiName"] == "/remote/v1/api/devices"
    assert body["requestMethod"] == "POST"
    assert body["bodyParam"] == {"gwid": "HP1", "tankStatus": {"heatSet": 50}}


async def test_set_zone_heat_temperature_payload(client):
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload={"result": 0})
        await client.set_zone_temperature("HP1", 2, 21, cooling=False)
        body = _last_transfer_body(m)
    assert body["bodyParam"] == {"gwid": "HP1", "zoneStatus": [{"zoneId": 2, "heatSet": 21}]}


async def test_set_zone_cool_temperature_payload(client):
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload={"result": 0})
        await client.set_zone_temperature("HP1", 2, 24, cooling=True)
        body = _last_transfer_body(m)
    assert body["bodyParam"] == {"gwid": "HP1", "zoneStatus": [{"zoneId": 2, "coolSet": 24}]}


async def test_set_force_dhw_payload(client):
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload={"result": 0})
        await client.set_force_dhw("HP1", on=True)
        body = _last_transfer_body(m)
    assert body["bodyParam"] == {"gwid": "HP1", "forceDHW": 1}


async def test_set_operation_payload_bundles_mode_zones_and_tank(client):
    from custom_components.panasonic_aquarea.api.models import UpdateOperationMode
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload={"result": 0})
        await client.set_operation(
            "HP1", UpdateOperationMode.HEAT, [(1, True), (2, False)], tank_on=True
        )
        body = _last_transfer_body(m)
    assert body["bodyParam"] == {
        "gwid": "HP1",
        "operationMode": 1,
        "operationStatus": 1,
        "zoneStatus": [
            {"zoneId": 1, "operationStatus": 1},
            {"zoneId": 2, "operationStatus": 0},
        ],
        "tankStatus": {"operationStatus": 1},
    }
