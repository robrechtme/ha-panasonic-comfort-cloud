from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time

from custom_components.panasonic_aquarea.api.models import EnergyHourBucket
from custom_components.panasonic_aquarea.coordinator import PanasonicAquareaEnergyCoordinator

COOLING_ID = "panasonic_aquarea:hp1_cooling_energy"


class FakeStatisticsStore:
    """Stands in for the recorder's long-term statistics table.

    `get_last` and `add_external` are patched in as `get_last_statistics` /
    `async_add_external_statistics`, so the coordinator's continuity logic
    (query last sum, only append newer hours) runs against real bookkeeping
    instead of a database, without the friction of a real recorder fixture.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict[float, dict]] = {}

    def get_last(self, hass, number_of_stats, statistic_id, convert_units, types):
        bucket = self.rows.get(statistic_id)
        if not bucket:
            return {}
        last_start = max(bucket)
        return {statistic_id: [{"start": last_start, **bucket[last_start]}]}

    def add_external(self, hass, metadata, stats):
        bucket = self.rows.setdefault(metadata["statistic_id"], {})
        for s in stats:
            bucket[s["start"].timestamp()] = {"sum": s["sum"], "state": s["state"]}


def _coordinator(client):
    return PanasonicAquareaEnergyCoordinator(MagicMock(), client, ["HP1"])


def _client(buckets):
    client = MagicMock()
    client.get_energy_today = AsyncMock(return_value=MagicMock())
    client.get_energy_history = AsyncMock(return_value=buckets)
    return client


def _patch_recorder(store: FakeStatisticsStore) -> ExitStack:
    stack = ExitStack()
    mock_get_instance = stack.enter_context(
        patch("custom_components.panasonic_aquarea.coordinator.get_instance")
    )
    mock_get_instance.return_value.async_add_executor_job = AsyncMock(
        side_effect=lambda fn, *a: fn(*a)
    )
    stack.enter_context(
        patch(
            "custom_components.panasonic_aquarea.coordinator.get_last_statistics",
            side_effect=store.get_last,
        )
    )
    stack.enter_context(
        patch(
            "custom_components.panasonic_aquarea.coordinator.async_add_external_statistics",
            side_effect=store.add_external,
        )
    )
    return stack


async def test_only_completed_hours_are_backfilled():
    buckets = [
        EnergyHourBucket(datetime(2026, 5, 29, 9, tzinfo=UTC), 0.0, 0.05, 0.0),
        EnergyHourBucket(datetime(2026, 5, 29, 10, tzinfo=UTC), 0.1, 0.07, 0.2),
    ]
    coordinator = _coordinator(_client(buckets))
    store = FakeStatisticsStore()

    with freeze_time("2026-05-29 10:30:00+00:00"), _patch_recorder(store):
        await coordinator._async_update_data()

    # hour 9 ended before 10:30 -> backfilled; hour 10 is still open -> not yet
    hour9 = datetime(2026, 5, 29, 9, tzinfo=UTC).timestamp()
    assert list(store.rows[COOLING_ID].keys()) == [hour9]
    assert store.rows[COOLING_ID][hour9] == {"sum": 0.05, "state": 0.05}


async def test_sum_continues_across_polls_without_double_counting():
    store = FakeStatisticsStore()
    hour9 = datetime(2026, 5, 29, 9, tzinfo=UTC)
    hour10 = datetime(2026, 5, 29, 10, tzinfo=UTC)

    first = [EnergyHourBucket(hour9, 0.0, 0.05, 0.0)]
    coordinator = _coordinator(_client(first))
    with freeze_time("2026-05-29 10:05:00+00:00"), _patch_recorder(store):
        await coordinator._async_update_data()

    # next poll: Panasonic returns hour 9 again (already stored) plus the newly-completed hour 10
    second = first + [EnergyHourBucket(hour10, 0.1, 0.07, 0.2)]
    coordinator._client.get_energy_history = AsyncMock(return_value=second)
    with freeze_time("2026-05-29 11:05:00+00:00"), _patch_recorder(store):
        await coordinator._async_update_data()

    rows = store.rows[COOLING_ID]
    assert list(rows.keys()) == [hour9.timestamp(), hour10.timestamp()]
    assert rows[hour9.timestamp()] == {"sum": 0.05, "state": 0.05}
    # continues from the existing sum (0.05), doesn't reset or double-count hour 9
    assert rows[hour10.timestamp()] == {"sum": 0.12, "state": 0.07}
