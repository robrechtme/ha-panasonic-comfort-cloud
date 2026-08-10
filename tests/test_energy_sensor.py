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
        client.get_energy_history = AsyncMock(return_value=[])
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
    assert float(hass.states.get("sensor.warmtepomp_heating_energy_today").state) == 0.0
