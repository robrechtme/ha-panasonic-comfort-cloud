"""Data update coordinator for Panasonic Aquarea."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter

from .api.client import ApiError, AuthError, PanasonicCloudClient
from .api.models import AquareaDevice, EnergyHourBucket, EnergyTotals, OperationMode
from .const import (
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_USERNAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

_ENERGY_CATEGORIES: tuple[tuple[str, str, Callable[[EnergyHourBucket], float]], ...] = (
    ("heating", "Heating", lambda b: b.heating),
    ("cooling", "Cooling", lambda b: b.cooling),
    ("hot_water", "Hot water", lambda b: b.hot_water),
    ("total", "Total", lambda b: b.total),
)


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

    def apply_optimistic(
        self,
        guid: str,
        *,
        operation_mode: OperationMode | None = None,
        zone_on: dict[int, bool] | None = None,
        tank_on: bool | None = None,
        force_dhw: bool | None = None,
    ) -> None:
        """Reflect a just-issued control write in state immediately.

        The cloud status we poll lags the device by ~30s, so reading it right
        after a write returns the pre-change state and the UI wouldn't update
        until the next poll. Instead we push the expected state to all entities
        now via async_set_updated_data; the next poll reconciles with reality
        (and corrects us if a write silently failed).
        """
        device = self.data.get(guid) if self.data else None
        if device is None:
            return
        changes: dict = {}
        if operation_mode is not None:
            changes["operation_mode"] = operation_mode
        if zone_on:
            changes["zones"] = tuple(
                replace(z, on=zone_on[z.zone_id]) if z.zone_id in zone_on else z
                for z in device.zones
            )
        if tank_on is not None and device.tank is not None:
            changes["tank"] = replace(device.tank, on=tank_on)
        if force_dhw is not None:
            changes["force_dhw"] = force_dhw
        if not changes:
            return
        self.async_set_updated_data({**self.data, guid: replace(device, **changes)})


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
                await self._async_backfill_statistics(guid, date, offset)
            except (ApiError, AuthError) as err:
                _LOGGER.warning("Energy update failed for %s: %s", guid, err)
        return result

    async def _async_backfill_statistics(self, guid: str, date: str, offset: str) -> None:
        """Insert Panasonic's own hour-bucketed consumption into long-term statistics.

        Panasonic already attributes consumption to the correct device-local hour;
        relying on our 30-min, wall-clock-unaligned polling of a single cumulative
        sensor instead would let HA's own hourly reconstruction misattribute
        consumption to the following hour whenever a poll lands just after the
        boundary. Only fully-elapsed hours are backfilled — the current hour is
        still growing on Panasonic's side, so it's picked up complete next poll.
        """
        now = dt_util.now()
        buckets = await self._client.get_energy_history(guid, date, offset)
        complete = [b for b in buckets if b.start + timedelta(hours=1) <= now]
        if not complete:
            return
        for key, name, value_fn in _ENERGY_CATEGORIES:
            await self._async_backfill_category(guid, key, name, complete, value_fn)

    async def _async_backfill_category(
        self,
        guid: str,
        key: str,
        name: str,
        buckets: list[EnergyHourBucket],
        value_fn: Callable[[EnergyHourBucket], float],
    ) -> None:
        statistic_id = f"{DOMAIN}:{guid.lower()}_{key}_energy"
        last = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
        )
        if last:
            anchor_sum = last[statistic_id][0]["sum"]
            anchor_start = dt_util.utc_from_timestamp(last[statistic_id][0]["start"])
        else:
            anchor_sum, anchor_start = 0.0, None

        new_buckets = sorted(
            (b for b in buckets if anchor_start is None or b.start > anchor_start),
            key=lambda b: b.start,
        )
        if not new_buckets:
            return

        running = anchor_sum
        stats = []
        for bucket in new_buckets:
            value = round(value_fn(bucket), 3)
            running = round(running + value, 3)
            stats.append(StatisticData(start=bucket.start, state=value, sum=running))

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"Warmtepomp {name} energy",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class=EnergyConverter.UNIT_CLASS,
            unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        )
        async_add_external_statistics(self.hass, metadata, stats)
