# Panasonic Aquarea (energy) Implementation Plan — Plan 3 (v0.3.0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add daily energy-consumption sensors (Heating / Cooling / Hot water / Total kWh) for the HA Energy dashboard.

**Architecture:** A new client method fetches today's hourly consumption buckets and sums them per category. A second `DataUpdateCoordinator` (30-min interval) drives 4 `total_increasing` energy sensors that accumulate over the day and reset at midnight — exactly what HA's Energy dashboard consumes. Reuses the existing client/session/token.

**Tech stack:** unchanged. Live-confirmed endpoint.

## Confirmed API (live spike)

`POST https://accsmart.panasonic.com/remote/v1/app/common/transfer` (our signed headers, 401→refresh→retry via the existing `_transfer`):
```json
{"apiName":"/remote/v1/api/consumption","requestMethod":"POST",
 "bodyParam":{"gwid":"<deviceGuid>","dataMode":0,"date":"YYYYMMDD","osTimezone":"+02:00"}}
```
- `dataMode`: 0 = hourly buckets for the day (24), 1 = daily for the month, 2 = monthly for the year.
- Response top-level `historyDataList`: array of buckets, each `{dataTime, heatConsumption, coolConsumption, tankConsumption, heatCost, coolCost, tankCost, roomTemp, outdoorTemp}`. Values in **kWh**. No total field (sum client-side). Closed buckets — finest granularity is hourly; current in-progress hour is partial/absent.
- gwid = the short `deviceGuid` (same as status/control).

## File Structure
```
custom_components/panasonic_aquarea/
├── api/client.py     # MODIFY: add get_energy_today()
├── api/models.py     # MODIFY: add EnergyTotals
├── coordinator.py    # MODIFY: add PanasonicAquareaEnergyCoordinator
├── __init__.py       # MODIFY: build + first-refresh energy coordinator; expose on runtime_data
├── sensor.py         # MODIFY: add 4 energy sensors (tied to the energy coordinator)
└── translations/en.json  # MODIFY: 4 energy entity names
tests/
├── api/test_client_energy.py  # CREATE
└── test_energy_sensor.py      # CREATE
```

---

## Task E1: client `get_energy_today` + `EnergyTotals` model (TDD)

**Files:** `api/models.py`, `api/client.py`, `tests/api/test_client_energy.py`.

- [ ] **Step 1: model** — append to `models.py`:
```python
@dataclass(frozen=True)
class EnergyTotals:
    """Today's consumption (kWh) summed across hourly buckets."""
    heating: float
    cooling: float
    hot_water: float
    total: float

    @classmethod
    def from_consumption(cls, payload: dict) -> "EnergyTotals":
        buckets = payload.get("historyDataList", []) if isinstance(payload, dict) else []
        heating = sum(b.get("heatConsumption") or 0 for b in buckets)
        cooling = sum(b.get("coolConsumption") or 0 for b in buckets)
        hot_water = sum(b.get("tankConsumption") or 0 for b in buckets)
        return cls(
            heating=round(heating, 3),
            cooling=round(cooling, 3),
            hot_water=round(hot_water, 3),
            total=round(heating + cooling + hot_water, 3),
        )
```

- [ ] **Step 2: failing test** `tests/api/test_client_energy.py`:
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


def _last_body(m):
    for (method, url), calls in m.requests.items():
        if method == "POST" and str(url).endswith("/remote/v1/app/common/transfer"):
            return calls[-1].kwargs["json"]
    raise AssertionError("no transfer POST")


async def test_get_energy_today_sums_buckets(client):
    payload = {"historyDataList": [
        {"dataTime": "20260529 09", "heatConsumption": 0, "coolConsumption": 0.05, "tankConsumption": 0},
        {"dataTime": "20260529 10", "heatConsumption": 0.1, "coolConsumption": 0.07, "tankConsumption": 0.2},
    ]}
    with aioresponses() as m:
        m.post(f"{c.API_BASE}/remote/v1/app/common/transfer", status=200, payload=payload)
        totals = await client.get_energy_today("HP1", "20260529", "+02:00")
        body = _last_body(m)
    assert body["bodyParam"] == {"gwid": "HP1", "dataMode": 0, "date": "20260529", "osTimezone": "+02:00"}
    assert body["apiName"] == "/remote/v1/api/consumption"
    assert totals.heating == 0.1
    assert totals.cooling == 0.12
    assert totals.hot_water == 0.2
    assert totals.total == 0.42
