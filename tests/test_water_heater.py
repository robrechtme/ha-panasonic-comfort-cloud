from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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
    with patch(
        "custom_components.panasonic_aquarea.coordinator.PanasonicCloudClient"
    ) as cls:
        client = cls.return_value
        client.ensure_session = AsyncMock()
        client.get_devices = AsyncMock(return_value=[("HP1", "Warmtepomp")])
        client.get_status = AsyncMock(return_value=device)
        client.get_energy_today = AsyncMock(return_value=MagicMock())
        client.get_energy_history = AsyncMock(return_value=[])
        client.set_tank_temperature = AsyncMock()
        client.set_tank_operation = AsyncMock()
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, client


async def test_tank_entity_state(hass: HomeAssistant, aquarea_status):
    await _setup(hass, aquarea_status)
    state = hass.states.get("water_heater.warmtepomp_tank")
    assert state is not None
    assert state.attributes["temperature"] == 52
    assert state.attributes["current_temperature"] == 46


async def test_tank_set_temperature_calls_client(hass: HomeAssistant, aquarea_status):
    _, client = await _setup(hass, aquarea_status)
    await hass.services.async_call(
        "water_heater",
        "set_temperature",
        {"entity_id": "water_heater.warmtepomp_tank", "temperature": 50},
        blocking=True,
    )
    client.set_tank_temperature.assert_awaited_once_with("HP1", 50)


async def test_tank_set_temperature_out_of_range_rejected(hass: HomeAssistant, aquarea_status):
    _, client = await _setup(hass, aquarea_status)
    with pytest.raises(ValueError):
        await hass.services.async_call(
            "water_heater",
            "set_temperature",
            {"entity_id": "water_heater.warmtepomp_tank", "temperature": 99},
            blocking=True,
        )
    client.set_tank_temperature.assert_not_awaited()
