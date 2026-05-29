# Panasonic Aquarea (control) Implementation Plan — Plan 2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add write/control to the existing read-only `panasonic_aquarea` integration: device operation-mode `select`, per-zone `climate`/`number`/`switch`, tank `water_heater`, and a force-DHW `switch` — and remove the always-unknown `water_pressure` sensor.

**Architecture:** Control reuses the proven Comfort Cloud `transfer` proxy: `POST /remote/v1/app/common/transfer` with `{apiName: "/remote/v1/api/devices", requestMethod: "POST", bodyParam: {gwid, ...}}`. New client write methods sit alongside the existing read methods in `api/client.py`. Entities call them and then request a coordinator refresh. **Operation mode is device-wide**, so it's a single `select`; zone climates are on/off + setpoint only.

**Tech Stack:** Same as Plan 1 (Python 3.13, HA custom integration, stdlib + aiohttp; pytest/aioresponses/pytest-homeassistant-custom-component/ruff).

**Builds on:** the merged read-only integration (commit history through `091935a`). Spec: `docs/superpowers/specs/2026-05-29-panasonic-aquarea-ha-integration-design.md`. Control payloads were reversed from `aioaquarea`'s `device_control.py`.

---

## ⚠️ Risk & the spike

Writes mutate the real heat pump. The one unknown is **`gwid` for writes**: reads work with the short `deviceGuid` (e.g. `B218954411`); `aioaquarea` references a `long_id` for writes. **Phase A is a live spike** that resolves this with a safe no-op write before any control code is built. All later tasks assume the spike's finding (default: the short `deviceGuid` works for writes too, consistent with reads). If the spike shows a distinct `long_id` is required, Task B1 captures it from the device list and every `set_*` call uses it instead — a noted, contained adjustment.

Safety rules for all control code:
- Validate every setpoint against the device's reported min/max; refuse out-of-range.
- After a successful write, call `await coordinator.async_request_refresh()` so state reflects reality (no blind optimistic state).

---

## File Structure

```
custom_components/panasonic_aquarea/
├── api/client.py        # MODIFY: add write methods + capture device id for writes
├── api/models.py        # MODIFY: add operation_status/tank on-off already present; add UpdateOperationMode enum + write-id field
├── coordinator.py       # MODIFY: expose write-id per guid (from device list)
├── __init__.py          # MODIFY: add CLIMATE, WATER_HEATER, SWITCH, SELECT, NUMBER platforms
├── sensor.py            # MODIFY: remove water_pressure sensor
├── climate.py           # CREATE: absolute-zone climate
├── water_heater.py      # CREATE: tank
├── number.py            # CREATE: offset-zone offset
├── switch.py            # CREATE: offset-zone on/off + force DHW
├── select.py            # CREATE: device operation mode
└── translations/en.json # MODIFY: add new entity names; drop water_pressure
tests/
├── api/test_client_control.py   # CREATE
├── test_climate.py / test_select.py / test_water_heater.py  # CREATE
└── control_smoke.py             # CREATE (manual, like live_smoke)
```

---

## Phase A — Live write spike

### Task A1: Confirm the write path with a safe no-op write

**Files:** Create `tests/control_smoke.py` (manual; not CI).

- [ ] **Step 1: Write the spike script** `tests/control_smoke.py`

