"""Select platform for Panasonic Aquarea."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PanasonicAquareaConfigEntry
from .api.models import QuietMode
from .entity import AquareaEntity

_QUIET_OPTIONS: dict[str, QuietMode] = {mode.name.lower(): mode for mode in QuietMode}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PanasonicAquareaConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(AquareaQuietModeSelect(coordinator, guid) for guid in coordinator.data)


class AquareaQuietModeSelect(AquareaEntity, SelectEntity):
    _attr_translation_key = "quiet_mode"
    _attr_options = list(_QUIET_OPTIONS)

    def __init__(self, coordinator, guid) -> None:
        super().__init__(coordinator, guid)
        self._attr_unique_id = f"{guid}_quiet_mode"

    @property
    def current_option(self) -> str:
        return self.device.quiet_mode.name.lower()

    async def async_select_option(self, option: str) -> None:
        mode = _QUIET_OPTIONS[option]
        await self.coordinator.client.set_quiet_mode(self._guid, mode)
        self.coordinator.apply_optimistic(self._guid, quiet_mode=mode)
