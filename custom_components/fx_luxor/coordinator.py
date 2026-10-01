"""Polling coordinator for a Luxor controller."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ControllerInfo, LuxorClient, LuxorError, LuxorState, ThemeGroup
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, THEME_DETAIL_REFRESH_POLLS

_LOGGER = logging.getLogger(__name__)

type LuxorConfigEntry = ConfigEntry[LuxorCoordinator]


class LuxorCoordinator(DataUpdateCoordinator[LuxorState]):
    """Polls groups, themes and colors from one controller."""

    config_entry: LuxorConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: LuxorConfigEntry,
        client: LuxorClient,
        info: ControllerInfo,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {info.name}",
            update_interval=timedelta(seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self.client = client
        self.info = info
        self.theme_groups: dict[int, list[ThemeGroup]] = {}
        self._polls = 0
        self._force_theme_details = False

    async def _async_update_data(self) -> LuxorState:
        try:
            info = await self.client.controller_info()
            state = await self.client.state(info)
            # Keep the static parts of the info stable even if a later poll differs.
            self.info.rssi = info.rssi
            refresh_details = (
                self._force_theme_details
                or self._polls % THEME_DETAIL_REFRESH_POLLS == 0
                or set(state.themes) != set(self.theme_groups)
            )
            if refresh_details:
                self.theme_groups = {idx: await self.client.theme_groups(idx) for idx in state.themes}
                self._force_theme_details = False
        except LuxorError as err:
            raise UpdateFailed(str(err)) from err
        self._polls += 1
        return state

    async def async_refresh_themes(self) -> None:
        """Re-read everything, including theme definitions, right now."""
        self._force_theme_details = True
        await self.async_refresh()
