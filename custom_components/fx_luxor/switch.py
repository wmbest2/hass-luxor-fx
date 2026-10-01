"""Luxor themes as switches (themes have real on/off state on the controller)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import LuxorError, Theme
from .coordinator import LuxorConfigEntry, LuxorCoordinator
from .entity import LuxorEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def _add_new() -> None:
        new = [i for i in coordinator.data.themes if i not in known]
        known.update(new)
        async_add_entities(LuxorThemeSwitch(coordinator, i) for i in new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class LuxorThemeSwitch(LuxorEntity, SwitchEntity):
    """A Luxor theme (A-Z on the facepack)."""

    def __init__(self, coordinator: LuxorCoordinator, index: int) -> None:
        super().__init__(coordinator, f"theme_{index}")
        self._index = index

    @property
    def _theme(self) -> Theme | None:
        return self.coordinator.data.themes.get(self._index)

    @property
    def available(self) -> bool:
        return super().available and self._theme is not None

    @property
    def name(self) -> str:
        theme = self._theme
        return f"Theme {theme.name}" if theme else f"Theme {chr(65 + self._index)}"

    @property
    def is_on(self) -> bool | None:
        theme = self._theme
        return theme.on if theme else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "theme_index": self._index,
            "theme_letter": chr(65 + self._index) if 0 <= self._index < 26 else None,
        }
        groups = self.coordinator.theme_groups.get(self._index)
        if groups is not None:
            attrs["groups"] = [
                {"group": g.group, "intensity": g.intensity, "color_slot": g.color} for g in groups
            ]
        return attrs

    async def _set(self, on: bool) -> None:
        try:
            await self.coordinator.client.illuminate_theme(self._index, on)
        except LuxorError as err:
            raise HomeAssistantError(f"Failed to switch {self.name}: {err}") from err
        if (theme := self._theme) is not None:
            theme.on = on
        await self._async_command_done()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