```python
"""Manual control spike — verifies a SAFE no-op write round-trips. NOT in CI.

It reads the tank's current target, writes that SAME value back (no behaviour
change), and reads it back. Also reports the raw device-list entry so we can see
whether a separate long id exists. Run with care.

Usage:
    PANASONIC_USERNAME=... PANASONIC_PASSWORD=... python tests/control_smoke.py
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp  # noqa: E402

from custom_components.panasonic_aquarea.api import const  # noqa: E402
from custom_components.panasonic_aquarea.api.client import PanasonicCloudClient  # noqa: E402


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        c = PanasonicCloudClient(
            session, os.environ["PANASONIC_USERNAME"], os.environ["PANASONIC_PASSWORD"]
        )
        await c.login()

        # Raw device list — inspect for any long id vs the short deviceGuid
        async with session.get(
            f"{const.API_BASE}/device/group/", headers=c._headers(client_id=True)
        ) as resp:
            groups = await resp.json()
        dev = groups["groupList"][0]["deviceList"][0]
        print("device-list entry keys:", list(dev.keys()))
        print("deviceGuid:", dev.get("deviceGuid"))
        guid = dev["deviceGuid"]

        before = await c.get_status(guid)
        target = before.tank.target_temperature
        print(f"tank target before: {target}")

        # SAFE no-op write: set the tank target to its CURRENT value
        body = {
            "apiName": "/remote/v1/api/devices",
            "requestMethod": "POST",
            "bodyParam": {"gwid": guid, "tankStatus": {"heatSet": target}},
        }
        async with session.post(
            f"{const.API_BASE}/remote/v1/app/common/transfer",
            json=body,
            headers=c._headers(client_id=True),
        ) as resp:
            print("write HTTP:", resp.status)
            print("write body:", (await resp.text())[:300])

        after = await c.get_status(guid)
        print(f"tank target after: {after.tank.target_temperature}")
        print("RESULT: deviceGuid works for writes" if resp.status == 200 else "RESULT: needs long_id")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: STOP — hand to the controller/human to run live**

This step sends a real (no-op) write to the heat pump. Do NOT run it from an unattended subagent. The controller runs it with the user's go-ahead:
```bash
PANASONIC_USERNAME="$(grep '^USERNAME=' .env | cut -d= -f2-)" \
PANASONIC_PASSWORD="$(grep '^PASSWORD=' .env | cut -d= -f2-)" \
PYTHONPATH=. python tests/control_smoke.py
```
Record: does `deviceGuid` work for writes (HTTP 200, target unchanged)? Are there extra id fields in the device-list entry? **This finding determines whether Task B1 uses `deviceGuid` (default) or captures a separate `long_id`.**

- [ ] **Step 3: Commit the spike script**
```bash
git add tests/control_smoke.py
git commit -m "test: add control write spike"
```

---

## Phase B — Client write methods (TDD)

> Default assumption (pending Task A1): the short `deviceGuid` is the `gwid` for writes. If A1 proved a separate `long_id` is needed, in Task B1 capture it in `get_devices` and pass it everywhere a write `gwid` is used; the method signatures below stay the same (the caller just passes the right id string).

### Task B1: Operation-mode enum + write transport

**Files:** Modify `api/models.py`, `api/client.py`. Test: `tests/api/test_client_control.py`.

- [ ] **Step 1: Add the write-mode enum to `models.py`**

Append to `models.py`:
```python
class UpdateOperationMode(IntEnum):
    """Values accepted by the operationMode write (distinct from read OperationMode)."""
    OFF = 0
    HEAT = 1
    COOL = 2
    AUTO = 3
```
(If a value differs once confirmed live, adjust here — but HEAT=1/COOL=2/AUTO=3/OFF=0 matches the read `OperationMode` and `aioaquarea`.)

- [ ] **Step 2: Write the failing test** `tests/api/test_client_control.py`

```python
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


def _last_body(mocked):
    # aioresponses records requests; return the json body of the last transfer POST
    key = ("POST", f"{c.API_BASE}/remote/v1/app/common/transfer")
    # fall back to matching by URL suffix across recorded calls
    for (method, url), calls in mocked.requests.items():
        if method == "POST" and str(url).endswith("/remote/v1/app/common/transfer"):
            return calls[-1].kwargs["json"]
    raise AssertionError("no transfer POST recorded")


async def test_set_tank_temperature_payload(client):
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload={"result": 0})
        await client.set_tank_temperature("HP1", 50)
        body = _last_body(m)
    assert body["apiName"] == "/remote/v1/api/devices"
    assert body["requestMethod"] == "POST"
    assert body["bodyParam"] == {"gwid": "HP1", "tankStatus": {"heatSet": 50}}
```

- [ ] **Step 3: Run, confirm FAIL** — `pytest tests/api/test_client_control.py -v`

- [ ] **Step 4: Implement the write transport + first method in `client.py`**

Append to `PanasonicCloudClient`:
```python
    async def _write(self, body_param: dict) -> dict:
        """POST a control write through the transfer proxy (retries once on 401)."""
        envelope = {
            "apiName": "/remote/v1/api/devices",
            "requestMethod": "POST",
            "bodyParam": body_param,
        }
        return await self._transfer(envelope, allow_refresh=True)

    async def set_tank_temperature(self, gwid: str, temperature: int) -> None:
        await self._write({"gwid": gwid, "tankStatus": {"heatSet": temperature}})
