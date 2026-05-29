from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.panasonic_aquarea.const import DOMAIN


async def test_user_flow_success(hass: HomeAssistant):
    with patch(
        "custom_components.panasonic_aquarea.config_flow.PanasonicCloudClient"
    ) as mock_client_cls:
        client = mock_client_cls.return_value
        client.login = AsyncMock()
        client.get_devices = AsyncMock(return_value=[("HP1", "Warmtepomp")])
        client._refresh_token = "REFRESH"

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == "form"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "u@example.com", "password": "pw"}
        )
        assert result["type"] == "create_entry"
        assert result["data"]["username"] == "u@example.com"
        assert result["data"]["refresh_token"] == "REFRESH"


async def test_user_flow_invalid_auth(hass: HomeAssistant):
    from custom_components.panasonic_aquarea.api.client import AuthError

    with patch(
        "custom_components.panasonic_aquarea.config_flow.PanasonicCloudClient"
    ) as mock_client_cls:
        client = mock_client_cls.return_value
        client.login = AsyncMock(side_effect=AuthError("bad creds"))

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "u@example.com", "password": "bad"}
        )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_auth"}
