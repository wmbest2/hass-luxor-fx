"""Config flow for FX Luminaire Luxor."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import ControllerInfo, LuxorClient, LuxorError
from .const import (
    CONF_COLOR_GROUPS,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .coordinator import LuxorConfigEntry


class LuxorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._host: str | None = None
        self._info: ControllerInfo | None = None
        self._mac: str | None = None

    async def _probe(self, host: str) -> ControllerInfo:
        return await LuxorClient(host, async_get_clientsession(self.hass)).controller_info()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                info = await self._probe(host)
            except LuxorError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info.name)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(title=info.name, data={CONF_HOST: host})
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HOST): str}), user_input
            ),
            errors=errors,
        )

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """Controller seen on the network via its DHCP hostname (lxtwo-*, lxzdc-*, luxor-*)."""
        return await self._async_discovered(discovery_info.ip, format_mac(discovery_info.macaddress))

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """Controller advertised over mDNS as <name>._http._tcp.local."""
        if discovery_info.ip_address.version != 4:
            return self.async_abort(reason="not_ipv4_address")
        return await self._async_discovered(str(discovery_info.ip_address))

    async def _async_discovered(self, host: str, mac: str | None = None) -> ConfigFlowResult:
        try:
            info = await self._probe(host)
        except LuxorError:
            return self.async_abort(reason="cannot_connect")
        await self.async_set_unique_id(info.name)
        updates = {CONF_HOST: host} | ({CONF_MAC: mac} if mac else {})
        # Already set up: just follow the controller to its new IP.
        self._abort_if_unique_id_configured(updates=updates)
        self._host, self._info, self._mac = host, info, mac
        self.context["title_placeholders"] = {"name": info.name}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._host and self._info
        if user_input is not None:
            data = {CONF_HOST: self._host} | ({CONF_MAC: self._mac} if self._mac else {})
            return self.async_create_entry(title=self._info.name, data=data)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"name": self._info.name, "host": self._host},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                info = await self._probe(host)
            except LuxorError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info.name)
                self._abort_if_unique_id_mismatch(reason="wrong_controller")
                return self.async_update_reload_and_abort(entry, data_updates={CONF_HOST: host})
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema({vol.Required(CONF_HOST): str}), user_input or entry.data
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: LuxorConfigEntry) -> LuxorOptionsFlow:
        return LuxorOptionsFlow()


class LuxorOptionsFlow(OptionsFlowWithReload):
    """Polling interval and which groups have color fixtures."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            user_input[CONF_COLOR_GROUPS] = sorted(int(g) for g in user_input.get(CONF_COLOR_GROUPS, []))
            return self.async_create_entry(data=user_input)

        schema: dict[Any, Any] = {
            vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=3600)
            ),
        }
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is not None and coordinator.info.type.supports_color:
            options = [
                selector.SelectOptionDict(value=str(g.number), label=f"{g.number}: {g.name}")
                for g in sorted(coordinator.data.groups.values(), key=lambda g: g.number)
            ]
            schema[vol.Optional(CONF_COLOR_GROUPS, default=[])] = selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, multiple=True)
            )

        suggested = dict(self.config_entry.options)
        if CONF_COLOR_GROUPS in suggested:
            suggested[CONF_COLOR_GROUPS] = [str(g) for g in suggested[CONF_COLOR_GROUPS]]
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(vol.Schema(schema), suggested),
        )
