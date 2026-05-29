from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.panasonic_aquarea.api.models import AquareaDevice
from custom_components.panasonic_aquarea.const import DOMAIN


async def test_entities_created(hass: HomeAssistant, aquarea_status):
    device = AquareaDevice.from_status("HP1", aquarea_status)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "u", "password": "p", "refresh_token": "r"},
        unique_id="u",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.panasonic_aquarea.coordinator.PanasonicCloudClient"
    ) as cls:
        client = cls.return_value
        client.ensure_session = AsyncMock()
        client.get_devices = AsyncMock(return_value=[("HP1", "Warmtepomp")])
        client.get_status = AsyncMock(return_value=device)

        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.warmtepomp_outdoor_temperature")
    assert state is not None
    assert state.state == "31"
