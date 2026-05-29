from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.panasonic_aquarea.api.models import AquareaDevice, UpdateOperationMode
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
        client.set_operation_mode = AsyncMock()
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry, client


async def test_select_state(hass: HomeAssistant, aquarea_status):
    await _setup(hass, aquarea_status)
    state = hass.states.get("select.warmtepomp_operation_mode")
    assert state is not None
    assert state.state == "cool"
    assert state.attributes["options"] == ["off", "heat", "cool", "auto"]


async def test_select_option_calls_client(hass: HomeAssistant, aquarea_status):
    _, client = await _setup(hass, aquarea_status)
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.warmtepomp_operation_mode", "option": "heat"}, blocking=True,
    )
    client.set_operation_mode.assert_awaited_once_with("HP1", UpdateOperationMode.HEAT)


async def test_operation_mode_sensor_removed(hass: HomeAssistant, aquarea_status):
    await _setup(hass, aquarea_status)
    assert hass.states.get("sensor.warmtepomp_operation_mode") is None
