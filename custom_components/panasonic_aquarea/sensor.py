"""Sensor platform for Panasonic Aquarea."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import PanasonicAquareaConfigEntry
from .api.models import AquareaDevice
from .const import DOMAIN
from .entity import AquareaEntity


@dataclass(frozen=True, kw_only=True)
class AquareaSensorDescription(SensorEntityDescription):
    value_fn: Callable[[AquareaDevice], float | int | str | None]


_ENERGY_SENSORS = (
    ("heating", lambda t: t.heating),
    ("cooling", lambda t: t.cooling),
    ("hot_water", lambda t: t.hot_water),
    ("total", lambda t: t.total),
)


SENSORS: tuple[AquareaSensorDescription, ...] = (
    AquareaSensorDescription(
        key="outdoor_temperature",
        translation_key="outdoor_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.outdoor_temperature,
    ),
    AquareaSensorDescription(
        key="pump_duty",
        translation_key="pump_duty",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.pump_duty,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PanasonicAquareaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []
    for guid, device in coordinator.data.items():
        entities += [AquareaSensor(coordinator, guid, desc) for desc in SENSORS]
        for zone in device.zones:
            entities.append(AquareaZoneTempSensor(coordinator, guid, zone.zone_id))
        if device.tank is not None:
            entities.append(AquareaTankTempSensor(coordinator, guid))
    energy = coordinator.energy
    if energy is not None:
        for guid in energy.data:
            entities += [
                AquareaEnergySensor(energy, guid, key, fn) for key, fn in _ENERGY_SENSORS
            ]
    async_add_entities(entities)


class AquareaSensor(AquareaEntity, SensorEntity):
    entity_description: AquareaSensorDescription

    def __init__(self, coordinator, guid, description: AquareaSensorDescription) -> None:
        super().__init__(coordinator, guid)
        self.entity_description = description
        self._attr_unique_id = f"{guid}_{description.key}"

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.device)


class AquareaZoneTempSensor(AquareaEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, guid, zone_id: int) -> None:
        super().__init__(coordinator, guid)
        self._zone_id = zone_id
        self._attr_unique_id = f"{guid}_zone{zone_id}_temperature"
        self._attr_translation_key = "zone_temperature"
        self._attr_translation_placeholders = {"zone": self._zone().name}

    def _zone(self):
        return next(z for z in self.device.zones if z.zone_id == self._zone_id)

    @property
    def native_value(self):
        return self._zone().current_temperature


class AquareaTankTempSensor(AquareaEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "tank_temperature"

    def __init__(self, coordinator, guid) -> None:
        super().__init__(coordinator, guid)
        self._attr_unique_id = f"{guid}_tank_temperature"

    @property
    def native_value(self):
        return self.device.tank.current_temperature


class AquareaEnergySensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, energy_coordinator, guid, key, value_fn) -> None:
        super().__init__(energy_coordinator)
        self._guid = guid
        self._value_fn = value_fn
        self._attr_unique_id = f"{guid}_energy_{key}"
        self._attr_translation_key = f"energy_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, guid)})

    @property
    def native_value(self):
        totals = self.coordinator.data.get(self._guid)
        return self._value_fn(totals) if totals else None
