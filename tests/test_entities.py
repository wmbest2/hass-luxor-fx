"""Entity behaviour tests."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fx_luxor.const import CONF_COLOR_GROUPS, DOMAIN

from .conftest import HOST

PREFIX = "luxor_lxtwo_000000001"


async def _setup(hass: HomeAssistant, options: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="lxtwo-000000001", data={CONF_HOST: HOST}, options=options or {}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities_created(hass: HomeAssistant, mock_controller) -> None:
    await _setup(hass)
    g1 = hass.states.get(f"light.{PREFIX}_group_1")
    assert g1.state == STATE_ON
    assert g1.attributes["brightness"] == 26  # 10%
    assert g1.attributes["supported_color_modes"] == ["brightness"]
    assert hass.states.get(f"switch.{PREFIX}_theme_nighttime").state == STATE_ON
    assert hass.states.get(f"switch.{PREFIX}_theme_nighttime").attributes["groups"][2] == {
        "group": 3,
        "intensity": 100,
        "color_slot": 0,
    }
    assert hass.states.get(f"button.{PREFIX}_illuminate_all") is not None
    assert hass.states.get(f"sensor.{PREFIX}_wi_fi_signal").state == "44"


async def test_light_brightness_and_off(hass: HomeAssistant, mock_controller) -> None:
    await _setup(hass)
    eid = f"light.{PREFIX}_group_2"
    await hass.services.async_call("light", "turn_on", {"entity_id": eid, "brightness": 128}, blocking=True)
    assert mock_controller.groups[2]["Inten"] == 50
    await hass.services.async_call("light", "turn_off", {"entity_id": eid}, blocking=True)
    assert mock_controller.groups[2]["Inten"] == 0
    assert hass.states.get(eid).state == STATE_OFF
    # Plain turn_on restores the previous level.
    await hass.services.async_call("light", "turn_on", {"entity_id": eid}, blocking=True)
    assert mock_controller.groups[2]["Inten"] == 50


async def test_light_color_uses_dedicated_slot(hass: HomeAssistant, mock_controller) -> None:
    await _setup(hass, {CONF_COLOR_GROUPS: [1]})
    eid = f"light.{PREFIX}_group_1"
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": eid, "hs_color": (120, 60), "brightness": 255}, blocking=True
    )
    assert mock_controller.colors[250] == {"C": 250, "Hue": 120, "Sat": 60}
    assert mock_controller.groups[1]["Colr"] == 250
    assert mock_controller.groups[1]["Inten"] == 100
    state = hass.states.get(eid)
    assert state.attributes["hs_color"] == (120.0, 60.0)
    assert state.attributes["color_slot"] == 250
    # Other groups and user presets untouched.
    assert mock_controller.groups[2]["Colr"] == 0
    assert mock_controller.colors[1] == {"C": 1, "Hue": 43, "Sat": 38}


async def test_theme_switch(hass: HomeAssistant, mock_controller) -> None:
    await _setup(hass)
    eid = f"switch.{PREFIX}_theme_nighttime"
    await hass.services.async_call("switch", "turn_off", {"entity_id": eid}, blocking=True)
    assert hass.states.get(eid).state == STATE_OFF
    assert all(g["Inten"] == 0 for g in mock_controller.groups.values())
    await hass.services.async_call("switch", "turn_on", {"entity_id": eid}, blocking=True)
    assert hass.states.get(eid).state == STATE_ON
    assert mock_controller.groups[3]["Inten"] == 100


async def test_buttons(hass: HomeAssistant, mock_controller) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "button", "press", {"entity_id": f"button.{PREFIX}_extinguish_all"}, blocking=True
    )
    assert all(g["Inten"] == 0 for g in mock_controller.groups.values())
    await hass.services.async_call(
        "button", "press", {"entity_id": f"button.{PREFIX}_illuminate_all"}, blocking=True
    )
    assert all(g["Inten"] == 75 for g in mock_controller.groups.values())


async def test_not_ready_when_offline(hass: HomeAssistant, mock_controller) -> None:
    mock_controller.offline = True
    entry = MockConfigEntry(domain=DOMAIN, unique_id="lxtwo-000000001", data={CONF_HOST: HOST})
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_goes_unavailable(hass: HomeAssistant, mock_controller) -> None:
    entry = await _setup(hass)
    mock_controller.offline = True
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(f"light.{PREFIX}_group_1").state == STATE_UNAVAILABLE


async def test_diagnostics_and_unload(hass: HomeAssistant, mock_controller) -> None:
    from custom_components.fx_luxor.diagnostics import async_get_config_entry_diagnostics

    entry = await _setup(hass)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["entry"]["data"][CONF_HOST] == "**REDACTED**"
    assert diag["state"]["groups"][1]["name"] == "Group 1"
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
