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
                print(
                    f"  zone {zone.name}: {zone.mode.name} on={zone.on} "
                    f"now={zone.current_temperature}°C"
                )
            if device.tank:
                print(
                    f"  tank: now={device.tank.current_temperature}°C "
                    f"set={device.tank.target_temperature}°C"
                )


if __name__ == "__main__":
    asyncio.run(main())
