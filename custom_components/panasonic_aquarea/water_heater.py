"""Water heater (DHW tank) platform for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.components.water_heater import (
    STATE_OFF,
    STATE_PERFORMANCE,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PanasonicAquareaConfigEntry
from .entity import AquareaEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PanasonicAquareaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        AquareaTank(coordinator, guid)
        for guid, device in coordinator.data.items()
        if device.tank is not None
    )


class AquareaTank(AquareaEntity, WaterHeaterEntity):
    _attr_translation_key = "tank"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_operation_list = [STATE_OFF, STATE_PERFORMANCE]
    _attr_supported_features = (
        WaterHeaterEntityFeature.TARGET_TEMPERATURE
        | WaterHeaterEntityFeature.OPERATION_MODE
    )

    def __init__(self, coordinator, guid) -> None:
        super().__init__(coordinator, guid)
        self._attr_unique_id = f"{guid}_tank"

    @property
    def current_temperature(self) -> int:
        return self.device.tank.current_temperature

    @property
    def target_temperature(self) -> int:
        return self.device.tank.target_temperature

    @property
    def min_temp(self) -> int:
        return self.device.tank.heat_min

    @property
    def max_temp(self) -> int:
        return self.device.tank.heat_max

    @property
    def current_operation(self) -> str:
        return STATE_PERFORMANCE if self.device.tank.on else STATE_OFF

    async def async_set_temperature(self, **kwargs) -> None:
        temp = int(kwargs[ATTR_TEMPERATURE])
        tank = self.device.tank
        if not tank.heat_min <= temp <= tank.heat_max:
            raise ValueError(
                f"tank temperature {temp} out of range {tank.heat_min}-{tank.heat_max}"
            )
        await self.coordinator.client.set_tank_temperature(self._guid, temp)
        await self.coordinator.async_request_refresh()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        on = operation_mode == STATE_PERFORMANCE
        mode, zones, tank_on = self._operation_bundle(tank_on=on)
        await self.coordinator.client.set_operation(self._guid, mode, zones, tank_on=tank_on)
        self.coordinator.apply_optimistic(self._guid, tank_on=on)
