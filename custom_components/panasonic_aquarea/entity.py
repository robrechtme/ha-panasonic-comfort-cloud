"""Base entity for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.models import UpdateOperationMode
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

    def _operation_bundle(
        self,
        *,
        mode: UpdateOperationMode | None = None,
        zone_overrides: dict[int, bool] | None = None,
        tank_on: bool | None = None,
    ) -> tuple[int, list[tuple[int, bool]], bool]:
        """Build a full-bundle write from the device's current state, with overrides.

        Panasonic's API doesn't reliably honor a bare operationMode, zoneStatus,
        or tankStatus write in isolation - every zone's and the tank's current
        activation state needs echoing back alongside whatever's actually
        changing. Mirrors aioaquarea's post_device_operation_update.

        When the mode isn't being changed it's echoed from the device's current
        read-side mode, converted to the write enum - the two use different
        numbering, so echoing the raw read value silently reselects the wrong
        mode (live-verified: it flipped the unit to Heat).
        """
        device = self.device
        overrides = zone_overrides or {}
        zones = [(z.zone_id, overrides.get(z.zone_id, z.on)) for z in device.zones]
        resolved_mode = int(
            mode if mode is not None else UpdateOperationMode.from_read(device.operation_mode)
        )
        resolved_tank_on = (
            tank_on if tank_on is not None else bool(device.tank and device.tank.on)
        )
        return resolved_mode, zones, resolved_tank_on
