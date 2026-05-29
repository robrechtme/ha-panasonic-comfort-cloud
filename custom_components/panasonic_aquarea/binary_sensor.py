"""Binary sensor platform for Panasonic Aquarea."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PanasonicAquareaConfigEntry
from .api.models import AquareaDevice
from .entity import AquareaEntity


@dataclass(frozen=True, kw_only=True)
class AquareaBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[AquareaDevice], bool]


BINARY_SENSORS: tuple[AquareaBinaryDescription, ...] = (
    AquareaBinaryDescription(
        key="defrost",
        translation_key="defrost",
        device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda d: d.defrost,
    ),
    AquareaBinaryDescription(
        key="fault",
        translation_key="fault",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda d: d.fault,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PanasonicAquareaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        AquareaBinarySensor(coordinator, guid, desc)
        for guid in coordinator.data
        for desc in BINARY_SENSORS
    )


class AquareaBinarySensor(AquareaEntity, BinarySensorEntity):
    entity_description: AquareaBinaryDescription

    def __init__(self, coordinator, guid, description: AquareaBinaryDescription) -> None:
        super().__init__(coordinator, guid)
        self.entity_description = description
        self._attr_unique_id = f"{guid}_{description.key}"

    @property
    def is_on(self) -> bool:
        return self.entity_description.value_fn(self.device)
