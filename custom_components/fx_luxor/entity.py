"""Base entity for Luxor."""

from __future__ import annotations

from homeassistant.const import CONF_MAC
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import LuxorCoordinator


class LuxorEntity(CoordinatorEntity[LuxorCoordinator]):
    """Entity attached to the controller device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: LuxorCoordinator, key: str) -> None:
        super().__init__(coordinator)
        info = coordinator.info
        self._attr_unique_id = f"{info.name}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, info.name)},
            manufacturer=MANUFACTURER,
            model=f"Luxor {info.type.value}",
            name=f"Luxor {info.name}",
            configuration_url=f"http://{coordinator.client.host}/",
        )
        if mac := coordinator.config_entry.data.get(CONF_MAC):
            # Lets HA's DHCP watcher track the controller's IP by MAC.
            self._attr_device_info["connections"] = {(CONNECTION_NETWORK_MAC, mac)}

    async def _async_command_done(self) -> None:
        """Push optimistic state, then re-poll soon to confirm."""
        self.coordinator.async_update_listeners()
        await self.coordinator.async_request_refresh()
