"""FX Luminaire Luxor integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import LuxorClient, LuxorError
from .coordinator import LuxorConfigEntry, LuxorCoordinator

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]


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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LuxorConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
