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
        client.set_force_dhw = AsyncMock()
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, client


async def test_offset_number_state(hass: HomeAssistant, aquarea_status):
    await _setup(hass, aquarea_status)
    state = hass.states.get("number.warmtepomp_boven_offset")
    assert state is not None
    assert float(state.state) == -5
    # absolute zone has no offset number
    assert hass.states.get("number.warmtepomp_beneden_offset") is None


async def test_offset_number_set_writes_heatset(hass: HomeAssistant, aquarea_status):
    _, client = await _setup(hass, aquarea_status)
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.warmtepomp_boven_offset", "value": 2}, blocking=True,
    )
    client.set_zone_temperature.assert_awaited_once_with("HP1", 1, 2, cooling=False)


async def test_zone_switch_turn_on(hass: HomeAssistant, aquarea_status):
    _, client = await _setup(hass, aquarea_status)
    await hass.services.async_call(
        "switch", "turn_on",
        {"entity_id": "switch.warmtepomp_boven"}, blocking=True,
    )
    # Boven (zone 1) forced on, Beneden (zone 2) echoed as-is, mode/tank echoed
    client.set_operation.assert_awaited_once_with("HP1", 2, [(1, True), (2, True)], tank_on=True)


async def test_force_dhw_switch_turn_on(hass: HomeAssistant, aquarea_status):
    _, client = await _setup(hass, aquarea_status)
    await hass.services.async_call(
        "switch", "turn_on",
        {"entity_id": "switch.warmtepomp_force_dhw"}, blocking=True,
    )
    client.set_force_dhw.assert_awaited_once_with("HP1", on=True)


async def test_force_dhw_switch_absent_without_tank(hass: HomeAssistant, aquarea_status):
    import copy
    tankless = copy.deepcopy(aquarea_status)
    tankless["status"]["tankStatus"] = None
    device = AquareaDevice.from_status("HP1", tankless)
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
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get("switch.warmtepomp_force_dhw") is None
    # offset-zone switch still present
    assert hass.states.get("switch.warmtepomp_boven") is not None