```
Note: `_transfer` (added in Plan 1) returns parsed JSON and already handles the 401-retry. A write response like `{"result": 0}` has no `"status"` key — that's fine here because `_write` does NOT do the `"status" not in data` check (that check lives only in `get_status`). Confirm `_transfer` itself does not require `"status"` (it doesn't — only `get_status` does).

- [ ] **Step 5: Run, confirm PASS.** Then full suite + `ruff check .`.

- [ ] **Step 6: Commit**
```bash
git add custom_components/panasonic_aquarea/api/models.py custom_components/panasonic_aquarea/api/client.py tests/api/test_client_control.py
git commit -m "feat: add control write transport and tank setpoint"
```

### Task B2: Remaining write methods

**Files:** Modify `api/client.py`. Test: `tests/api/test_client_control.py`.

- [ ] **Step 1: Append failing tests** (one per payload; verify exact bodyParam):

```python
async def test_set_zone_heat_temperature_payload(client):
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload={"result": 0})
        await client.set_zone_temperature("HP1", 2, 21, cooling=False)
        body = _last_body(m)
    assert body["bodyParam"] == {"gwid": "HP1", "zoneStatus": [{"zoneId": 2, "heatSet": 21}]}


async def test_set_zone_cool_temperature_payload(client):
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload={"result": 0})
        await client.set_zone_temperature("HP1", 2, 24, cooling=True)
        body = _last_body(m)
    assert body["bodyParam"] == {"gwid": "HP1", "zoneStatus": [{"zoneId": 2, "coolSet": 24}]}


async def test_set_zone_operation_payload(client):
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload={"result": 0})
        await client.set_zone_operation("HP1", 1, on=False)
        body = _last_body(m)
    assert body["bodyParam"] == {"gwid": "HP1", "zoneStatus": [{"zoneId": 1, "operationStatus": 0}]}


async def test_set_tank_operation_payload(client):
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload={"result": 0})
        await client.set_tank_operation("HP1", on=True)
        body = _last_body(m)
    assert body["bodyParam"] == {"gwid": "HP1", "tankStatus": {"operationStatus": 1}}


async def test_set_force_dhw_payload(client):
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload={"result": 0})
        await client.set_force_dhw("HP1", on=True)
        body = _last_body(m)
    assert body["bodyParam"] == {"gwid": "HP1", "forceDHW": 1}


async def test_set_operation_mode_payload(client):
    from custom_components.panasonic_aquarea.api.models import UpdateOperationMode
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload={"result": 0})
        await client.set_operation_mode("HP1", UpdateOperationMode.HEAT)
        body = _last_body(m)
    assert body["bodyParam"] == {"gwid": "HP1", "operationMode": 1}
```

- [ ] **Step 2: Run, confirm FAIL.**

- [ ] **Step 3: Implement** (append to `PanasonicCloudClient`):
```python
    async def set_zone_temperature(
        self, gwid: str, zone_id: int, temperature: int, *, cooling: bool
    ) -> None:
        key = "coolSet" if cooling else "heatSet"
        await self._write({"gwid": gwid, "zoneStatus": [{"zoneId": zone_id, key: temperature}]})

    async def set_zone_operation(self, gwid: str, zone_id: int, *, on: bool) -> None:
        await self._write(
            {"gwid": gwid, "zoneStatus": [{"zoneId": zone_id, "operationStatus": int(on)}]}
        )

    async def set_tank_operation(self, gwid: str, *, on: bool) -> None:
        await self._write({"gwid": gwid, "tankStatus": {"operationStatus": int(on)}})

    async def set_force_dhw(self, gwid: str, *, on: bool) -> None:
        await self._write({"gwid": gwid, "forceDHW": int(on)})

    async def set_operation_mode(self, gwid: str, mode: "UpdateOperationMode") -> None:
        await self._write({"gwid": gwid, "operationMode": int(mode)})
