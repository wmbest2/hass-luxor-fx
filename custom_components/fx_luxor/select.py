"""The controller's themes as one selector.

The controller keeps an independent on/off flag per theme: turning on theme B
does not clear theme A's flag, and changing a light by hand clears neither. So
the flags can't say which look is showing. This selector shows a theme only
while the lights still match it:

- the theme applied last (from HA, or the only flagged theme whose levels match
  the lights), as long as every group in it is still at the theme's level;
- "Off" when every light is off;
- nothing (unknown) otherwise, e.g. after a light was changed by hand.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .api import LuxorError, theme_letter
from .coordinator import LuxorConfigEntry, LuxorCoordinator
from .entity import LuxorEntity

PARALLEL_UPDATES = 1

OPTION_OFF = "Off"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LuxorThemeSelect(entry.runtime_data)])


def theme_options(coordinator: LuxorCoordinator) -> dict[str, int]:
    """Option label -> theme index, in facepack order. Duplicate names get their letter."""
    themes = sorted(coordinator.data.themes.values(), key=lambda t: t.index)
    names = [t.name or theme_letter(t.index) for t in themes]
    labels: dict[str, int] = {}
    for theme, name in zip(themes, names, strict=True):
        label = (
            name if names.count(name) == 1 and name != OPTION_OFF else f"{name} ({theme_letter(theme.index)})"
        )
        labels[label] = theme.index
    return labels


class LuxorThemeSelect(LuxorEntity, SelectEntity, RestoreEntity):
    """Pick the active theme, or Off."""

    _attr_translation_key = "theme"

    def __init__(self, coordinator: LuxorCoordinator) -> None:
        super().__init__(coordinator, "theme")
        self._active: int | None = None  # index of the theme applied last
        self._off = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is None:
            self._reconcile()
            return
        index = last.attributes.get("theme_index")
        if last.state == OPTION_OFF:
            self._off = True
        elif isinstance(index, int):
            self._active = index
        self._reconcile()

    # ---- state -------------------------------------------------------------

    def _matches(self, index: int) -> bool:
        """Do the lights currently show this theme's levels?"""
        definition = self.coordinator.theme_groups.get(index)
        if definition is None:
            return True  # not read yet; nothing to contradict
        groups = self.coordinator.data.groups
        return all(groups[g.group].intensity == g.intensity for g in definition if g.group in groups)

    def _reconcile(self) -> None:
        """Work out which theme (if any) the lights are showing."""
        data = self.coordinator.data
        candidates = {i for i, t in data.themes.items() if t.on and self._matches(i)}
        lights_off = all(not g.is_on for g in data.groups.values())
        if self._active is not None and self._active in candidates:
            self._off = False
        elif len(candidates) == 1:
            self._active, self._off = next(iter(candidates)), False
        else:
            # Changed by hand, or ambiguous: unselected, unless everything is off.
            self._active, self._off = None, lights_off

    @callback
    def _handle_coordinator_update(self) -> None:
        self._reconcile()
        super()._handle_coordinator_update()

    @property
    def options(self) -> list[str]:
        return [OPTION_OFF, *theme_options(self.coordinator)]

    @property
    def current_option(self) -> str | None:
        if self._off:
            return OPTION_OFF
        if self._active is None:
            return None
        for label, index in theme_options(self.coordinator).items():
            if index == self._active:
                return label
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        attrs: dict[str, Any] = {
            "themes": [
                {
                    "name": t.name,
                    "letter": theme_letter(t.index),
                    "theme_index": t.index,
                    "groups": [
                        {"group": g.group, "intensity": g.intensity, "color_slot": g.color}
                        for g in self.coordinator.theme_groups.get(t.index, [])
                    ],
                }
                for t in sorted(data.themes.values(), key=lambda t: t.index)
            ]
        }
        if self._active is not None and not self._off:
            attrs["theme_index"] = self._active
            attrs["theme_letter"] = theme_letter(self._active)
        return attrs

    # ---- control -----------------------------------------------------------

    async def async_select_option(self, option: str) -> None:
        client = self.coordinator.client
        try:
            if option == OPTION_OFF:
                await client.extinguish_all()
                self._active, self._off = None, True
                for theme in self.coordinator.data.themes.values():
                    theme.on = False
                for group in self.coordinator.data.groups.values():
                    group.intensity = 0
            else:
                index = theme_options(self.coordinator).get(option)
                if index is None:
                    raise ServiceValidationError(f"Unknown Luxor theme '{option}'")
                await client.illuminate_theme(index, True)
                self._active, self._off = index, False
                self.coordinator.data.themes[index].on = True
                for tg in self.coordinator.theme_groups.get(index, []):
                    if (group := self.coordinator.data.groups.get(tg.group)) is not None:
                        group.intensity = tg.intensity
        except LuxorError as err:
            raise HomeAssistantError(f"Failed to set theme {option}: {err}") from err
        self.async_write_ha_state()
        # Re-read theme definitions too, so a theme edited in the app isn't
        # mistaken for "changed by hand" right after it's applied.
        await self.coordinator.async_refresh_themes()
