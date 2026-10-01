"""Theme management action tests."""

from __future__ import annotations

import pytest
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fx_luxor.const import DOMAIN

from .conftest import HOST

PREFIX = "luxor_lxtwo_000000001"
THEME = f"select.{PREFIX}_theme"
G1, G2, G3 = (f"light.group_{n}" for n in (1, 2, 3))


@pytest.fixture
async def entry(hass: HomeAssistant, mock_controller) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="lxtwo-000000001", data={CONF_HOST: HOST})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _call(hass, service, data, response=False):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=response or None
    )


def _themes(hass) -> dict[str, dict]:
    return {t["name"]: t for t in hass.states.get(THEME).attributes["themes"]}


async def test_create_theme(hass: HomeAssistant, entry, mock_controller) -> None:
    result = await _call(
        hass,
        "create_theme",
        {"name": "Party", "groups": [{"entity_id": G1, "brightness_pct": 40}, {"entity_id": G3}]},
        response=True,
    )
    assert result == {"theme_index": 1, "letter": "B", "name": "Party"}
    assert mock_controller.themes[1]["Name"] == "Party"
    assert mock_controller.theme_groups[1] == [
        {"GroupNumber": 1, "Intensity": 40, "Color": 0},
        {"GroupNumber": 3, "Intensity": 100, "Color": 0},
    ]
    state = hass.states.get(THEME)
    assert state.attributes["options"] == ["Off", "Nighttime", "Party"]
    assert _themes(hass)["Party"]["groups"][0] == {"group": 1, "intensity": 40, "color_slot": 0}

    await hass.services.async_call(
        "select", "select_option", {"entity_id": THEME, "option": "Party"}, blocking=True
    )
    assert mock_controller.groups[1]["Inten"] == 40


async def test_create_with_letter_and_conflicts(hass: HomeAssistant, entry, mock_controller) -> None:
    result = await _call(hass, "create_theme", {"name": "Late", "letter": "z"}, response=True)
    assert result["theme_index"] == 25 and mock_controller.theme_groups[25] == []
    with pytest.raises(ServiceValidationError, match="already used"):
        await _call(hass, "create_theme", {"name": "Other", "letter": "A"})
    with pytest.raises(ServiceValidationError, match="already exists"):
        await _call(hass, "create_theme", {"name": "nighttime"})


async def test_create_rejects_foreign_entity(hass: HomeAssistant, entry) -> None:
    with pytest.raises(ServiceValidationError, match="not a Luxor group"):
        await _call(hass, "create_theme", {"name": "X", "groups": [{"entity_id": THEME}]})


async def test_save_current_as_new_theme(hass: HomeAssistant, entry, mock_controller) -> None:
    await hass.services.async_call("light", "turn_on", {"entity_id": G2, "brightness": 128}, blocking=True)
    await hass.services.async_call("light", "turn_off", {"entity_id": G3}, blocking=True)
    result = await _call(hass, "save_current_as_theme", {"name": "Evening"}, response=True)
    assert mock_controller.theme_groups[result["theme_index"]] == [
        {"GroupNumber": 1, "Intensity": 10, "Color": 0},
        {"GroupNumber": 2, "Intensity": 50, "Color": 0},
        {"GroupNumber": 3, "Intensity": 0, "Color": 0},
    ]


async def test_save_current_overwrites_by_letter(hass: HomeAssistant, entry, mock_controller) -> None:
    await hass.services.async_call("light", "turn_on", {"entity_id": G2, "brightness": 255}, blocking=True)
    await _call(hass, "save_current_as_theme", {"theme": "a", "lights": [G2]})
    assert mock_controller.theme_groups[0] == [{"GroupNumber": 2, "Intensity": 100, "Color": 0}]
    assert _themes(hass)["Nighttime"]["groups"] == [{"group": 2, "intensity": 100, "color_slot": 0}]


async def test_save_current_needs_target(hass: HomeAssistant, entry) -> None:
    with pytest.raises(Exception, match="must contain at least one of"):
        await _call(hass, "save_current_as_theme", {})


async def test_unknown_theme(hass: HomeAssistant, entry) -> None:
    with pytest.raises(ServiceValidationError, match="Themes: A Nighttime"):
        await _call(hass, "delete_theme", {"theme": "Party"})


async def test_update_theme(hass: HomeAssistant, entry, mock_controller) -> None:
    groups = [{"entity_id": G3, "brightness_pct": 25}]
    await _call(hass, "update_theme", {"theme": "Nighttime", "groups": groups})
    assert mock_controller.theme_groups[0] == [{"GroupNumber": 3, "Intensity": 25, "Color": 0}]


async def test_rename_theme(hass: HomeAssistant, entry, mock_controller) -> None:
    await _call(hass, "rename_theme", {"theme": "NIGHTTIME", "name": "Late Night"})
    assert mock_controller.themes[0]["Name"] == "Late Night"
    state = hass.states.get(THEME)
    assert state.attributes["options"] == ["Off", "Late Night"]
    assert state.state == "Late Night"  # still the active theme


async def test_delete_theme(hass: HomeAssistant, entry, mock_controller) -> None:
    await _call(hass, "delete_theme", {"theme": "Nighttime"})
    assert 0 not in mock_controller.themes
    assert hass.states.get(THEME).attributes["options"] == ["Off"]


async def test_restricted_controller(hass: HomeAssistant, entry, mock_controller) -> None:
    mock_controller.restricted = True
    with pytest.raises(HomeAssistantError, match="locked"):
        await _call(hass, "create_theme", {"name": "Nope"})
    assert hass.states.get(THEME).state == "Nighttime"  # nothing else disturbed


async def test_explicit_color_slot(hass: HomeAssistant, entry, mock_controller) -> None:
    groups = [{"entity_id": G1, "brightness_pct": 50, "color_slot": 4}, {"entity_id": G2}]
    await _call(hass, "update_theme", {"theme": "A", "groups": groups})
    assert mock_controller.theme_groups[0] == [
        {"GroupNumber": 1, "Intensity": 50, "Color": 4},
        {"GroupNumber": 2, "Intensity": 100, "Color": 0},
    ]
    with pytest.raises(Exception, match="value must be at most 260"):
        await _call(hass, "update_theme", {"theme": "A", "groups": [{"entity_id": G1, "color_slot": 999}]})


def test_services_yaml_valid() -> None:
    """services.yaml passes HA's own schema and selector validation."""
    from pathlib import Path

    import yaml
    from homeassistant.helpers.service import _SERVICES_SCHEMA

    path = Path(__file__).parents[1] / "custom_components" / DOMAIN / "services.yaml"
    services = _SERVICES_SCHEMA(yaml.safe_load(path.read_text()))
    assert set(services) == {
        "create_theme",
        "save_current_as_theme",
        "update_theme",
        "rename_theme",
        "delete_theme",
    }
    fields = services["create_theme"]["fields"]["groups"]["selector"]["object"]["fields"]
    assert set(fields) == {"entity_id", "brightness_pct", "color_slot"}
