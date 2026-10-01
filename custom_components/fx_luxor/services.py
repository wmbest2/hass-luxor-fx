"""Theme management actions (create, save current, update, rename, delete)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .api import (
    THEME_INDEX_MAX,
    LuxorError,
    LuxorStatusError,
    ThemeGroup,
    clean_name,
    theme_letter,
)
from .const import DOMAIN
from .coordinator import LuxorConfigEntry, LuxorCoordinator

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_NAME = "name"
ATTR_LETTER = "letter"
ATTR_GROUPS = "groups"
ATTR_LIGHTS = "lights"
ATTR_BRIGHTNESS_PCT = "brightness_pct"

SERVICE_CREATE = "create_theme"
SERVICE_SAVE_CURRENT = "save_current_as_theme"
SERVICE_UPDATE = "update_theme"
SERVICE_RENAME = "rename_theme"
SERVICE_DELETE = "delete_theme"

STATUS_RESTRICTED = 252

_NAME = vol.All(cv.string, vol.Length(min=1))
_LETTER = vol.All(cv.string, vol.Upper, vol.Match(r"^[A-Z]$"))
_GROUPS = vol.All(
    cv.ensure_list,
    [
        vol.Schema(
            {
                vol.Required(ATTR_ENTITY_ID): cv.entity_id,
                vol.Optional(ATTR_BRIGHTNESS_PCT, default=100): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=100)
                ),
            }
        )
    ],
)

CREATE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_NAME): _NAME,
        vol.Optional(ATTR_LETTER): _LETTER,
        vol.Optional(ATTR_GROUPS, default=list): _GROUPS,
    }
)
SAVE_CURRENT_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
            vol.Exclusive(ATTR_ENTITY_ID, "target"): cv.entity_id,
            vol.Exclusive(ATTR_NAME, "target"): _NAME,
            vol.Optional(ATTR_LETTER): _LETTER,
            vol.Optional(ATTR_LIGHTS): cv.entity_ids,
        }
    ),
    cv.has_at_least_one_key(ATTR_ENTITY_ID, ATTR_NAME),
)
UPDATE_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id, vol.Required(ATTR_GROUPS): _GROUPS})
RENAME_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id, vol.Required(ATTR_NAME): _NAME})
DELETE_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): cv.entity_id})


# ---- lookups -----------------------------------------------------------------


def _loaded_entries(hass: HomeAssistant) -> list[LuxorConfigEntry]:
    return [e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED]


def _entry_from_call(hass: HomeAssistant, call: ServiceCall) -> LuxorConfigEntry:
    entries = _loaded_entries(hass)
    if entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID):
        for entry in entries:
            if entry.entry_id == entry_id:
                return entry
        raise ServiceValidationError(f"No loaded Luxor controller with config entry {entry_id}")
    if len(entries) == 1:
        return entries[0]
    if not entries:
        raise ServiceValidationError("No Luxor controller is set up")
    raise ServiceValidationError("Several Luxor controllers are set up; choose one with config_entry_id")


def _parse_entity(hass: HomeAssistant, entity_id: str, platform: Platform, key: str) -> tuple[str, int]:
    """Return (config_entry_id, number) for one of our group lights or theme switches."""
    reg = er.async_get(hass).async_get(entity_id)
    if reg is None or reg.platform != DOMAIN or reg.domain != platform or reg.config_entry_id is None:
        raise ServiceValidationError(f"{entity_id} is not a Luxor {key} {platform.value}")
    _, sep, number = reg.unique_id.rpartition(f"_{key}_")
    if not sep or not number.isdigit():
        raise ServiceValidationError(f"{entity_id} is not a Luxor {key} {platform.value}")
    return reg.config_entry_id, int(number)


def _theme_from_entity(hass: HomeAssistant, entity_id: str) -> tuple[LuxorCoordinator, int]:
    entry_id, index = _parse_entity(hass, entity_id, Platform.SWITCH, "theme")
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(f"The Luxor controller for {entity_id} is not loaded")
    coordinator: LuxorCoordinator = entry.runtime_data
    if index not in coordinator.data.themes:
        raise ServiceValidationError(f"Theme {theme_letter(index)} no longer exists on the controller")
    return coordinator, index


def _group_numbers(hass: HomeAssistant, coordinator: LuxorCoordinator, entity_ids: list[str]) -> list[int]:
    numbers = []
    for entity_id in entity_ids:
        entry_id, number = _parse_entity(hass, entity_id, Platform.LIGHT, "group")
        if entry_id != coordinator.config_entry.entry_id:
            raise ServiceValidationError(f"{entity_id} belongs to a different Luxor controller")
        if number not in coordinator.data.groups:
            raise ServiceValidationError(f"{entity_id} no longer exists on the controller")
        numbers.append(number)
    return numbers


def _groups_from_call(
    hass: HomeAssistant, coordinator: LuxorCoordinator, groups: list[dict[str, Any]]
) -> list[ThemeGroup]:
    numbers = _group_numbers(hass, coordinator, [g[ATTR_ENTITY_ID] for g in groups])
    current = coordinator.data.groups
    result: dict[int, ThemeGroup] = {}
    for number, spec in zip(numbers, groups, strict=True):
        # Keep the group's current color slot so a theme doesn't change colors by accident.
        result[number] = ThemeGroup(
            group=number, intensity=spec[ATTR_BRIGHTNESS_PCT], color=current[number].color
        )
    return list(result.values())


def _free_index(coordinator: LuxorCoordinator, letter: str | None) -> int:
    used = set(coordinator.data.themes)
    if letter is not None:
        index = ord(letter) - ord("A")
        if index in used:
            name = coordinator.data.themes[index].name
            raise ServiceValidationError(f"Theme {letter} is already used by '{name}'")
        return index
    for index in range(THEME_INDEX_MAX + 1):
        if index not in used:
            return index
    raise ServiceValidationError("All 26 theme slots (A-Z) are in use")


def _check_name_free(coordinator: LuxorCoordinator, name: str, *, ignore: int | None = None) -> str:
    name = clean_name(name)
    if not name:
        raise ServiceValidationError("Theme name can't be empty")
    for idx, theme in coordinator.data.themes.items():
        if idx != ignore and theme.name.casefold() == name.casefold():
            raise ServiceValidationError(f"A theme named '{theme.name}' already exists")
    return name


def _theme_entity_id(hass: HomeAssistant, coordinator: LuxorCoordinator, index: int) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        Platform.SWITCH, DOMAIN, f"{coordinator.info.name}_theme_{index}"
    )


async def _run(coordinator: LuxorCoordinator, action: Callable[[], Awaitable[None]]) -> None:
    """Run controller writes, translate errors, then re-read themes."""
    try:
        await action()
    except LuxorStatusError as err:
        if err.status == STATUS_RESTRICTED:
            raise HomeAssistantError(
                "Theme changes are locked on the Luxor controller. Turn off theme restriction "
                "in the controller's setup menu and try again."
            ) from err
        raise HomeAssistantError(str(err)) from err
    except LuxorError as err:
        raise HomeAssistantError(f"Could not reach the Luxor controller: {err}") from err
    finally:
        await coordinator.async_refresh_themes()


def _result(hass: HomeAssistant, coordinator: LuxorCoordinator, index: int) -> dict[str, Any]:
    theme = coordinator.data.themes.get(index)
    return {
        "theme_index": index,
        "letter": theme_letter(index),
        "name": theme.name if theme else None,
        "entity_id": _theme_entity_id(hass, coordinator, index),
    }


# ---- handlers ----------------------------------------------------------------


async def _create(call: ServiceCall) -> ServiceResponse:
    hass = call.hass
    coordinator: LuxorCoordinator = _entry_from_call(hass, call).runtime_data
    name = _check_name_free(coordinator, call.data[ATTR_NAME])
    index = _free_index(coordinator, call.data.get(ATTR_LETTER))
    groups = _groups_from_call(hass, coordinator, call.data[ATTR_GROUPS])
    color = coordinator.info.type.supports_color

    async def action() -> None:
        await coordinator.client.add_theme(index, name)
        if groups:
            await coordinator.client.set_theme_groups(index, groups, include_color=color)

    await _run(coordinator, action)
    await hass.async_block_till_done()  # let the new switch register
    return _result(hass, coordinator, index)


async def _save_current(call: ServiceCall) -> ServiceResponse:
    hass = call.hass
    if entity_id := call.data.get(ATTR_ENTITY_ID):
        coordinator, index = _theme_from_entity(hass, entity_id)
        new_name = None
    else:
        coordinator = _entry_from_call(hass, call).runtime_data
        new_name = _check_name_free(coordinator, call.data[ATTR_NAME])
        index = _free_index(coordinator, call.data.get(ATTR_LETTER))

    groups = coordinator.data.groups
    if lights := call.data.get(ATTR_LIGHTS):
        numbers = _group_numbers(hass, coordinator, lights)
    else:
        numbers = sorted(groups)
    snapshot = [ThemeGroup(group=n, intensity=groups[n].intensity, color=groups[n].color) for n in numbers]
    color = coordinator.info.type.supports_color

    async def action() -> None:
        if new_name is not None:
            await coordinator.client.add_theme(index, new_name)
        await coordinator.client.set_theme_groups(index, snapshot, include_color=color)

    await _run(coordinator, action)
    await hass.async_block_till_done()
    return _result(hass, coordinator, index)


async def _update(call: ServiceCall) -> None:
    hass = call.hass
    coordinator, index = _theme_from_entity(hass, call.data[ATTR_ENTITY_ID])
    groups = _groups_from_call(hass, coordinator, call.data[ATTR_GROUPS])
    color = coordinator.info.type.supports_color
    await _run(coordinator, lambda: coordinator.client.set_theme_groups(index, groups, include_color=color))


async def _rename(call: ServiceCall) -> None:
    hass = call.hass
    coordinator, index = _theme_from_entity(hass, call.data[ATTR_ENTITY_ID])
    old = coordinator.data.themes[index].name
    new = _check_name_free(coordinator, call.data[ATTR_NAME], ignore=index)
    if new == old:
        return
    await _run(coordinator, lambda: coordinator.client.rename_theme(old, new))


async def _delete(call: ServiceCall) -> None:
    hass = call.hass
    entity_id = call.data[ATTR_ENTITY_ID]
    coordinator, index = _theme_from_entity(hass, entity_id)
    name = coordinator.data.themes[index].name
    await _run(coordinator, lambda: coordinator.client.delete_theme(name))
    if index not in coordinator.data.themes:
        er.async_get(hass).async_remove(entity_id)


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions (once, not per controller)."""
    hass.services.async_register(
        DOMAIN, SERVICE_CREATE, _create, schema=CREATE_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SAVE_CURRENT,
        _save_current,
        schema=SAVE_CURRENT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICE_UPDATE, _update, schema=UPDATE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RENAME, _rename, schema=RENAME_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_DELETE, _delete, schema=DELETE_SCHEMA)
