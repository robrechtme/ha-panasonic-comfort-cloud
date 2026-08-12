from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.panasonic_aquarea.api.models import AquareaDevice
from custom_components.panasonic_aquarea.const import DOMAIN


async def _setup(hass, aquarea_status):
    device = AquareaDevice.from_status("HP1", aquarea_status)
    entry = MockConfigEntry(
        domain=DOMAIN, data={"username": "u", "password": "p", "refresh_token": "r"}, unique_id="u"
    )
    entry.add_to_hass(hass)
    with patch("custom_components.panasonic_aquarea.coordinator.PanasonicCloudClient") as cls:
        client = cls.return_value
        client.ensure_session = AsyncMock()
        client.get_devices = AsyncMock(return_value=[("HP1", "Warmtepomp")])
        client.get_status = AsyncMock(return_value=device)
        client.get_energy_today = AsyncMock(return_value=MagicMock())
        client.get_energy_history = AsyncMock(return_value=[])
        client.set_zone_temperature = AsyncMock()
        client.set_operation = AsyncMock()
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, client


async def test_only_absolute_zone_is_climate(hass: HomeAssistant, aquarea_status):
    await _setup(hass, aquarea_status)
    assert hass.states.get("climate.warmtepomp_beneden") is not None
    assert hass.states.get("climate.warmtepomp_boven") is None  # offset zone excluded


async def test_climate_state(hass: HomeAssistant, aquarea_status):
    await _setup(hass, aquarea_status)
    state = hass.states.get("climate.warmtepomp_beneden")
    # device is in COOL mode -> active setpoint is the cool setpoint
    assert state.attributes["current_temperature"] == 24
    assert state.attributes["temperature"] == 22


async def test_climate_reflects_device_mode_and_step(hass, aquarea_status):
    await _setup(hass, aquarea_status)
    state = hass.states.get("climate.warmtepomp_beneden")
    assert state.state == "cool"  # device mode COOL, zone on
    assert state.attributes["target_temp_step"] == 1
    assert state.attributes["current_temperature"] == 24
    assert state.attributes["temperature"] == 22  # cool setpoint in COOL mode


async def test_climate_set_temperature_uses_cool_in_cool_mode(hass: HomeAssistant, aquarea_status):
    _, client = await _setup(hass, aquarea_status)
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": "climate.warmtepomp_beneden", "temperature": 23},
        blocking=True,
    )
    client.set_zone_temperature.assert_awaited_once_with("HP1", 2, 23, cooling=True)


async def test_climate_set_hvac_mode_bundles_mode_zones_and_tank(hass, aquarea_status):
    from custom_components.panasonic_aquarea.api.models import UpdateOperationMode
    _, client = await _setup(hass, aquarea_status)
    await hass.services.async_call(
        "climate", "set_hvac_mode",
        {"entity_id": "climate.warmtepomp_beneden", "hvac_mode": "heat"}, blocking=True,
    )
    # Boven (zone 1) echoed as-is (off), Beneden (zone 2) forced on, tank echoed (on)
    client.set_operation.assert_awaited_once_with(
        "HP1", UpdateOperationMode.HEAT, [(1, False), (2, True)], tank_on=True
    )


async def test_climate_set_hvac_mode_to_current_mode_still_sends_full_bundle(hass, aquarea_status):
    # aquarea_status fixture device is already in Cool - live-verified that a bare
    # mode-only write for the mode the device is already in flips it to Heat, so the
    # full bundle (mode + every zone + tank) must always be sent, never skipped.
    from custom_components.panasonic_aquarea.api.models import UpdateOperationMode
    _, client = await _setup(hass, aquarea_status)
    await hass.services.async_call(
        "climate", "set_hvac_mode",
        {"entity_id": "climate.warmtepomp_beneden", "hvac_mode": "cool"}, blocking=True,
    )
    client.set_operation.assert_awaited_once_with(
        "HP1", UpdateOperationMode.COOL, [(1, False), (2, True)], tank_on=True
    )


async def test_set_hvac_mode_updates_state_optimistically(hass, aquarea_status):
    # The polled cloud status lags the device by ~30s, so the UI must reflect the
    # change immediately from the optimistic push, without re-reading status.
    _, client = await _setup(hass, aquarea_status)
    assert hass.states.get("climate.warmtepomp_beneden").state == "cool"
    await hass.services.async_call(
        "climate", "set_hvac_mode",
        {"entity_id": "climate.warmtepomp_beneden", "hvac_mode": "off"}, blocking=True,
    )
    assert hass.states.get("climate.warmtepomp_beneden").state == "off"
    # only the first-refresh poll ran; no extra status read was triggered by the write
    assert client.get_status.await_count == 1
