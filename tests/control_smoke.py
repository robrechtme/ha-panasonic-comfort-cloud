"""Manual control spike — verifies a real, reversible setpoint write. NOT in CI.

Confirms (a) whether the short deviceGuid works as the write `gwid`, and
(b) that a zone setpoint write round-trips: reads Beneden (zone 2), sets its
active setpoint to 21, reads back, then restores 22.

Usage:
    PANASONIC_USERNAME=... PANASONIC_PASSWORD=... PYTHONPATH=. python tests/control_smoke.py
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp  # noqa: E402

from custom_components.panasonic_aquarea.api import const  # noqa: E402
from custom_components.panasonic_aquarea.api.client import PanasonicCloudClient  # noqa: E402
from custom_components.panasonic_aquarea.api.models import OperationMode  # noqa: E402

ZONE_ID = 2  # Beneden


async def write_zone(session, c, guid, zone_id, key, value):
    body = {
        "apiName": "/remote/v1/api/devices",
        "requestMethod": "POST",
        "bodyParam": {"gwid": guid, "zoneStatus": [{"zoneId": zone_id, key: value}]},
    }
    async with session.post(
        f"{const.API_BASE}/remote/v1/app/common/transfer",
        json=body,
        headers=c._headers(client_id=True),
    ) as resp:
        text = await resp.text()
        print(f"  write {key}={value} -> HTTP {resp.status}: {text[:160]}")
        return resp.status


def zone_setpoint(device, zone_id):
    z = next(zz for zz in device.zones if zz.zone_id == zone_id)
    cooling = device.operation_mode is OperationMode.COOL
    return (z.cool_setpoint if cooling else z.heat_setpoint), ("coolSet" if cooling else "heatSet"), z.name


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        c = PanasonicCloudClient(
            session, os.environ["PANASONIC_USERNAME"], os.environ["PANASONIC_PASSWORD"]
        )
        await c.login()

        async with session.get(
            f"{const.API_BASE}/device/group/", headers=c._headers(client_id=True)
        ) as resp:
            dev = (await resp.json())["groupList"][0]["deviceList"][0]
        print("device-list entry keys:", list(dev.keys()))
        guid = dev["deviceGuid"]
        print("deviceGuid (used as write gwid):", guid)

        before = await c.get_status(guid)
        sp, key, name = zone_setpoint(before, ZONE_ID)
        print(f"\n{name} (zone {ZONE_ID}) active setpoint before: {key}={sp}")

        print("\n-> setting 21")
        status1 = await write_zone(session, c, guid, ZONE_ID, key, 21)
        mid = await c.get_status(guid)
        sp_mid, _, _ = zone_setpoint(mid, ZONE_ID)
        print(f"  read-back: {key}={sp_mid}")

        print("\n-> restoring 22")
        await write_zone(session, c, guid, ZONE_ID, key, 22)
        after = await c.get_status(guid)
        sp_after, _, _ = zone_setpoint(after, ZONE_ID)
        print(f"  read-back: {key}={sp_after}")

        ok = status1 == 200 and sp_mid == 21 and sp_after == 22
        print(f"\nRESULT: {'WRITE PATH CONFIRMED via deviceGuid' if ok else 'NEEDS INVESTIGATION'}")


if __name__ == "__main__":
    asyncio.run(main())