```

- [ ] **Step 3:** run, confirm FAIL.

- [ ] **Step 4: implement** — add `EnergyTotals` to the `from .models import ...` line in `client.py`, then append:
```python
    async def get_energy_today(self, gwid: str, date: str, tz_offset: str) -> "EnergyTotals":
        """Fetch today's consumption (hourly buckets) and return summed kWh totals.

        date: 'YYYYMMDD' (device-local). tz_offset: e.g. '+02:00'.
        """
        data = await self._transfer(
            {
                "apiName": "/remote/v1/api/consumption",
                "requestMethod": "POST",
                "bodyParam": {"gwid": gwid, "dataMode": 0, "date": date, "osTimezone": tz_offset},
            },
            allow_refresh=True,
        )
        return EnergyTotals.from_consumption(data)
```

- [ ] **Step 5:** run, confirm PASS. Full suite + `ruff check .`.
- [ ] **Step 6: commit** `feat: add energy consumption fetch`.

---

## Task E2: energy coordinator + entry wiring

**Files:** `coordinator.py`, `__init__.py`.

- [ ] **Step 1: add the energy coordinator** to `coordinator.py`:
```python
from homeassistant.util import dt as dt_util  # add to imports
from .api.models import AquareaDevice, EnergyTotals  # extend existing models import


class PanasonicAquareaEnergyCoordinator(DataUpdateCoordinator[dict[str, EnergyTotals]]):
    """Polls today's consumption for each device every 30 minutes."""

    def __init__(self, hass: HomeAssistant, client, guids: list[str]) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_energy", update_interval=timedelta(minutes=30)
        )
        self._client = client
        self._guids = guids

    @staticmethod
    def _today_and_offset() -> tuple[str, str]:
        now = dt_util.now()  # HA-local time
        date = now.strftime("%Y%m%d")
        raw = now.strftime("%z") or "+0000"  # e.g. +0200
        offset = f"{raw[:3]}:{raw[3:]}"  # -> +02:00
        return date, offset

    async def _async_update_data(self) -> dict[str, EnergyTotals]:
        date, offset = self._today_and_offset()
        result: dict[str, EnergyTotals] = {}
        for guid in self._guids:
            try:
                result[guid] = await self._client.get_energy_today(guid, date, offset)
            except (ApiError, AuthError) as err:
                _LOGGER.warning("Energy update failed for %s: %s", guid, err)
        return result
```
Add `from datetime import timedelta` if not present, and ensure `ApiError, AuthError` are imported (they are, from `.api.client`).

- [ ] **Step 2: wire into `__init__.py`** `async_setup_entry` (after the main coordinator's first refresh):
```python
    coordinator = PanasonicAquareaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    energy_coordinator = PanasonicAquareaEnergyCoordinator(
        hass, coordinator.client, list(coordinator.data)
    )
    await energy_coordinator.async_config_entry_first_refresh()
    coordinator.energy = energy_coordinator

    entry.runtime_data = coordinator
```
Add `from .coordinator import PanasonicAquareaCoordinator, PanasonicAquareaEnergyCoordinator`. Declare the attribute on the main coordinator: in `PanasonicAquareaCoordinator.__init__`, add `self.energy: PanasonicAquareaEnergyCoordinator | None = None` (use a forward ref / `Any` to avoid a circular type issue — `self.energy = None` with a comment is fine).

- [ ] **Step 3:** `python -c "import ..."`/`pytest -q` (existing tests still pass — energy sensors come next), `ruff check .`. Commit `feat: add energy coordinator`.

---

## Task E3: energy sensors (TDD)

**Files:** `sensor.py`, `translations/en.json`, `tests/test_energy_sensor.py`.

- [ ] **Step 1: failing test** `tests/test_energy_sensor.py`:
```python
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.panasonic_aquarea.api.models import AquareaDevice, EnergyTotals
from custom_components.panasonic_aquarea.const import DOMAIN