```
Add `UpdateOperationMode` to the `from .models import ...` line. Note: we send `operationMode` alone (simplest payload). **If the spike/live test shows the API rejects a mode-only write and requires the full bundle** (operationStatus + zoneStatus + tankStatus, as `aioaquarea` sends), change `set_operation_mode` to accept the current zone/tank operation statuses and include them — and the `select` entity (Task C5) passes them from coordinator data. Keep the mode-only version unless live testing forces the bundle.

- [ ] **Step 4: Run, confirm PASS.** Full suite + `ruff check .`.

- [ ] **Step 5: Commit**
```bash
git add custom_components/panasonic_aquarea/api/client.py tests/api/test_client_control.py
git commit -m "feat: add zone/tank/force-dhw/mode write methods"
```

### Task B3: Expose the write-id per device in the coordinator

**Files:** Modify `api/client.py` (`get_devices`), `coordinator.py`. Test: extend `tests/api/test_client.py`.

- [ ] **Step 1: Failing test** — `get_devices` returns the write id alongside guid/name.

Append to `tests/api/test_client.py`:
```python
async def test_get_devices_includes_write_id(session):
    client = PanasonicCloudClient(session, "user", "pass")
    client._token = "TKN"
    client._client_id = "CID"
    with aioresponses() as m:
        m.get(
            f"{c.API_BASE}/device/group/",
            status=200,
            payload={"groupList": [{"deviceList": [
                {"deviceGuid": "HP1", "deviceType": "2", "deviceName": "Warmtepomp"},
            ]}]},
        )
        devices = await client.get_devices()
    # (guid, write_id, name); write_id defaults to guid unless A1 found a separate long id
    assert devices == [("HP1", "HP1", "Warmtepomp")]
```

- [ ] **Step 2: Run, confirm FAIL** (current returns 2-tuples).

- [ ] **Step 3: Implement.** Change `get_devices` to return `(guid, write_id, name)`. Default `write_id = deviceGuid`. **If A1 found a separate long id field (e.g. `"deviceModuleNumber"` or similar), use `dev.get("<that field>", dev["deviceGuid"])` as `write_id`.** Update the existing `test_get_devices_returns_aquarea_only` assertion to the 3-tuple form.

In `coordinator.py`: store `self._write_ids: dict[str, str] = {}`; in `_async_setup`, populate from `get_devices` (`{guid: write_id}` and `self._guids = [guid...]`). Add a helper:
```python
    def write_id(self, guid: str) -> str:
        return self._write_ids[guid]
```

- [ ] **Step 4: Run, confirm PASS** (update any other test that called the old 2-tuple `get_devices`). Full suite + `ruff check .`.

- [ ] **Step 5: Commit**
```bash
git add custom_components/panasonic_aquarea/api/client.py custom_components/panasonic_aquarea/coordinator.py tests/api/test_client.py
git commit -m "feat: expose per-device write id"
```

---

## Phase C — Control entities

> All entities follow the same write pattern: validate → `await self.coordinator.client.set_*(self.coordinator.write_id(self._guid), ...)` → `await self.coordinator.async_request_refresh()`.

### Task C1: Remove the water_pressure sensor

**Files:** Modify `sensor.py`, `translations/en.json`.

- [ ] **Step 1:** In `sensor.py`, delete the `AquareaSensorDescription(key="water_pressure", ...)` entry from `SENSORS`. Remove the now-unused `UnitOfPressure` import if nothing else uses it.
- [ ] **Step 2:** In `translations/en.json`, remove the `"water_pressure"` entry under `entity.sensor`.
- [ ] **Step 3:** Update `tests/test_init.py` if it asserted on water pressure (it doesn't — it checks outdoor temp; verify and leave). Run `pytest -q` + `ruff check .`.
- [ ] **Step 4: Commit**
```bash
git add custom_components/panasonic_aquarea/sensor.py custom_components/panasonic_aquarea/translations/en.json
git commit -m "feat: drop always-unknown water pressure sensor"
```

### Task C2: Tank water_heater

**Files:** Create `water_heater.py`. Modify `__init__.py` (add `Platform.WATER_HEATER`), `translations/en.json`. Test: `tests/test_water_heater.py`.

- [ ] **Step 1: Failing test** `tests/test_water_heater.py` — set up the entry (reuse the `test_init.py` patching pattern: patch `coordinator.PanasonicCloudClient`, `ensure_session`/`get_devices` returning the 3-tuple `[("HP1","HP1","Warmtepomp")]`/`get_status` returning the fixture device), then:
```python
    state = hass.states.get("water_heater.warmtepomp_tank")
    assert state is not None
    assert state.attributes["temperature"] == 52
    assert state.attributes["current_temperature"] == 46
