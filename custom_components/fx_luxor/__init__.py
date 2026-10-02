"""FX Luminaire Luxor integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import LuxorClient, LuxorError
from .const import DOMAIN
from .coordinator import LuxorConfigEntry, LuxorCoordinator
from .entity import controller_device_info
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register actions once for all controllers."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LuxorConfigEntry) -> bool:
    """Set up a Luxor controller from a config entry."""
    client = LuxorClient(entry.data[CONF_HOST], async_get_clientsession(hass))
    try:
        info = await client.controller_info()
    except LuxorError as err:
        raise ConfigEntryNotReady(f"Cannot reach Luxor controller: {err}") from err

    coordinator = LuxorCoordinator(hass, entry, client, info)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Register the controller first so group devices can hang off it.
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **controller_device_info(coordinator)
    )

    # Themes used to be one switch each (0.1.x); they're now a single selector.
    entities = er.async_get(hass)
    for reg in er.async_entries_for_config_entry(entities, entry.entry_id):
        if reg.domain == Platform.SWITCH and "_theme_" in reg.unique_id:
            entities.async_remove(reg.entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LuxorConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: LuxorConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow deleting a group device whose group no longer exists on the controller."""
    coordinator = entry.runtime_data
    prefix = f"{coordinator.info.name}_group_"
    for domain, ident in device.identifiers:
        if domain != DOMAIN:
            continue
        if ident == coordinator.info.name:
            return False  # never the controller itself
        if ident.startswith(prefix) and ident[len(prefix) :].isdigit():
            return int(ident[len(prefix) :]) not in coordinator.data.groups
    return True
