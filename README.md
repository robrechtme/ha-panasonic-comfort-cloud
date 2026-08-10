# Panasonic Aquarea — Home Assistant integration

A self-contained Home Assistant custom integration for **Panasonic Aquarea** air-to-water heat
pumps, via Panasonic Comfort Cloud. Reads live status (zones, DHW tank, outdoor temperature, pump
duty, defrost, fault) and exposes it as Home Assistant entities.

It talks to Comfort Cloud directly through the app's proxy endpoint — **no dependency on any
third-party Panasonic library** (stdlib + Home Assistant's bundled `aiohttp` only), so it doesn't
break when community libraries fall behind Panasonic's API changes.

> **Status:** read + control. See [`docs/superpowers/specs`](docs/superpowers/specs) for the design.

## Entities

| Platform | Entity |
|---|---|
| `climate` | One per absolute-temperature zone — mode (Off / Heat / Cool / Auto), setpoint (1° step); Auto uses a heat/cool range. Mode is device-wide. |
| `water_heater` | DHW tank (target temperature + on/off) |
| `number` | Compensation offset, one per offset-mode zone |
| `switch` | Per offset-zone on/off, and Force DHW |
| `sensor` | Outdoor temperature, per-zone temperature, DHW tank temperature |
| `sensor` (energy) | Daily Heating / Cooling / Hot water / Total energy (kWh) for the Energy dashboard |
| `binary_sensor` | Defrost active, fault, pump running |

Zones are auto-detected: absolute-temperature zones become `climate` entities (which also carry the
device-wide operation mode); compensation-offset zones become a `number` (the offset) plus an on/off
`switch`. All entities group under one device per heat pump.

## Installation (HACS — custom repository)

1. In Home Assistant, open **HACS**.
2. Top-right **⋮ → Custom repositories**.
3. Add repository URL `https://github.com/robrechtme/ha-panasonic-comfort-cloud`, type
   **Integration**, and click **Add**.
4. Find **Panasonic Aquarea** in the HACS list and **Download** it.
5. **Restart Home Assistant.**
6. **Settings → Devices & Services → Add Integration → Panasonic Aquarea**, and sign in with your
   Panasonic Comfort Cloud email and password.

### Energy dashboard

The four "energy today" sensors are `total_increasing` kWh and reset at midnight. Add them under
**Settings → Energy → Add consumption** to chart the heat pump's daily heating / cooling / hot-water
usage. Values come from Panasonic's hourly consumption history, so they lag by up to ~1 hour, and a
category reads 0 until it's actually used (e.g. heating in summer). Requires a unit with energy
metering.

For accurate hour-by-hour attribution (matching against a smart meter, etc.), use the four
external statistics instead — `panasonic_aquarea:<guid>_{heating,cooling,hot_water,total}_energy`,
selectable as a separate consumption source in the Energy dashboard. These are backfilled directly
from Panasonic's own per-hour buckets, so — unlike the polled sensors above — they don't misattribute
consumption to the wrong hour.

### Manual installation

Copy `custom_components/panasonic_aquarea` into your Home Assistant `config/custom_components/`
directory and restart.

## Requirements

- A Panasonic Comfort Cloud account with the Aquarea heat pump registered (the same account/app
  you use on your phone).
- Home Assistant 2024.1 or newer.

## Known limitations

- **Water pressure** is only reported by Panasonic's *live* (`deviceDirect=1`) response; the cached
  polling mode this integration uses (`deviceDirect=0`, chosen for reliability) omits it, so no water
  pressure sensor is exposed.
- Offset-mode zone `number` controls always edit the heat-compensation offset (the API setpoint is
  mode-agnostic for those zones).

## License

MIT
