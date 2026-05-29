"""Base entity for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PanasonicAquareaCoordinator


class AquareaEntity(CoordinatorEntity[PanasonicAquareaCoordinator]):
    """Common base wiring coordinator data + device_info for one heat pump."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PanasonicAquareaCoordinator, guid: str) -> None:
        super().__init__(coordinator)
        self._guid = guid
        device = coordinator.data[guid]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, guid)},
            manufacturer="Panasonic",
            name=device.name,
            model=device.service_type,
        )

    @property
    def device(self):
        return self.coordinator.data[self._guid]

    @property
    def available(self) -> bool:
        return super().available and self._guid in self.coordinator.data
