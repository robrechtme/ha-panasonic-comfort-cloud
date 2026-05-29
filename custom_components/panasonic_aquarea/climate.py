"""Climate platform (absolute-temperature zones) for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PanasonicAquareaConfigEntry
from .api.models import OperationMode, ZoneMode
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
            if zone.mode is ZoneMode.ABSOLUTE:
                entities.append(AquareaZoneClimate(coordinator, guid, zone.zone_id))
    async_add_entities(entities)


class AquareaZoneClimate(AquareaEntity, ClimateEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT_COOL]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator, guid, zone_id: int) -> None:
        super().__init__(coordinator, guid)
        self._zone_id = zone_id
        self._attr_unique_id = f"{guid}_zone{zone_id}_climate"
        self._attr_translation_key = "zone"
        self._attr_translation_placeholders = {"zone": self._zone().name}

    def _zone(self):
        return next(z for z in self.device.zones if z.zone_id == self._zone_id)

    @property
    def _cooling(self) -> bool:
        return self.device.operation_mode is OperationMode.COOL

    @property
    def current_temperature(self) -> int:
        return self._zone().current_temperature

    @property
    def target_temperature(self) -> int:
        z = self._zone()
        return z.cool_setpoint if self._cooling else z.heat_setpoint

    @property
    def min_temp(self) -> int:
        z = self._zone()
        return z.cool_min if self._cooling else z.heat_min

    @property
    def max_temp(self) -> int:
        z = self._zone()
        return z.cool_max if self._cooling else z.heat_max

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT_COOL if self._zone().on else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction:
        if not self._zone().on:
            return HVACAction.OFF
        return HVACAction.COOLING if self._cooling else HVACAction.HEATING

    async def async_set_temperature(self, **kwargs) -> None:
        temp = int(kwargs[ATTR_TEMPERATURE])
        if not self.min_temp <= temp <= self.max_temp:
            raise ValueError(f"temperature {temp} out of range {self.min_temp}-{self.max_temp}")
        await self.coordinator.client.set_zone_temperature(
            self._guid, self._zone_id, temp, cooling=self._cooling
        )
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self.coordinator.client.set_zone_operation(
            self._guid, self._zone_id, on=hvac_mode != HVACMode.OFF
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT_COOL)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
