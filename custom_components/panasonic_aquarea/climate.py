"""Climate platform (absolute-temperature zones) for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.components.climate import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PanasonicAquareaConfigEntry
from .api.models import OperationMode, UpdateOperationMode, ZoneMode
from .entity import AquareaEntity

_MODE_TO_HVAC = {
    OperationMode.HEAT: HVACMode.HEAT,
    OperationMode.COOL: HVACMode.COOL,
    OperationMode.AUTO: HVACMode.AUTO,
}
_HVAC_TO_UPDATE = {
    HVACMode.HEAT: UpdateOperationMode.HEAT,
    HVACMode.COOL: UpdateOperationMode.COOL,
    HVACMode.AUTO: UpdateOperationMode.AUTO,
}
_HVAC_TO_MODE = {
    HVACMode.HEAT: OperationMode.HEAT,
    HVACMode.COOL: OperationMode.COOL,
    HVACMode.AUTO: OperationMode.AUTO,
}


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
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL, HVACMode.AUTO]
    _attr_target_temperature_step = 1
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
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
    def _mode(self) -> OperationMode:
        return self.device.operation_mode

    @property
    def hvac_mode(self) -> HVACMode:
        if not self._zone().on:
            return HVACMode.OFF
        return _MODE_TO_HVAC.get(self._mode, HVACMode.OFF)

    @property
    def hvac_action(self) -> HVACAction:
        if not self._zone().on:
            return HVACAction.OFF
        if self._mode is OperationMode.COOL:
            return HVACAction.COOLING
        if self._mode is OperationMode.HEAT:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def current_temperature(self) -> int:
        return self._zone().current_temperature

    @property
    def target_temperature(self) -> int | None:
        z = self._zone()
        if self._mode is OperationMode.HEAT:
            return z.heat_setpoint
        if self._mode is OperationMode.COOL:
            return z.cool_setpoint
        return None  # AUTO uses the range below

    @property
    def target_temperature_low(self) -> int | None:
        return self._zone().heat_setpoint if self._mode is OperationMode.AUTO else None

    @property
    def target_temperature_high(self) -> int | None:
        return self._zone().cool_setpoint if self._mode is OperationMode.AUTO else None

    @property
    def min_temp(self) -> int:
        z = self._zone()
        if self._mode is OperationMode.COOL:
            return z.cool_min
        if self._mode is OperationMode.AUTO:
            return min(z.heat_min, z.cool_min)
        return z.heat_min

    @property
    def max_temp(self) -> int:
        z = self._zone()
        if self._mode is OperationMode.HEAT:
            return z.heat_max
        if self._mode is OperationMode.AUTO:
            return max(z.heat_max, z.cool_max)
        return z.cool_max

    async def async_set_temperature(self, **kwargs) -> None:
        guid = self._guid
        if ATTR_TARGET_TEMP_LOW in kwargs or ATTR_TARGET_TEMP_HIGH in kwargs:
            low = kwargs.get(ATTR_TARGET_TEMP_LOW)
            high = kwargs.get(ATTR_TARGET_TEMP_HIGH)
            if low is not None:
                await self.coordinator.client.set_zone_temperature(
                    guid, self._zone_id, int(low), cooling=False
                )
            if high is not None:
                await self.coordinator.client.set_zone_temperature(
                    guid, self._zone_id, int(high), cooling=True
                )
        elif ATTR_TEMPERATURE in kwargs:
            temp = int(kwargs[ATTR_TEMPERATURE])
            await self.coordinator.client.set_zone_temperature(
                guid, self._zone_id, temp, cooling=self._mode is OperationMode.COOL
            )
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            mode, zones, tank_on = self._operation_bundle(zone_overrides={self._zone_id: False})
            await self.coordinator.client.set_operation(self._guid, mode, zones, tank_on=tank_on)
            self.coordinator.apply_optimistic(self._guid, zone_on={self._zone_id: False})
        else:
            mode, zones, tank_on = self._operation_bundle(
                mode=_HVAC_TO_UPDATE[hvac_mode], zone_overrides={self._zone_id: True}
            )
            await self.coordinator.client.set_operation(self._guid, mode, zones, tank_on=tank_on)
            self.coordinator.apply_optimistic(
                self._guid,
                operation_mode=_HVAC_TO_MODE[hvac_mode],
                zone_on={self._zone_id: True},
            )

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(_MODE_TO_HVAC.get(self._mode, HVACMode.HEAT))

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
