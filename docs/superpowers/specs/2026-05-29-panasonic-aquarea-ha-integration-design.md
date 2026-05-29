# Panasonic Aquarea — Home Assistant integration (design)

**Date:** 2026-05-29
**Status:** Approved design, pre-implementation
**Domain:** `panasonic_aquarea`

## Goal

A self-contained Home Assistant custom integration for a Panasonic **Aquarea** air-to-water
heat pump, talking to **Panasonic Comfort Cloud** through the proven proxy path (no Aquarea Smart
Cloud, no `aioaquarea`). Personal-first, but kept clean/HACS-shaped so it can be shared later.

Replaces reliance on the stalled `sockless-coding/panasonic_cc` integration (see `NOTES.md` for the
saga). Runs under its own domain so it coexists with the currently-patched `panasonic_cc` during
development; the old one is removed once this is trusted.

### v1 scope

Read + basic control:
- All readable status as sensors/binary_sensors.
- Per-zone climate control + DHW tank water_heater + Force-DHW switch.

Deferred to v2: energy/cost consumption history (separate cloud endpoint, not yet tested) and its
Energy-dashboard wiring; quiet/powerful controls; CI.

## Approach

**Chosen: C — fully self-contained.** Port our verified JS client (`index.js`, being removed) to
Python inside the integration. Take inspiration for wire details from `aio-panasonic-comfort-cloud`
(auth, signing, status parsing) and `aioaquarea`'s `AquareaDeviceControl` (write payloads), but
depend on **neither** at runtime. Rationale: the entire problem to date was depending on stalled
community libraries; owning the client removes that risk. We already have the full client working in
JS, so the port is low-uncertainty (except control writes — see Risks).

Rejected: (A) wrapping `aio-panasonic-comfort-cloud` — faster but reintroduces a community-lib
dependency; (B) forking `panasonic_cc` — inherits the messy stalled codebase we're escaping.

## Repository layout

This `panasonic-cc` repo becomes a HACS-compatible integration repo. `index.js`, `package.json`,
`node_modules/`, and `.cache.json` are removed; `NOTES.md` stays (documents the API + the HA patch).

```
panasonic-cc/
├── custom_components/
│   └── panasonic_aquarea/
│       ├── __init__.py           # setup entry, build client, start coordinator, unload
│       ├── manifest.json         # requirements: [] (stdlib + HA aiohttp only)
│       ├── config_flow.py        # login UI + reauth; one entry per account, devices auto-discovered
│       ├── coordinator.py        # DataUpdateCoordinator (deviceDirect=0)
│       ├── entity.py             # shared base: coordinator wiring + device_info
│       ├── api/                  # HA-agnostic client (port of index.js)
│       │   ├── client.py
│       │   ├── models.py
│       │   └── const.py
│       ├── sensor.py
│       ├── binary_sensor.py
│       ├── climate.py
│       ├── water_heater.py
│       ├── switch.py
│       ├── number.py             # offset-mode zone control (see zone nuance)
│       └── translations/en.json
├── NOTES.md
├── hacs.json
├── .tool-versions               # python 3.13 (mise/asdf)
├── pyproject.toml               # ruff + test config
└── tests/
```

**Design principle:** `api/` knows nothing about Home Assistant — a pure async Panasonic client,
standalone-usable like `index.js` was. All HA specifics live outside it. Clean boundary → the client
is unit-testable in isolation and the HA glue stays thin.

## Component: the client (`api/`)

`api/client.py` — `PanasonicCloudClient(session, username, password, *, token=None, on_token_refresh=None)`:

- `login()` — OAuth2 + PKCE: `/authorize` → scrape login form → `/usernamepassword/login` →
  `/login/callback` → exchange code at `/oauth/token`; then `get_client_id()` (`POST /auth/v2/login`).
- `_cfc_key(ts, token)` — SHA-256 `X-CFC-API-KEY` signing (port of `CFCGenerator`).
- `_app_version()` — fetch current version from the Play Store; fall back to pinned const `4.3.0`
  on failure. Defeats the `4106` "new version published" gate permanently.
- `get_devices()` — `GET /device/group/`; return `deviceType == "2"` (Aquarea) entries.
- `get_status(guid, direct=False)` — the `POST /remote/v1/app/common/transfer` call wrapping
  `apiName: /remote/v1/api/devices?gwid=<guid>&deviceDirect=<0|1>`, parsed into a model.
- control methods — `transfer` POST (payloads mapped during the control spike, see Risks).

**Token lifecycle (lessons baked in):**
- Never full-login when a usable token/refresh exists. On start: use stored token; if expired,
  `refresh_token` grant; only fall back to full `login()` if refresh fails.
- `on_token_refresh(new_refresh_token)` callback fires on rotation → HA layer persists it to the
  config entry (client stays HA-agnostic).
- Exponential backoff on consecutive auth failures so we never re-trip Auth0's brute-force lockout.

`api/models.py` — frozen dataclasses parsed from the payload, modeled on
`aio-panasonic-comfort-cloud`'s data classes:
- `AquareaDevice` — operation mode, current action, direction, outdoor temp, water pressure, pump
  duty, defrost (`deiceStatus`), fault (`is_on_error` + code), model/firmware/serviceType, `force_dhw`.
