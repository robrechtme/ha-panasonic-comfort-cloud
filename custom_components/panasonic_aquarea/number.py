"""Number platform (offset-mode zone compensation) for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PanasonicAquareaConfigEntry
from .api.models import ZoneMode
from .entity import AquareaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PanasonicAquareaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities = []
    for guid, device in coordinator.data.items():
        for zone in device.zones:
            if zone.mode is ZoneMode.OFFSET:
                entities.append(AquareaZoneOffset(coordinator, guid, zone.zone_id))
    async_add_entities(entities)


class AquareaZoneOffset(AquareaEntity, NumberEntity):
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 1

    def __init__(self, coordinator, guid, zone_id: int) -> None:
        super().__init__(coordinator, guid)
        self._zone_id = zone_id
        self._attr_unique_id = f"{guid}_zone{zone_id}_offset"
        self._attr_translation_key = "zone_offset"
        self._attr_translation_placeholders = {"zone": self._zone().name}

    def _zone(self):
        return next(z for z in self.device.zones if z.zone_id == self._zone_id)

    @property
    def native_min_value(self) -> int:
        return self._zone().heat_min

    @property
    def native_max_value(self) -> int:
        return self._zone().heat_max

    @property
    def native_value(self) -> int:
        return self._zone().heat_setpoint

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.client.set_zone_temperature(
            self._guid, self._zone_id, int(value), cooling=False
        )
        await self.coordinator.async_request_refresh()
