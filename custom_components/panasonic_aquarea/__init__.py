"""The Panasonic Aquarea integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import PanasonicAquareaCoordinator, PanasonicAquareaEnergyCoordinator

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.WATER_HEATER,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SWITCH,
]

type PanasonicAquareaConfigEntry = ConfigEntry[PanasonicAquareaCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: PanasonicAquareaConfigEntry
) -> bool:
    coordinator = PanasonicAquareaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    energy_coordinator = PanasonicAquareaEnergyCoordinator(
        hass, coordinator.client, list(coordinator.data)
    )
    await energy_coordinator.async_config_entry_first_refresh()
    coordinator.energy = energy_coordinator

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: PanasonicAquareaConfigEntry
) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
