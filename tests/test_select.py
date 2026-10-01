"""Theme selector tests."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_restore_cache

from custom_components.fx_luxor.const import DOMAIN

from .conftest import HOST

THEME = "select.luxor_lxtwo_000000001_theme"


def _add_themes(fake) -> None:
    fake.themes[1] = {"Name": "All On", "ThemeIndex": 1, "OnOff": 0}
    fake.theme_groups[1] = [{"GroupNumber": n, "Intensity": 100, "Color": 0} for n in (1, 2, 3)]
    fake.themes[2] = {"Name": "Gloomy Day", "ThemeIndex": 2, "OnOff": 0}
    fake.theme_groups[2] = [
        {"GroupNumber": 1, "Intensity": 0, "Color": 0},
        {"GroupNumber": 2, "Intensity": 0, "Color": 0},
        {"GroupNumber": 3, "Intensity": 100, "Color": 0},
    ]


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="lxtwo-000000001", data={CONF_HOST: HOST})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _select(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call(
        "select", "select_option", {"entity_id": THEME, "option": option}, blocking=True
    )


async def test_options_and_initial_state(hass: HomeAssistant, mock_controller) -> None:
    _add_themes(mock_controller)
    await _setup(hass)
    state = hass.states.get(THEME)
    assert state.attributes["options"] == ["Off", "Nighttime", "All On", "Gloomy Day"]
    assert state.state == "Nighttime"  # the only theme flagged on
    assert state.attributes["theme_letter"] == "A"
    assert [t["letter"] for t in state.attributes["themes"]] == ["A", "B", "C"]


async def test_only_one_theme_shown_active(hass: HomeAssistant, mock_controller) -> None:
    """The controller leaves earlier themes flagged on; the selector shows the last one."""
    _add_themes(mock_controller)
    await _setup(hass)
    await _select(hass, "All On")
    await _select(hass, "Gloomy Day")
    assert all(t["OnOff"] == 1 for t in mock_controller.themes.values())  # controller quirk
    assert hass.states.get(THEME).state == "Gloomy Day"
    assert [g["Inten"] for g in mock_controller.groups.values()] == [0, 0, 100]
    await _select(hass, "All On")
    assert hass.states.get(THEME).state == "All On"
    assert [g["Inten"] for g in mock_controller.groups.values()] == [100, 100, 100]


async def test_off_extinguishes_all(hass: HomeAssistant, mock_controller) -> None:
    _add_themes(mock_controller)
    await _setup(hass)
    await _select(hass, "Off")
    assert all(g["Inten"] == 0 for g in mock_controller.groups.values())
    assert all(t["OnOff"] == 0 for t in mock_controller.themes.values())
    assert hass.states.get(THEME).state == "Off"
    assert "theme_index" not in hass.states.get(THEME).attributes


async def test_manual_change_clears_selection(hass: HomeAssistant, mock_controller) -> None:
    await _setup(hass)
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.group_3", "brightness": 128}, blocking=True
    )
    state = hass.states.get(THEME)
    assert state.state == STATE_UNKNOWN
    assert "theme_index" not in state.attributes
    # Putting the light back to the theme's level selects the theme again.
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": "light.group_3", "brightness": 255}, blocking=True
    )
    assert hass.states.get(THEME).state == "Nighttime"


async def test_reapply_after_manual_change(hass: HomeAssistant, mock_controller) -> None:
    await _setup(hass)
    await hass.services.async_call("light", "turn_off", {"entity_id": "light.group_1"}, blocking=True)
    assert hass.states.get(THEME).state == STATE_UNKNOWN
    await _select(hass, "Nighttime")
    assert hass.states.get(THEME).state == "Nighttime"
    assert mock_controller.groups[1]["Inten"] == 10


async def test_all_lights_off_by_hand_shows_off(hass: HomeAssistant, mock_controller) -> None:
    await _setup(hass)
    for n in (1, 2, 3):
        await hass.services.async_call("light", "turn_off", {"entity_id": f"light.group_{n}"}, blocking=True)
    assert hass.states.get(THEME).state == "Off"


async def test_ambiguous_without_history(hass: HomeAssistant, mock_controller) -> None:
    _add_themes(mock_controller)
    mock_controller.theme_groups[2] = mock_controller.theme_groups[1]  # same levels as All On
    for t in mock_controller.themes.values():
        t["OnOff"] = 1
    for g in mock_controller.groups.values():
        g["Inten"] = 100
    await _setup(hass)
    assert hass.states.get(THEME).state == STATE_UNKNOWN  # B and C both match


async def test_restores_last_choice(hass: HomeAssistant, mock_controller) -> None:
    _add_themes(mock_controller)
    mock_controller.theme_groups[2] = mock_controller.theme_groups[1]
    for t in mock_controller.themes.values():
        t["OnOff"] = 1
    for g in mock_controller.groups.values():
        g["Inten"] = 100
    mock_restore_cache(hass, [State(THEME, "Gloomy Day", {"theme_index": 2})])
    await _setup(hass)
    assert hass.states.get(THEME).state == "Gloomy Day"


async def test_picked_on_facepack(hass: HomeAssistant, mock_controller) -> None:
    _add_themes(mock_controller)
    entry = await _setup(hass)
    # Extinguish all, then theme C pressed on the facepack.
    mock_controller.handle("ExtinguishAll", {})
    mock_controller.handle("IlluminateTheme", {"ThemeIndex": 2, "OnOff": 1})
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(THEME).state == "Gloomy Day"


async def test_old_theme_switches_removed(hass: HomeAssistant, mock_controller) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="lxtwo-000000001", data={CONF_HOST: HOST})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "switch", DOMAIN, "lxtwo-000000001_theme_0", config_entry=entry, suggested_object_id="old_theme"
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(old.entity_id) is None
    assert hass.states.get(THEME) is not None
