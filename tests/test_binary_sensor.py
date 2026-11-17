from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.panasonic_aquarea.api.models import AquareaDevice
from custom_components.panasonic_aquarea.const import DOMAIN


async def _setup(hass, status):
    device = AquareaDevice.from_status("HP1", status)
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
    return entry


async def test_pump_duty_off_when_zero(hass: HomeAssistant, aquarea_status):
    await _setup(hass, aquarea_status)
    state = hass.states.get("binary_sensor.warmtepomp_pump_duty")
    assert state is not None
    assert state.state == "off"
    assert state.attributes["device_class"] == "running"


async def test_pump_duty_on_when_nonzero(hass: HomeAssistant, aquarea_status):
    aquarea_status["status"]["pumpDuty"] = 1
    await _setup(hass, aquarea_status)
    state = hass.states.get("binary_sensor.warmtepomp_pump_duty")
    assert state.state == "on"


async def test_no_pump_duty_percentage_sensor(hass: HomeAssistant, aquarea_status):
    await _setup(hass, aquarea_status)
    assert hass.states.get("sensor.warmtepomp_pump_duty") is None


async def test_fault_off_for_eco_comfort_special_status(hass: HomeAssistant, aquarea_status):
    aquarea_status["status"]["specialStatus"] = 2
    await _setup(hass, aquarea_status)
    assert hass.states.get("binary_sensor.warmtepomp_fault").state == "off"


async def test_fault_on_with_error_codes(hass: HomeAssistant, aquarea_status):
    aquarea_status["status"]["faultStatus"] = [
        {"errorCode": "H23", "errorMessage": "Refrigerant sensor abnormality"}
    ]
    await _setup(hass, aquarea_status)
    state = hass.states.get("binary_sensor.warmtepomp_fault")
    assert state.state == "on"
    assert state.attributes["error_codes"] == ["H23"]
    assert state.attributes["error_messages"] == ["Refrigerant sensor abnormality"]


async def test_water_pressure_sensor(hass: HomeAssistant, aquarea_status):
    await _setup(hass, aquarea_status)
    state = hass.states.get("sensor.warmtepomp_water_pressure")
    assert float(state.state) == 1.32
    assert state.attributes["unit_of_measurement"] == "bar"
