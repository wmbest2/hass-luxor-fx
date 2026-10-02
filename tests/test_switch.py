"""Flash lights (assignment mode) diagnostic switch."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, STATE_OFF, STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.fx_luxor.const import DOMAIN
from custom_components.fx_luxor.switch import AUTO_OFF

from .conftest import HOST

PREFIX = "luxor_lxtwo_000000001"
SWITCH = f"switch.{PREFIX}_flash_lights_assignment_mode"
UNIQUE_ID = "lxtwo-000000001_flash_lights"


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="lxtwo-000000001", data={CONF_HOST: HOST})
    entry.add_to_hass(hass)
    return entry


async def _setup_enabled(hass: HomeAssistant) -> MockConfigEntry:
    """Pre-register the switch as enabled, then set up."""
    entry = _entry(hass)
    er.async_get(hass).async_get_or_create(
        "switch",
        DOMAIN,
        UNIQUE_ID,
        config_entry=entry,
        suggested_object_id=f"{PREFIX}_flash_lights_assignment_mode",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_disabled_by_default_and_diagnostic(hass: HomeAssistant, mock_controller) -> None:
    entry = _entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    reg = er.async_get(hass)
    entity_id = reg.async_get_entity_id("switch", DOMAIN, UNIQUE_ID)
    assert entity_id is not None
    entry_reg = reg.async_get(entity_id)
    assert entry_reg.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entry_reg.entity_category is EntityCategory.DIAGNOSTIC
    assert hass.states.get(entity_id) is None


async def test_turn_on_off(hass: HomeAssistant, mock_controller) -> None:
    await _setup_enabled(hass)
    state = hass.states.get(SWITCH)
    assert state.state == STATE_OFF
    assert state.attributes["assumed_state"] is True

    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    assert ("FlashLights", {"OnOff": 1}) in mock_controller.calls
    assert mock_controller.flashing
    assert hass.states.get(SWITCH).state == STATE_ON

    await hass.services.async_call("switch", "turn_off", {"entity_id": SWITCH}, blocking=True)
    assert ("FlashLights", {"OnOff": 0}) in mock_controller.calls
    assert not mock_controller.flashing
    assert all(g["Inten"] == 0 for g in mock_controller.groups.values())
    assert hass.states.get(SWITCH).state == STATE_OFF


async def test_extinguish_all_clears_state(hass: HomeAssistant, mock_controller) -> None:
    await _setup_enabled(hass)
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    await hass.services.async_call(
        "button", "press", {"entity_id": f"button.{PREFIX}_extinguish_all"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == STATE_OFF


async def test_auto_off(hass: HomeAssistant, mock_controller) -> None:
    await _setup_enabled(hass)
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    async_fire_time_changed(hass, dt_util.utcnow() + AUTO_OFF)
    await hass.async_block_till_done()
    assert not mock_controller.flashing
    assert hass.states.get(SWITCH).state == STATE_OFF


async def test_survives_legacy_switch_cleanup(hass: HomeAssistant, mock_controller) -> None:
    """Setup removes old per-theme switches but must keep this one (and its enabled state)."""
    entry = await _setup_enabled(hass)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH) is not None


async def test_theme_off_clears_state(hass: HomeAssistant, mock_controller) -> None:
    await _setup_enabled(hass)
    await hass.services.async_call("switch", "turn_on", {"entity_id": SWITCH}, blocking=True)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": f"select.{PREFIX}_theme", "option": "Off"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get(SWITCH).state == STATE_OFF