```
Then drive a service call and assert the client method was awaited:
```python
    client.set_tank_temperature = AsyncMock()
    await hass.services.async_call(
        "water_heater", "set_temperature",
        {"entity_id": "water_heater.warmtepomp_tank", "temperature": 50}, blocking=True,
    )
    client.set_tank_temperature.assert_awaited_once_with("HP1", 50)
```

- [ ] **Step 2: Run, confirm FAIL.**

- [ ] **Step 3: Implement `water_heater.py`:**
```python
"""Water heater (DHW tank) platform for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.components.water_heater import (
    STATE_OFF,
    STATE_PERFORMANCE,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PanasonicAquareaConfigEntry
from .entity import AquareaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PanasonicAquareaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        AquareaTank(coordinator, guid)
        for guid, device in coordinator.data.items()
        if device.tank is not None
    )


class AquareaTank(AquareaEntity, WaterHeaterEntity):
    _attr_translation_key = "tank"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_operation_list = [STATE_OFF, STATE_PERFORMANCE]
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
    )

    def __init__(self, coordinator, guid) -> None:
        super().__init__(coordinator, guid)
        self._attr_unique_id = f"{guid}_tank"

    @property
    def current_temperature(self) -> int:
        return self.device.tank.current_temperature

    @property
    def target_temperature(self) -> int:
        return self.device.tank.target_temperature

    @property
    def min_temp(self) -> int:
        return self.device.tank.heat_min

    @property
    def max_temp(self) -> int:
        return self.device.tank.heat_max

    @property
    def current_operation(self) -> str:
        return STATE_PERFORMANCE if self.device.tank.on else STATE_OFF

    async def async_set_temperature(self, **kwargs) -> None:
        temp = int(kwargs[ATTR_TEMPERATURE])
        tank = self.device.tank
        if not tank.heat_min <= temp <= tank.heat_max:
            raise ValueError(f"tank temperature {temp} out of range {tank.heat_min}-{tank.heat_max}")
        await self.coordinator.client.set_tank_temperature(
            self.coordinator.write_id(self._guid), temp
        )
        await self.coordinator.async_request_refresh()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        await self.coordinator.client.set_tank_operation(
            self.coordinator.write_id(self._guid), on=operation_mode == STATE_PERFORMANCE
        )
        await self.coordinator.async_request_refresh()
```

- [ ] **Step 4:** Add `Platform.WATER_HEATER` to `PLATFORMS` in `__init__.py`. Add `"water_heater": {"tank": {"name": "Tank"}}` under `entity` in `en.json`.
- [ ] **Step 5: Run, confirm PASS.** Full suite + `ruff check .`.
- [ ] **Step 6: Commit**
```bash
git add custom_components/panasonic_aquarea/water_heater.py custom_components/panasonic_aquarea/__init__.py custom_components/panasonic_aquarea/translations/en.json tests/test_water_heater.py
git commit -m "feat: add tank water heater control"
```

### Task C3: Absolute-zone climate

**Files:** Create `climate.py`. Modify `__init__.py` (`Platform.CLIMATE`), `en.json`. Test: `tests/test_climate.py`.

- [ ] **Step 1: Failing test** `tests/test_climate.py` (same entry-setup pattern). Assert the absolute zone (Beneden) becomes a climate entity and the offset zone (Boven) does NOT:
```python
    assert hass.states.get("climate.warmtepomp_beneden") is not None
    assert hass.states.get("climate.warmtepomp_boven") is None
    state = hass.states.get("climate.warmtepomp_beneden")
    assert state.attributes["current_temperature"] == 24
    assert state.attributes["temperature"] == 20
```
Then a `set_temperature` service call asserts `client.set_zone_temperature` awaited with `("HP1", 2, 22, cooling=...)` (cooling derived from device mode COOL in the fixture → cooling=True, and the value clamped to range).

- [ ] **Step 2: Run, confirm FAIL.**

- [ ] **Step 3: Implement `climate.py`:**
```python
"""Climate platform (absolute-temperature zones) for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PanasonicAquareaConfigEntry
from .api.models import OperationMode, ZoneMode
from .entity import AquareaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PanasonicAquareaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities = []
    for guid, device in coordinator.data.items():
        for zone in device.zones:
            if zone.mode is ZoneMode.ABSOLUTE:
                entities.append(AquareaZoneClimate(coordinator, guid, zone.zone_id))
    async_add_entities(entities)


