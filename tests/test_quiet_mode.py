import copy
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.panasonic_aquarea.api.models import AquareaDevice, QuietMode
from custom_components.panasonic_aquarea.const import DOMAIN

ENTITY_ID = "select.warmtepomp_quiet_mode"


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
        client.set_quiet_mode = AsyncMock()
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return client


async def test_quiet_mode_state_from_status(hass: HomeAssistant, aquarea_status):
    status = copy.deepcopy(aquarea_status)
    status["status"]["quietMode"] = 3
    await _setup(hass, status)
    state = hass.states.get(ENTITY_ID)
    assert state.state == "level_3"
    assert state.attributes["options"] == ["off", "level_1", "level_2", "level_3"]


async def test_quiet_mode_select_writes_and_updates_optimistically(
    hass: HomeAssistant, aquarea_status
):
    client = await _setup(hass, aquarea_status)
    assert hass.states.get(ENTITY_ID).state == "off"
    await hass.services.async_call(
        "select", "select_option", {"entity_id": ENTITY_ID, "option": "level_1"}, blocking=True,
    )
    client.set_quiet_mode.assert_awaited_once_with("HP1", QuietMode.LEVEL_1)
    assert hass.states.get(ENTITY_ID).state == "level_1"
    assert client.get_status.await_count == 1


def test_unknown_quiet_mode_parses_as_off(aquarea_status):
    status = copy.deepcopy(aquarea_status)
    status["status"]["quietMode"] = 9
    assert AquareaDevice.from_status("HP1", status).quiet_mode is QuietMode.OFF
