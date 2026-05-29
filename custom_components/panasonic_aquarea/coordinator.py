"""Data update coordinator for Panasonic Aquarea."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import ApiError, AuthError, PanasonicCloudClient
from .api.models import AquareaDevice
from .const import (
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class PanasonicAquareaCoordinator(DataUpdateCoordinator[dict[str, AquareaDevice]]):
    """Polls Comfort Cloud and exposes {guid: AquareaDevice}."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.entry = entry
        self._guids: list[str] = []
        self.client = PanasonicCloudClient(
            async_get_clientsession(hass),
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
            refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
            on_token_refresh=self._persist_refresh_token,
        )

    async def _persist_refresh_token(self, token: str) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry, data={**self.entry.data, CONF_REFRESH_TOKEN: token}
        )

    async def _async_setup(self) -> None:
        try:
            await self.client.ensure_session()
            self._guids = [guid for guid, _ in await self.client.get_devices()]
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except ApiError as err:
            raise UpdateFailed(str(err)) from err

    async def _async_update_data(self) -> dict[str, AquareaDevice]:
        result: dict[str, AquareaDevice] = {}
        for guid in self._guids:
            try:
                await self.client.ensure_session()
                result[guid] = await self.client.get_status(guid)
            except AuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except ApiError as err:
                _LOGGER.warning("Failed to update %s: %s", guid, err)
        if not result:
            raise UpdateFailed("No device data retrieved")
        return result