class AquareaZoneClimate(AquareaEntity, ClimateEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator, guid, zone_id: int) -> None:
        super().__init__(coordinator, guid)
        self._zone_id = zone_id
        self._attr_unique_id = f"{guid}_zone{zone_id}_climate"
        self._attr_translation_key = "zone"
        self._attr_translation_placeholders = {"zone": self._zone().name}

    def _zone(self):
        return next(z for z in self.device.zones if z.zone_id == self._zone_id)

    @property
    def _cooling(self) -> bool:
        return self.device.operation_mode is OperationMode.COOL

    @property
    def current_temperature(self) -> int:
        return self._zone().current_temperature

    @property
    def target_temperature(self) -> int:
        z = self._zone()
        return z.cool_setpoint if self._cooling else z.heat_setpoint

    @property
    def min_temp(self) -> int:
        z = self._zone()
        return z.cool_min if self._cooling else z.heat_min

    @property
    def max_temp(self) -> int:
        z = self._zone()
        return z.cool_max if self._cooling else z.heat_max

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT_COOL if self._zone().on else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        if not self._zone().on:
            return HVACAction.OFF
        return HVACAction.COOLING if self._cooling else HVACAction.HEATING

    async def async_set_temperature(self, **kwargs) -> None:
        temp = int(kwargs[ATTR_TEMPERATURE])
        if not self.min_temp <= temp <= self.max_temp:
            raise ValueError(f"temperature {temp} out of range {self.min_temp}-{self.max_temp}")
        await self.coordinator.client.set_zone_temperature(
            self.coordinator.write_id(self._guid), self._zone_id, temp, cooling=self._cooling
        )
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.coordinator.client.set_zone_operation(
            self.coordinator.write_id(self._guid), self._zone_id, on=hvac_mode != HVACMode.OFF
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT_COOL)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
```

- [ ] **Step 4:** Add `Platform.CLIMATE` to `PLATFORMS`. Add `"climate": {"zone": {"name": "{zone}"}}` under `entity` in `en.json`.
- [ ] **Step 5: Run, confirm PASS.** Full suite + `ruff check .`.
- [ ] **Step 6: Commit**
```bash
git add custom_components/panasonic_aquarea/climate.py custom_components/panasonic_aquarea/__init__.py custom_components/panasonic_aquarea/translations/en.json tests/test_climate.py
git commit -m "feat: add absolute-zone climate control"
```

### Task C4: Offset-zone number + zone on/off switch

**Files:** Create `number.py`, `switch.py`. Modify `__init__.py` (`Platform.NUMBER`, `Platform.SWITCH`), `en.json`. Test: `tests/test_offset_zone.py`.

- [ ] **Step 1: Failing test** `tests/test_offset_zone.py`: assert the offset zone (Boven) produces `number.warmtepomp_boven_offset` (value −5) and `switch.warmtepomp_boven` (off). A `number.set_value` of `2` awaits `client.set_zone_temperature("HP1", 1, 2, cooling=False)` (offset written into heatSet). A `switch.turn_on` awaits `client.set_zone_operation("HP1", 1, on=True)`.

- [ ] **Step 2: Run, confirm FAIL.**

- [ ] **Step 3: Implement `number.py`:**
```python
"""Number platform (offset-mode zone compensation) for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PanasonicAquareaConfigEntry
from .api.models import ZoneMode
from .entity import AquareaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PanasonicAquareaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities = []
    for guid, device in coordinator.data.items():
        for zone in device.zones:
            if zone.mode is ZoneMode.OFFSET:
                entities.append(AquareaZoneOffset(coordinator, guid, zone.zone_id))
    async_add_entities(entities)


class AquareaZoneOffset(AquareaEntity, NumberEntity):
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 1

    def __init__(self, coordinator, guid, zone_id: int) -> None:
        super().__init__(coordinator, guid)
        self._zone_id = zone_id
        self._attr_unique_id = f"{guid}_zone{zone_id}_offset"
        self._attr_translation_key = "zone_offset"
        self._attr_translation_placeholders = {"zone": self._zone().name}

    def _zone(self):
        return next(z for z in self.device.zones if z.zone_id == self._zone_id)

    @property
    def native_min_value(self) -> int:
        return self._zone().heat_min

    @property
    def native_max_value(self) -> int:
        return self._zone().heat_max

    @property
    def native_value(self) -> int:
        return self._zone().heat_setpoint

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.client.set_zone_temperature(
            self.coordinator.write_id(self._guid), self._zone_id, int(value), cooling=False
        )
        await self.coordinator.async_request_refresh()
```

- [ ] **Step 4: Implement `switch.py`** (handles both offset-zone on/off AND force-DHW from Task C6 — but build only the zone switch now; force-DHW added in C6):
```python
"""Switch platform for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PanasonicAquareaConfigEntry
from .api.models import ZoneMode
from .entity import AquareaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PanasonicAquareaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = []
    for guid, device in coordinator.data.items():
        for zone in device.zones:
            if zone.mode is ZoneMode.OFFSET:
                entities.append(AquareaZoneSwitch(coordinator, guid, zone.zone_id))
        entities.append(AquareaForceDHWSwitch(coordinator, guid))
    async_add_entities(entities)


