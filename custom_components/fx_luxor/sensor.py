"""Diagnostic sensors."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LuxorConfigEntry, LuxorCoordinator
from .entity import LuxorEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if coordinator.info.rssi is not None:
        async_add_entities([LuxorSignalSensor(coordinator)])


class LuxorSignalSensor(LuxorEntity, SensorEntity):
    """Wi-Fi signal as reported by the controller (unitless, higher is better)."""

    _attr_translation_key = "signal"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: LuxorCoordinator) -> None:
        super().__init__(coordinator, "signal")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.info.rssi
