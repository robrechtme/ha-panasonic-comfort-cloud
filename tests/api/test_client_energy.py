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


def _last_body(m):
    for (method, url), calls in m.requests.items():
        if method == "POST" and str(url).endswith("/remote/v1/app/common/transfer"):
            return calls[-1].kwargs["json"]
    raise AssertionError("no transfer POST")


async def test_get_energy_today_sums_buckets(client):
    payload = {
        "historyDataList": [
            {
                "dataTime": "20260529 09",
                "heatConsumption": 0,
                "coolConsumption": 0.05,
                "tankConsumption": 0,
            },
            {
                "dataTime": "20260529 10",
                "heatConsumption": 0.1,
                "coolConsumption": 0.07,
                "tankConsumption": 0.2,
            },
        ]
    }
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload=payload)
        totals = await client.get_energy_today("HP1", "20260529", "+02:00")
        body = _last_body(m)
    assert body["bodyParam"] == {
        "gwid": "HP1", "dataMode": 0, "date": "20260529", "osTimezone": "+02:00"
    }
    assert body["apiName"] == "/remote/v1/api/consumption"
    assert totals.heating == 0.1
    assert totals.cooling == 0.12
    assert totals.hot_water == 0.2
    assert totals.total == 0.42