class AquareaZoneSwitch(AquareaEntity, SwitchEntity):
    def __init__(self, coordinator, guid, zone_id: int) -> None:
        super().__init__(coordinator, guid)
        self._zone_id = zone_id
        self._attr_unique_id = f"{guid}_zone{zone_id}_switch"
        self._attr_translation_key = "zone_power"
        self._attr_translation_placeholders = {"zone": self._zone().name}

    def _zone(self):
        return next(z for z in self.device.zones if z.zone_id == self._zone_id)

    @property
    def is_on(self) -> bool:
        return self._zone().on

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.client.set_zone_operation(
            self.coordinator.write_id(self._guid), self._zone_id, on=True
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.client.set_zone_operation(
            self.coordinator.write_id(self._guid), self._zone_id, on=False
        )
        await self.coordinator.async_request_refresh()


class AquareaForceDHWSwitch(AquareaEntity, SwitchEntity):
    _attr_translation_key = "force_dhw"

    def __init__(self, coordinator, guid) -> None:
        super().__init__(coordinator, guid)
        self._attr_unique_id = f"{guid}_force_dhw"

    @property
    def is_on(self) -> bool:
        return self.device.force_dhw

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.client.set_force_dhw(self.coordinator.write_id(self._guid), on=True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.client.set_force_dhw(self.coordinator.write_id(self._guid), on=False)
        await self.coordinator.async_request_refresh()
```
(Force-DHW is included here so SWITCH is built once; its test is added in Task C6.)

- [ ] **Step 5:** Add `Platform.NUMBER` and `Platform.SWITCH` to `PLATFORMS`. Add to `en.json` under `entity`: `"number": {"zone_offset": {"name": "{zone} offset"}}` and `"switch": {"zone_power": {"name": "{zone}"}, "force_dhw": {"name": "Force DHW"}}`.
- [ ] **Step 6: Run, confirm PASS.** Full suite + `ruff check .`.
- [ ] **Step 7: Commit**
```bash
git add custom_components/panasonic_aquarea/number.py custom_components/panasonic_aquarea/switch.py custom_components/panasonic_aquarea/__init__.py custom_components/panasonic_aquarea/translations/en.json tests/test_offset_zone.py
git commit -m "feat: add offset-zone number and zone/force-dhw switches"
```

### Task C5: Device operation-mode select

**Files:** Create `select.py`. Modify `__init__.py` (`Platform.SELECT`), `en.json`. Test: `tests/test_select.py`.

- [ ] **Step 1: Failing test** `tests/test_select.py`: assert `select.warmtepomp_operation_mode` exists with current option `"cool"` (fixture mode=COOL) and options `["off","heat","cool","auto"]`. A `select.select_option` of `"heat"` awaits `client.set_operation_mode("HP1", UpdateOperationMode.HEAT)`.

- [ ] **Step 2: Run, confirm FAIL.**

- [ ] **Step 3: Implement `select.py`:**
```python
"""Select platform (device operation mode) for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PanasonicAquareaConfigEntry
from .api.models import OperationMode, UpdateOperationMode
from .entity import AquareaEntity

_OPTIONS = ["off", "heat", "cool", "auto"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PanasonicAquareaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(AquareaModeSelect(coordinator, guid) for guid in coordinator.data)


class AquareaModeSelect(AquareaEntity, SelectEntity):
    _attr_translation_key = "operation_mode"
    _attr_options = _OPTIONS

    def __init__(self, coordinator, guid) -> None:
        super().__init__(coordinator, guid)
        self._attr_unique_id = f"{guid}_operation_mode_select"

    @property
    def current_option(self) -> str:
        name = self.device.operation_mode.name.lower()
        return name if name in _OPTIONS else "off"

    async def async_select_option(self, option: str) -> None:
        mode = UpdateOperationMode[option.upper()]
        await self.coordinator.client.set_operation_mode(self.coordinator.write_id(self._guid), mode)
        await self.coordinator.async_request_refresh()
```
Note: read `OperationMode` has a `DHW` member that `UpdateOperationMode` lacks; `_OPTIONS` intentionally excludes `dhw` (not a settable whole-unit mode). The `current_option` guard maps any unexpected mode to `"off"`. Import `OperationMode` only if referenced; otherwise drop it from the import to satisfy ruff.

- [ ] **Step 4:** Add `Platform.SELECT` to `PLATFORMS`. Add `"select": {"operation_mode": {"name": "Operation mode"}}` under `entity` in `en.json`. **Also consider removing the read-only `operation_mode` *sensor*** (Task C1's file) since the select now shows mode — OPTIONAL; if you remove it, update `tests/test_init.py` accordingly and the `en.json` sensor block. Recommended: remove the duplicate sensor to avoid two "Operation mode" entities. If removed, do it in this task and note it in the commit.

- [ ] **Step 5: Run, confirm PASS.** Full suite + `ruff check .`.
- [ ] **Step 6: Commit**
```bash
git add custom_components/panasonic_aquarea/select.py custom_components/panasonic_aquarea/__init__.py custom_components/panasonic_aquarea/translations/en.json tests/test_select.py
git commit -m "feat: add device operation-mode select"
```

---

## Phase D — Live verification & release

### Task D1: Control smoke test (live, with consent) + release

- [ ] **Step 1:** Controller runs a real, reversible control round-trip with the user's go-ahead: read tank target, set it +1°C via `client.set_tank_temperature`, refresh + confirm it changed, then restore the original value. (Extend `tests/control_smoke.py` or do it inline.) Do NOT run unattended.
- [ ] **Step 2:** Install the updated integration on the live HA (ODroid) per `NOTES.md`/README, restart, and confirm the new climate/water_heater/select/number/switch entities appear and a setpoint change from the HA UI reaches the pump.
- [ ] **Step 3:** Bump `manifest.json` `version` to `0.2.0`, commit `feat: control support`, tag and release `v0.2.0` (`gh release create v0.2.0`).

---

## Self-Review

**Spec coverage (control portion of the design):**
- Device-wide mode `select` → Task C5. ✓
- Absolute-zone `climate` (on/off + setpoint, action) → Task C3. ✓
- Offset-zone `number` + on/off `switch` → Task C4. ✓
- Tank `water_heater` (+ force-DHW via operation mode) and force-DHW `switch` → Tasks C2, C4. ✓
- Write methods via the proven transfer proxy, with payloads reversed from `aioaquarea` → Tasks B1–B2. ✓
- Per-device write id → Task B3 (with spike-dependent default). ✓
- Safety: range validation + refresh-after-write → all C tasks. ✓
- water_pressure removal → Task C1. ✓
- Write-verification spike before any control entity → Task A1. ✓

**Placeholder scan:** Concrete code in every step. The two genuinely spike-dependent items — write `gwid` (deviceGuid vs long_id) and whether `operationMode` can be written alone vs as a bundle — are explicitly flagged with the default and the exact fallback, not left vague.

**Type consistency:** `set_*` signatures defined in B1–B2 match the calls in C2–C5. `coordinator.write_id(guid)` defined in B3, used in every control entity. `get_devices` 3-tuple change in B3 is propagated to the coordinator and the existing read tests. `UpdateOperationMode` defined in B1, used in B2 and C5.

---

## Notes for the implementer
- Every entity test reuses the `test_init.py` setup pattern (patch `coordinator.PanasonicCloudClient`; `get_devices` now returns 3-tuples). Keep that helper consistent; consider extracting it into `tests/conftest.py` as a fixture if duplication grows.
- Do not send live writes from subagents. The two live steps (A1, D1) are controller-run with user consent.
- If A1 shows the short `deviceGuid` works for writes (expected, since reads use it), B3's `write_id` is just the guid and nothing downstream changes.
