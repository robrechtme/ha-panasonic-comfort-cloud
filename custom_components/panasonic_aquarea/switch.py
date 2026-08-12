"""Switch platform for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
    entities: list[SwitchEntity] = []
    for guid, device in coordinator.data.items():
        for zone in device.zones:
            if zone.mode is ZoneMode.OFFSET:
                entities.append(AquareaZoneSwitch(coordinator, guid, zone.zone_id))
        if device.tank is not None:
            entities.append(AquareaForceDHWSwitch(coordinator, guid))
    async_add_entities(entities)


class AquareaZoneSwitch(AquareaEntity, SwitchEntity):
    _attr_translation_key = "zone_power"

    def __init__(self, coordinator, guid, zone_id: int) -> None:
        super().__init__(coordinator, guid)
        self._zone_id = zone_id
        self._attr_unique_id = f"{guid}_zone{zone_id}_switch"
        self._attr_translation_placeholders = {"zone": self._zone().name}

    def _zone(self):
        return next(z for z in self.device.zones if z.zone_id == self._zone_id)

    @property
    def is_on(self) -> bool:
        return self._zone().on

    async def async_turn_on(self, **kwargs) -> None:
        mode, zones, tank_on = self._operation_bundle(zone_overrides={self._zone_id: True})
        await self.coordinator.client.set_operation(self._guid, mode, zones, tank_on=tank_on)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        mode, zones, tank_on = self._operation_bundle(zone_overrides={self._zone_id: False})
        await self.coordinator.client.set_operation(self._guid, mode, zones, tank_on=tank_on)
        await self.coordinator.async_request_refresh()


class AquareaForceDHWSwitch(AquareaEntity, SwitchEntity):
    _attr_translation_key = "force_dhw"

    def __init__(self, coordinator, guid) -> None:
        super().__init__(coordinator, guid)
        self._attr_unique_id = f"{guid}_force_dhw"

    @property
    def is_on(self) -> bool:
        return self.device.force_dhw

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.client.set_force_dhw(self._guid, on=True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.client.set_force_dhw(self._guid, on=False)
        await self.coordinator.async_request_refresh()
