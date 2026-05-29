# Panasonic heat pump — working setup & notes

## TL;DR

- The heat pump (`Warmtepomp`, guid `B218954411`) is an **Aquarea air-to-water unit** (`deviceType: 2`) registered in **Panasonic Comfort Cloud**.
- It's live in Home Assistant via a **locally-patched** `sockless-coding/panasonic_cc` integration (climate + water_heater + sensor entities).
- `index.js` in this repo is a standalone Node read-out of the same data, useful as a CLI sanity check.

## Environment

- HA runs as Docker container **`homeassistant`** on the ODroid (`robflix`), accessed over SSH.
- Docker needs `sudo` (user not in the `docker` group).
- Integration files live in the bind-mounted `/config/custom_components/panasonic_cc/`.

## Why the integration needed patching

Upstream `panasonic_cc` is **effectively unmaintained** (last release 2025.5.0, May 2025; fix PRs unmerged; codeowner archived his dedicated Aquarea integration). Out of the box it failed for Aquarea in four ways:

1. **Options/config flow 500** — `OptionsFlow.config_entry` is read-only in newer HA cores.
2. **Broken Aquarea login** — pinned `aioaquarea==0.7.2` crashes (`com.auth0.state` cookie gone). Fixed upstream in `aioaquarea==1.0.0` ("new auth mechanism") but never adopted by the integration.
3. **1.x API drift** — `get_devices(include_long_id=...)` arg removed; device `.name`/`.version` renamed.
4. **`TOKEN_EXPIRED`** on the Aquarea Smart Cloud *device-direct* status path — avoided by using the Comfort Cloud proxy path (`device_direct=False`), which is the same path `index.js` uses.

## ⚠️ Fragility

These are **manual edits inside the container's config volume**. They survive container restarts/recreation (the volume persists) but **any HACS update to `panasonic_cc` overwrites all of them** and breaks the heat pump again. Don't update the integration — or reapply the patches below afterwards. Each patched file has a `.bak` next to it.

## Reapply the patches (run on the ODroid over SSH)

```bash
# 1. Fix the options-flow 500 (config_flow.py)
sudo docker exec -i homeassistant python3 - <<'EOF'
import pathlib, shutil
p = pathlib.Path("/config/custom_components/panasonic_cc/config_flow.py")
shutil.copy(p, p.with_suffix(".py.bak"))
s = p.read_text()
s = s.replace("PanasonicOptionsFlowHandler(config_entry)", "PanasonicOptionsFlowHandler()")
s = s.replace(
'''    def __init__(self, config_entry):
        """Initialize Panasonic options flow."""
        self.config_entry = config_entry
''', "")
p.write_text(s)
print("config_flow:", "PanasonicOptionsFlowHandler()" in s and "self.config_entry = config_entry" not in s)
EOF

# 2. Bump aioaquarea + fix 1.x API call + use the Comfort Cloud proxy path
sudo docker exec -i homeassistant python3 - <<'EOF'
import pathlib, shutil
base = pathlib.Path("/config/custom_components/panasonic_cc")

m = base / "manifest.json"
shutil.copy(m, str(m) + ".bak")
m.write_text(m.read_text().replace("aioaquarea==0.7.2", "aioaquarea==1.0.7"))

i = base / "__init__.py"
shutil.copy(i, str(i) + ".bak")
t = i.read_text()
t = t.replace("get_devices(include_long_id=True)", "get_devices()")
t = t.replace("AquareaApiClient(client, username, password)",
              "AquareaApiClient(client, username, password, device_direct=False)")
i.write_text(t)
print("manifest:", "aioaquarea==1.0.7" in m.read_text())
print("init:", "include_long_id" not in t and "device_direct=False" in t)

# 3. Fix 1.x attribute renames (coordinator.py)
c = base / "coordinator.py"
shutil.copy(c, str(c) + ".bak")
ct = c.read_text()
ct = ct.replace("name=self.device.name,", "name=self.device.device_name,")
ct = ct.replace("sw_version=self.device.version,", "sw_version=self.device.firmware_version,")
c.write_text(ct)
print("coordinator:", "self.device.device_name" in ct and "self.device.firmware_version" in ct)
EOF

# 4. Restart (HA reinstalls aioaquarea 1.0.7 on boot — first start is slower)
sudo docker restart homeassistant

# 5. Verify (wait ~60s first)
sudo docker exec homeassistant pip show aioaquarea | grep -i version   # expect 1.0.7
sudo docker logs --since 3m homeassistant 2>&1 | grep -iE 'panasonic|aquarea|error|has no attribute' | tail -20
```