async def _setup(hass, aquarea_status):
    device = AquareaDevice.from_status("HP1", aquarea_status)
    totals = EnergyTotals(heating=0.0, cooling=2.63, hot_water=0.0, total=2.63)
    entry = MockConfigEntry(
        domain=DOMAIN, data={"username": "u", "password": "p", "refresh_token": "r"}, unique_id="u"
    )
    entry.add_to_hass(hass)
    with patch("custom_components.panasonic_aquarea.coordinator.PanasonicCloudClient") as cls:
        client = cls.return_value
        client.ensure_session = AsyncMock()
        client.get_devices = AsyncMock(return_value=[("HP1", "Warmtepomp")])
        client.get_status = AsyncMock(return_value=device)
        client.get_energy_today = AsyncMock(return_value=totals)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_energy_sensors(hass: HomeAssistant, aquarea_status):
    await _setup(hass, aquarea_status)
    cool = hass.states.get("sensor.warmtepomp_cooling_energy_today")
    assert cool is not None
    assert float(cool.state) == 2.63
    assert cool.attributes["device_class"] == "energy"
    assert cool.attributes["state_class"] == "total_increasing"
    assert cool.attributes["unit_of_measurement"] == "kWh"
    assert float(hass.states.get("sensor.warmtepomp_total_energy_today").state) == 2.63
```

- [ ] **Step 2:** run, confirm FAIL.

- [ ] **Step 3: implement** — in `sensor.py`, add an energy-sensor description list + entities and append them in `async_setup_entry` (they bind to `coordinator.energy`, a DIFFERENT coordinator). Add imports `UnitOfEnergy`, and reuse `AquareaEntity`? No — `AquareaEntity` binds the main coordinator. Create a dedicated base in `sensor.py`:
```python
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfTemperature
from homeassistant.helpers.device_info import DeviceInfo  # if not already imported via entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN

_ENERGY = (
    ("heating", "Heating energy today", lambda t: t.heating),
    ("cooling", "Cooling energy today", lambda t: t.cooling),
    ("hot_water", "Hot water energy today", lambda t: t.hot_water),
    ("total", "Total energy today", lambda t: t.total),
)


class AquareaEnergySensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, energy_coordinator, guid, key, name, value_fn):
        super().__init__(energy_coordinator)
        self._guid = guid
        self._value_fn = value_fn
        self._attr_unique_id = f"{guid}_energy_{key}"
        self._attr_translation_key = f"energy_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, guid)})

    @property
    def native_value(self):
        totals = self.coordinator.data.get(self._guid)
        return self._value_fn(totals) if totals else None
```
Then in `async_setup_entry`, after adding the existing status sensors:
```python
    energy = coordinator.energy
    if energy is not None:
        for guid in energy.data:
            entities += [
                AquareaEnergySensor(energy, guid, key, name, fn) for key, name, fn in _ENERGY
            ]
```
(Note: entity_id slug derives from the translated name → `sensor.warmtepomp_cooling_energy_today` etc. The translation `name` strings below produce those slugs.)

- [ ] **Step 4:** translations — under `entity.sensor` in `en.json` add:
```json
"energy_heating": {"name": "Heating energy today"},
"energy_cooling": {"name": "Cooling energy today"},
"energy_hot_water": {"name": "Hot water energy today"},
"energy_total": {"name": "Total energy today"}
```

- [ ] **Step 5:** run, confirm PASS. If the generated entity_ids differ from the test's expectation, inspect `hass.states.async_entity_ids("sensor")` and align the translation names so they slug to `*_cooling_energy_today` / `*_total_energy_today` (don't weaken the value assertions). Full suite + `ruff check .`.
- [ ] **Step 6: commit** `feat: add daily energy sensors`.

---

## Task E4: live verify + release

- [ ] **Step 1 (controller, with user):** confirm the energy sensors populate live (cooling ≈ today's kWh) once installed on the ODroid; add them under Settings → Energy.
- [ ] **Step 2:** bump `manifest.json` to `0.3.0`; update README (energy section). Commit, merge to master, tag/release `v0.3.0`.

---

## Self-Review
- Consumption fetch via the proven transfer proxy + 401 retry → E1. ✓
- Sum heat/cool/tank kWh → `EnergyTotals` → E1. ✓
- Separate 30-min energy coordinator computing device-local date + tz offset → E2. ✓
- 4 `total_increasing` energy sensors grouped under the device → E3. ✓
- Energy-dashboard ready (device_class energy, kWh, total_increasing) → E3. ✓
- Scope: kWh breakdown only (no cost sensors) per the chosen scope. ✓

**Placeholders:** none. **Type consistency:** `EnergyTotals(heating/cooling/hot_water/total)` defined in E1, used in E2/E3; `get_energy_today(gwid, date, tz_offset)` defined E1, called E2; `coordinator.energy` set E2, read E3.

## Notes
- The energy coordinator reuses the main coordinator's authenticated client (shared token/session) — no second login.
- `total_increasing` handles the midnight reset (value returns to ~0); HA attributes the day correctly.
- `tests/energy_smoke.py` is the manual live checker (kept, like the other smoke scripts).
