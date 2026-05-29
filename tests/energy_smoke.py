"""Manual energy spike — fetches consumption history. Read-only. NOT in CI.

Usage:
    PANASONIC_USERNAME=... PANASONIC_PASSWORD=... PYTHONPATH=. python tests/energy_smoke.py
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp  # noqa: E402

from custom_components.panasonic_aquarea.api import const  # noqa: E402
from custom_components.panasonic_aquarea.api.client import PanasonicCloudClient  # noqa: E402

DATE = "20260529"  # today


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        c = PanasonicCloudClient(
            session, os.environ["PANASONIC_USERNAME"], os.environ["PANASONIC_PASSWORD"]
        )
        await c.login()
        guid = (await c.get_devices())[0][0]
        print("guid:", guid)

        for data_mode, label, date in [
            (0, "DAY/hourly", "20260529"),
            (1, "MONTH/daily", "20260529"),
            (2, "YEAR/monthly", "20260529"),
            (1, "MONTH/daily (Jan, heating season)", "20260115"),
        ]:
            body = {
                "apiName": "/remote/v1/api/consumption",
                "requestMethod": "POST",
                "bodyParam": {
                    "gwid": guid,
                    "dataMode": data_mode,
                    "date": date,
                    "osTimezone": "+02:00",
                },
            }
            data = await c._transfer(body, allow_refresh=True)
            buckets = data.get("historyDataList", []) if isinstance(data, dict) else []
            top_keys = list(data.keys()) if isinstance(data, dict) else None
            sums = {k: round(sum(b.get(k) or 0 for b in buckets), 3)
                    for k in ("heatConsumption", "coolConsumption", "tankConsumption")}
            print(f"\n=== dataMode={data_mode} ({label}) date={date} ===")
            print(f"top-level keys: {top_keys}; buckets: {len(buckets)}; sums: {sums}")
            nonzero = [b for b in buckets
                       if any(b.get(k) for k in ("heatConsumption", "coolConsumption", "tankConsumption"))]
            if nonzero:
                print(f"first non-zero bucket: {nonzero[0]}")


if __name__ == "__main__":
    asyncio.run(main())