## Revert to stock

```bash
cd /config/custom_components/panasonic_cc
for f in config_flow.py manifest.json __init__.py coordinator.py; do sudo cp "$f.bak" "$f"; done
sudo docker restart homeassistant
```

## Verified API facts (for the future fork)

The durable path — what `index.js` and the `device_direct=False` setup both use — is the **Comfort Cloud proxy**, no `aioaquarea`/Aquarea Smart Cloud:

- Auth: OAuth2 + PKCE against `authglb.digital.panasonic.com` (handled by `panasonic-comfort-cloud-client` / `aio-panasonic-comfort-cloud`).
- App version gate: `X-APP-VERSION` must be current (`4.3.0` as of 2026-05); stale → error `4106`. Auto-fetched from the Play Store in `index.js`.
- Request signing: `X-CFC-API-KEY` (SHA-256 over `"Comfort Cloud" + fixed key + ms-timestamp + "Bearer " + token`).
- Device list: `GET https://accsmart.panasonic.com/device/group/` → Aquarea shows as `deviceType: "2"`.
- Live status: `POST /remote/v1/app/common/transfer` with
  `{ "apiName": "/remote/v1/api/devices?gwid=<guid>&deviceDirect=1", "requestMethod": "GET" }`
  → full zones / tank / outdoor temp / water pressure.

## deviceDirect: 0 vs 1

Both `index.js` and the (patched) HA integration hit the **same** endpoint —
`POST accsmart.panasonic.com/remote/v1/app/common/transfer` with
`apiName: /remote/v1/api/devices?gwid=<guid>&deviceDirect=N`. The only difference is `N`:

- `deviceDirect=1` — **live** poll of the gateway. `index.js` uses this and a one-off call works,
  but under HA's repeated polling it returned `TOKEN_EXPIRED`.
- `deviceDirect=0` — **cached** cloud status (same fields, possibly seconds-stale). Reliable;
  this is what `device_direct=False` selects and what made HA work.

**Fork guidance:** poll with `deviceDirect=0`; expose `deviceDirect=1` only as an optional
"refresh now" action.

## Available readings from the cloud (what the heat pump reports)

Captured from the live payload for this unit (`serviceType: STD_ADP-TAW1`). The HA plugin only
surfaces a subset (marked ✅); everything marked ❌ is available but **not** exposed by the plugin.

### System / outdoor
- operationMode (Off/Heat/Cool/Auto), current action (heat/cool/idle), direction
- outdoorNow — outdoor temperature ✅
- waterPressure (bar) ❌
- pumpDuty (pump load) ❌
- deiceStatus (defrost) ❌, specialStatus ❌, holidayTimer ❌
- quietMode ❌, powerful ❌
- forceDHW ❌, forceHeater ❌ (also controllable)
- is_on_error / current_error (fault code) ❌
- bivalent, externalHeater, electricAnode (often 0 if not fitted) ❌
- model / firmware / modelSeriesSelection

### Per zone (this unit has 2: Boven, Beneden)
- temperatureNow ✅ (climate / zone sensor)
- heatSet / coolSet target + heatMin/heatMax/coolMin/coolMax ✅ (climate)
- operationStatus on/off ✅
- ecoHeat/ecoCool, comfortHeat/comfortCool offsets ❌
- zoneSensor / sensor mode

### DHW tank
- temperatureNow ✅, heatSet target ✅, heatMin/heatMax ✅ (water_heater)
- operationStatus on/off ✅

### Energy & cost history — separate endpoint (`ConsumptionType`), NOT exposed for Aquarea in HA ❌
- consumption split by Heat / Cool / Tank(HW) / Total (kWh)
- cost per category (heatCost/coolCost/tankCost)
- historical outdoorTemp; aggregated by day/week/month/year

Note: writable controls also exist (operation mode, zone setpoints, tank setpoint, force DHW,
force heater, quiet, powerful, holiday) via `deviceStatus/control`-style transfer calls.

## Fork plan (later)

Build a clean HA custom integration using **only** the Comfort Cloud proxy path above (via `aio-panasonic-comfort-cloud`, which already exposes `get_aquarea_device()`), bypassing the broken Aquarea Smart Cloud layer entirely. Native climate/water_heater/sensor entities, read + control + automate, no dependency on the stalled upstream.
