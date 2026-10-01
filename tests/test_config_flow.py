"""Config flow tests."""

from __future__ import annotations

from ipaddress import ip_address

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fx_luxor.const import CONF_COLOR_GROUPS, CONF_SCAN_INTERVAL, DOMAIN

from .conftest import HOST

ZEROCONF = ZeroconfServiceInfo(
    ip_address=ip_address(HOST),
    ip_addresses=[ip_address(HOST)],
    hostname="lxtwo-000000001.local.",
    name="lxtwo-000000001._http._tcp.local.",
    port=80,
    type="_http._tcp.local.",
    properties={"path": "/index.htm"},
)
DHCP = DhcpServiceInfo(ip=HOST, hostname="lxtwo-000000001", macaddress="aabbccddeeff")


async def test_user_flow(hass: HomeAssistant, mock_controller) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "lxtwo-000000001"
    assert result["data"] == {CONF_HOST: HOST}
    assert result["result"].unique_id == "lxtwo-000000001"


async def test_user_flow_cannot_connect(hass: HomeAssistant, mock_controller) -> None:
    mock_controller.offline = True
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    mock_controller.offline = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_dhcp_discovery(hass: HomeAssistant, mock_controller) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=DHCP
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: HOST, CONF_MAC: "aa:bb:cc:dd:ee:ff"}


async def test_dhcp_updates_ip_of_existing(hass: HomeAssistant, mock_controller) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="lxtwo-000000001", data={CONF_HOST: "10.0.0.9"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_DHCP}, data=DHCP
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == HOST
    assert entry.data[CONF_MAC] == "aa:bb:cc:dd:ee:ff"


async def test_reconfigure(hass: HomeAssistant, mock_controller) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="lxtwo-000000001", data={CONF_HOST: "10.0.0.9"})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == HOST


async def test_reconfigure_wrong_controller(hass: HomeAssistant, mock_controller) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="lxtwo-999", data={CONF_HOST: "10.0.0.9"})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["reason"] == "wrong_controller"


async def test_options_flow(hass: HomeAssistant, mock_controller) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="lxtwo-000000001", data={CONF_HOST: HOST})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 30, CONF_COLOR_GROUPS: ["2"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_SCAN_INTERVAL: 30, CONF_COLOR_GROUPS: [2]}
    await hass.async_block_till_done()
    state = hass.states.get("light.group_2")
    assert state.attributes["supported_color_modes"] == ["hs"]


async def test_zeroconf_discovery(hass: HomeAssistant, mock_controller) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=ZEROCONF
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: HOST}


async def test_zeroconf_updates_ip_of_existing(hass: HomeAssistant, mock_controller) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="lxtwo-000000001", data={CONF_HOST: "10.0.0.9"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=ZEROCONF
    )
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == HOST
