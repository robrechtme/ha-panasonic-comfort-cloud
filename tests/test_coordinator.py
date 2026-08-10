from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.panasonic_aquarea.api.client import ApiError
from custom_components.panasonic_aquarea.api.models import AquareaDevice
from custom_components.panasonic_aquarea.const import DOMAIN


async def test_one_failing_device_does_not_block_others(hass: HomeAssistant, aquarea_status):
    good = AquareaDevice.from_status("HP2", aquarea_status)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"username": "u", "password": "p", "refresh_token": "r"},
        unique_id="u",
    )
    entry.add_to_hass(hass)

    async def fake_get_status(guid, **kwargs):
        if guid == "HP1":
            raise ApiError("boom")
        return good

    with patch(
        "custom_components.panasonic_aquarea.coordinator.PanasonicCloudClient"
    ) as cls:
        client = cls.return_value
        client.ensure_session = AsyncMock()
        client.get_devices = AsyncMock(return_value=[("HP1", "A"), ("HP2", "B")])
        client.get_status = AsyncMock(side_effect=fake_get_status)
        client.get_energy_today = AsyncMock(return_value=MagicMock())
        client.get_energy_history = AsyncMock(return_value=[])

        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    coordinator = entry.runtime_data
    assert set(coordinator.data.keys()) == {"HP2"}  # HP1 failed, HP2 survived