- `Zone` — name, type, sensor mode, current temp, setpoint, heat/cool min/max, on/off, **mode flag
  (absolute vs offset)**.
- `Tank` — current/target temp, min/max, on/off.

Raw ints → Python enums for modes/actions.

## Component: HA layer

`coordinator.py` — `PanasonicAquareaCoordinator(DataUpdateCoordinator)`:
- Update interval **5 min**, `deviceDirect=0`. Per device: `client.get_status(guid)` →
  `{guid: AquareaDevice}`.
- Wires `on_token_refresh` → persist rotated refresh token to the config entry.
- Per-device error isolation (one failing device doesn't block the others).

`entity.py` — shared base: subscribes to the coordinator, sets `device_info` so all entities group
under one HA device per heat pump (manufacturer `Panasonic`, model from `serviceType`, `sw_version`
from firmware).

### Entity mapping (v1)

| Platform | Entity | Source | R/W |
|---|---|---|---|
| `climate` | one per **absolute-temp** zone | temp / setpoint / mode / action | R/W |
| `number` | one per **offset-mode** zone | zone compensation offset (e.g. −5…+5) | R/W |
| `sensor` | per-zone current temp | `zone.temperatureNow` | R |
| `water_heater` | DHW tank | tank current/target, on/off | R/W |
| `switch` | Force DHW | `forceDHW` | R/W |
| `sensor` | Outdoor temp | `outdoorNow` | R |
| `sensor` | Water pressure | `waterPressure` | R |
| `sensor` | Pump duty | `pumpDuty` | R |
| `sensor` | Operation mode | `operationMode` (enum) | R |
| `binary_sensor` | Defrost active | `deiceStatus` | R |
| `binary_sensor` | Fault | `is_on_error` (+ code attribute) | R |

**Zone nuance:** zones differ in meaning. Beneden uses absolute room temps (`heatSet: 20`, range
10–30) → a proper `climate` entity. Boven is in offset/compensation mode (`heatSet: -5`, range −5…+5)
→ that's a curve offset, not a room temperature, so it becomes a `number` entity + temp `sensor`
rather than a misleading `climate` entity. Zone mode is detected at setup from the zone descriptor.

## Data flow

HA timer → coordinator → `client.get_status(guid, direct=False)` → `transfer` GET → parsed
`AquareaDevice` → entities read attributes. Control: entity service call → `client.set_*` → `transfer`
POST → optimistic state update → coordinator refresh to confirm.

## Error handling

| Failure | Handling |
|---|---|
| Invalid credentials | `ConfigEntryAuthFailed` → HA reauth (no silent retry loop) |
| `4106` app-version gate | Re-fetch Play Store version, retry once |
| `TOKEN_EXPIRED` on a call | Refresh token once, retry; still failing → `UpdateFailed` |
| Network/timeout | `UpdateFailed`; HA backs off; entities → `unavailable` |
| Repeated auth failures | Exponential backoff on `login()` (avoid Auth0 brute-force lockout) |
| One device errors | Isolated — other devices keep updating |

## Risks

**Control writes are unverified.** Reads are proven; no write has been sent to the pump yet. The
`transfer` POST payloads for set-zone-setpoint / set-mode / set-tank-target / force-DHW must be
mapped. Mitigation:
1. Reverse payloads from `aioaquarea` `AquareaDeviceControl` + `aio-panasonic-comfort-cloud`.
2. **Control spike before any control entity:** prove one write end-to-end against the real pump —
   send it, read back with `deviceDirect=1`, confirm the change. Only then build climate/water_heater/
   switch/number writes.
3. Safety rails: validate every setpoint against device-reported min/max; refuse out-of-range.

If the spike shows the write API is gnarlier than expected, ship **read-only v1** and treat control as
v1.1.

## Build sequencing

1. Scaffold (repo cleanup, `.tool-versions`, `pyproject.toml`, `manifest.json`, `hacs.json`).
2. Client read path + models + unit tests (golden fixture = real captured payload).
3. Config flow + coordinator + `__init__` — first read-only entity (outdoor temp) live in HA = walking skeleton.
4. Remaining read-only entities (sensors, binary_sensors, zone temp sensors).
5. Control spike (verify one write against the real pump).
6. Control entities (climate, water_heater, switch, number) on top of the verified spike.

## Testing

- **Client unit tests** (pure Python, HTTP mocked via `aioresponses`, dev-only dep):
  CFC key (known vector, cross-checked vs JS), PKCE S256 challenge, login-form parsing, **status
  parsing → models using the real captured payload**, control payload builders, token refresh.
- **HA-layer tests** (`pytest-homeassistant-custom-component`): config-flow happy path + auth-fail,
  coordinator/entity smoke test. Confidence without gold-plating.
- **Live smoke test** (`tests/live_smoke.py`, manual, not CI): hits the real cloud with `.env`
  creds — read path, then the control spike with read-back. Successor to `index.js`.
- **Tooling:** `ruff` (HA standard), `.tool-versions` pins Python. CI (hassfest + ruff + pytest GH
  Action) noted as an optional shareability nicety — deferred.

## Out of scope (v1)

Energy/cost consumption history + Energy-dashboard wiring; quiet/powerful controls; multi-account;
CI/CD; HACS publication (layout ready, but not submitted).
