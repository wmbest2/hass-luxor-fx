"""Luxor light groups as Home Assistant lights."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import (
    COLOR_SLOT_MAX,
    COLOR_SLOT_MIN,
    Color,
    Group,
    LuxorError,
    dedicated_color_slot,
)
from .const import CONF_COLOR_GROUPS, DEFAULT_TURN_ON_INTENSITY
from .coordinator import LuxorConfigEntry, LuxorCoordinator
from .entity import LuxorEntity

PARALLEL_UPDATES = 1


def intensity_to_brightness(intensity: int) -> int:
    return round(max(0, min(100, intensity)) * 255 / 100)


def brightness_to_intensity(brightness: int) -> int:
    # Never round a non-zero brightness down to "off".
    return max(1, round(brightness * 100 / 255)) if brightness > 0 else 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    color_groups = set(entry.options.get(CONF_COLOR_GROUPS, []))
    known: set[int] = set()

    @callback
    def _add_new() -> None:
        new = [n for n in coordinator.data.groups if n not in known]
        known.update(new)
        async_add_entities(
            LuxorGroupLight(
                coordinator,
                n,
                color=coordinator.info.type.supports_color and n in color_groups,
            )
            for n in new
        )

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class LuxorGroupLight(LuxorEntity, LightEntity):
    """One Luxor light group."""

    _attr_name = None  # set from group name below

    def __init__(self, coordinator: LuxorCoordinator, number: int, *, color: bool) -> None:
        super().__init__(coordinator, f"group_{number}")
        self._number = number
        self._color = color
        self._last_intensity = DEFAULT_TURN_ON_INTENSITY
        mode = ColorMode.HS if color else ColorMode.BRIGHTNESS
        self._attr_color_mode = mode
        self._attr_supported_color_modes = {mode}

    @property
    def _group(self) -> Group | None:
        return self.coordinator.data.groups.get(self._number)

    @property
    def available(self) -> bool:
        return super().available and self._group is not None

    @property
    def name(self) -> str:
        group = self._group
        return group.name if group else f"Group {self._number}"

    @property
    def is_on(self) -> bool | None:
        group = self._group
        return group.is_on if group else None

    @property
    def brightness(self) -> int | None:
        group = self._group
        return intensity_to_brightness(group.intensity) if group else None

    @property
    def hs_color(self) -> tuple[float, float] | None:
        group = self._group
        if not self._color or group is None or group.color is None:
            return None
        if COLOR_SLOT_MIN <= group.color <= COLOR_SLOT_MAX:
            c = self.coordinator.data.colors.get(group.color)
            if c is not None:
                return (float(c.hue), float(c.saturation))
        return (0.0, 0.0)  # white / color wheel / DMX

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        group = self._group
        attrs: dict[str, Any] = {"group_number": self._number}
        if group is not None and group.color is not None:
            attrs["color_slot"] = group.color
            if group.color_wheel is not None:
                attrs["color_wheel"] = group.color_wheel
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        group = self._group
        if group is None:
            raise HomeAssistantError(f"Luxor group {self._number} no longer exists")
        client = self.coordinator.client

        if ATTR_BRIGHTNESS in kwargs:
            intensity = brightness_to_intensity(kwargs[ATTR_BRIGHTNESS])
        elif group.is_on:
            intensity = group.intensity
        else:
            intensity = self._last_intensity

        try:
            if self._color and ATTR_HS_COLOR in kwargs:
                hue, sat = kwargs[ATTR_HS_COLOR]
                slot = dedicated_color_slot(self._number)
                await client.set_color(slot, hue, sat)
                if group.color != slot:
                    await client.assign_group_color(group, slot)
                    group.color = slot
                colors = self.coordinator.data.colors
                if slot in colors:
                    colors[slot].hue, colors[slot].saturation = round(hue) % 360, round(sat)
                else:
                    colors[slot] = Color(slot=slot, hue=round(hue) % 360, saturation=round(sat))
            await client.illuminate_group(self._number, intensity)
        except LuxorError as err:
            raise HomeAssistantError(f"Failed to turn on {self.name}: {err}") from err

        group.intensity = intensity
        if intensity > 0:
            self._last_intensity = intensity
        await self._async_command_done()

    async def async_turn_off(self, **kwargs: Any) -> None:
        group = self._group
        if group is not None and group.is_on:
            self._last_intensity = group.intensity
        try:
            await self.coordinator.client.illuminate_group(self._number, 0)
        except LuxorError as err:
            raise HomeAssistantError(f"Failed to turn off {self.name}: {err}") from err
        if group is not None:
            group.intensity = 0
        await self._async_command_done()
