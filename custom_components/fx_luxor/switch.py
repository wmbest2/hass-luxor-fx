"""Diagnostic switch for the controller's FlashLights (light assignment) mode."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later

from .api import LuxorError
from .coordinator import LuxorConfigEntry, LuxorCoordinator
from .entity import LuxorEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

# Leaving the mode on by accident keeps every fixture lit; turn it off on our own.
AUTO_OFF = timedelta(minutes=10)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LuxorFlashLightsSwitch(entry.runtime_data)])


class LuxorFlashLightsSwitch(LuxorEntity, SwitchEntity):
    """FlashLights mode: the mode the Luxor app uses to assign fixtures to groups.

    The controller never reports this mode, so the state is what we last sent
    (cleared by Extinguish all, which also leaves the mode). Turning it off sets
    every group to 0%.
    """

    _attr_translation_key = "flash_lights"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_assumed_state = True

    def __init__(self, coordinator: LuxorCoordinator) -> None:
        super().__init__(coordinator, "flash_lights")
        self._cancel_auto_off: CALLBACK_TYPE | None = None

    @property
    def is_on(self) -> bool:
        return self.coordinator.client.flash_lights_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, on: bool) -> None:
        self._clear_timer()
        try:
            await self.coordinator.client.flash_lights(on)
        except LuxorError as err:
            raise HomeAssistantError(f"Failed to turn flash lights {'on' if on else 'off'}: {err}") from err
        if on:
            self._cancel_auto_off = async_call_later(self.hass, AUTO_OFF, self._async_auto_off)
        await self._async_command_done()

    async def _async_auto_off(self, _now: datetime) -> None:
        self._cancel_auto_off = None
        if not self.is_on:
            return
        _LOGGER.info("Turning off flash lights after %s", AUTO_OFF)
        try:
            await self._set(False)
        except HomeAssistantError as err:
            _LOGGER.warning("Could not turn off flash lights: %s", err)

    def _clear_timer(self) -> None:
        if self._cancel_auto_off is not None:
            self._cancel_auto_off()
            self._cancel_auto_off = None

    async def async_will_remove_from_hass(self) -> None:
        self._clear_timer()
        await super().async_will_remove_from_hass()
