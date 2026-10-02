"""Controller-wide buttons."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import LuxorClient, LuxorError
from .coordinator import LuxorConfigEntry, LuxorCoordinator
from .entity import LuxorEntity

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class LuxorButtonDescription(ButtonEntityDescription):
    press_fn: Callable[[LuxorClient], Awaitable[None]]


BUTTONS: tuple[LuxorButtonDescription, ...] = (
    LuxorButtonDescription(
        key="illuminate_all",
        translation_key="illuminate_all",
        press_fn=lambda c: c.illuminate_all(),
    ),
    LuxorButtonDescription(
        key="extinguish_all",
        translation_key="extinguish_all",
        press_fn=lambda c: c.extinguish_all(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LuxorConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(LuxorButton(entry.runtime_data, d) for d in BUTTONS)


class LuxorButton(LuxorEntity, ButtonEntity):
    entity_description: LuxorButtonDescription

    def __init__(self, coordinator: LuxorCoordinator, description: LuxorButtonDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        try:
            await self.entity_description.press_fn(self.coordinator.client)
        except LuxorError as err:
            raise HomeAssistantError(str(err)) from err
        await self._async_command_done()
