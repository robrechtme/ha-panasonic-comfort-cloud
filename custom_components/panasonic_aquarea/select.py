"""Select platform (device operation mode) for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PanasonicAquareaConfigEntry
from .api.models import UpdateOperationMode
from .entity import AquareaEntity

_OPTIONS = ["off", "heat", "cool", "auto"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PanasonicAquareaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(AquareaModeSelect(coordinator, guid) for guid in coordinator.data)


class AquareaModeSelect(AquareaEntity, SelectEntity):
    _attr_translation_key = "operation_mode"
    _attr_options = _OPTIONS

    def __init__(self, coordinator, guid) -> None:
        super().__init__(coordinator, guid)
        self._attr_unique_id = f"{guid}_operation_mode_select"

    @property
    def current_option(self) -> str:
        name = self.device.operation_mode.name.lower()
        return name if name in _OPTIONS else "off"

    async def async_select_option(self, option: str) -> None:
        mode = UpdateOperationMode[option.upper()]
        await self.coordinator.client.set_operation_mode(self._guid, mode)
        await self.coordinator.async_request_refresh()
