"""Data update coordinator for Panasonic Aquarea."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api.client import ApiError, AuthError, PanasonicCloudClient
from .api.models import AquareaDevice, EnergyTotals
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
        self.energy = None  # set to the PanasonicAquareaEnergyCoordinator in async_setup_entry

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


class PanasonicAquareaEnergyCoordinator(DataUpdateCoordinator[dict[str, EnergyTotals]]):
    """Polls today's consumption for each device every 30 minutes."""

    def __init__(self, hass: HomeAssistant, client: PanasonicCloudClient, guids: list[str]) -> None:
        super().__init__(
            hass, _LOGGER, name=f"{DOMAIN}_energy", update_interval=timedelta(minutes=30)
        )
        self._client = client
        self._guids = guids

    @staticmethod
    def _today_and_offset() -> tuple[str, str]:
        now = dt_util.now()  # HA-local time
        date = now.strftime("%Y%m%d")
        raw = now.strftime("%z") or "+0000"  # e.g. +0200
        offset = f"{raw[:3]}:{raw[3:]}"  # -> +02:00
        return date, offset

    async def _async_update_data(self) -> dict[str, EnergyTotals]:
        date, offset = self._today_and_offset()
        result: dict[str, EnergyTotals] = {}
        for guid in self._guids:
            try:
                result[guid] = await self._client.get_energy_today(guid, date, offset)
            except (ApiError, AuthError) as err:
                _LOGGER.warning("Energy update failed for %s: %s", guid, err)
        return result
