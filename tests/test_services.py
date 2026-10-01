"""Theme management action tests."""

from __future__ import annotations

import pytest
from homeassistant.const import CONF_HOST, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fx_luxor.const import DOMAIN

from .conftest import HOST

PREFIX = "luxor_lxtwo_000000001"
NIGHT = f"switch.{PREFIX}_theme_nighttime"
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


async def test_create_theme(hass: HomeAssistant, entry, mock_controller) -> None:
    result = await _call(
        hass,
        "create_theme",
        {"name": "Party", "groups": [{"entity_id": G1, "brightness_pct": 40}, {"entity_id": G3}]},
        response=True,
    )
    assert result == {
        "theme_index": 1,
        "letter": "B",
        "name": "Party",
        "entity_id": f"switch.{PREFIX}_theme_party",
    }
    assert mock_controller.themes[1]["Name"] == "Party"
    assert mock_controller.theme_groups[1] == [
        {"GroupNumber": 1, "Intensity": 40, "Color": 0},
        {"GroupNumber": 3, "Intensity": 100, "Color": 0},
    ]
    state = hass.states.get(result["entity_id"])
    assert state.state == STATE_OFF
    assert state.attributes["theme_letter"] == "B"
    assert state.attributes["groups"][0] == {"group": 1, "intensity": 40, "color_slot": 0}

    await hass.services.async_call("switch", "turn_on", {"entity_id": result["entity_id"]}, blocking=True)
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
        await _call(hass, "create_theme", {"name": "X", "groups": [{"entity_id": NIGHT}]})


async def test_save_current_as_new_theme(hass: HomeAssistant, entry, mock_controller) -> None:
    await hass.services.async_call("light", "turn_on", {"entity_id": G2, "brightness": 128}, blocking=True)
    await hass.services.async_call("light", "turn_off", {"entity_id": G3}, blocking=True)
    result = await _call(hass, "save_current_as_theme", {"name": "Evening"}, response=True)
    assert mock_controller.theme_groups[result["theme_index"]] == [
        {"GroupNumber": 1, "Intensity": 10, "Color": 0},
        {"GroupNumber": 2, "Intensity": 50, "Color": 0},
        {"GroupNumber": 3, "Intensity": 0, "Color": 0},
    ]


async def test_save_current_overwrites_with_filter(hass: HomeAssistant, entry, mock_controller) -> None:
    await hass.services.async_call("light", "turn_on", {"entity_id": G2, "brightness": 255}, blocking=True)
    await _call(hass, "save_current_as_theme", {"entity_id": NIGHT, "lights": [G2]})
    assert mock_controller.theme_groups[0] == [{"GroupNumber": 2, "Intensity": 100, "Color": 0}]
    assert hass.states.get(NIGHT).attributes["groups"] == [{"group": 2, "intensity": 100, "color_slot": 0}]


async def test_save_current_needs_target(hass: HomeAssistant, entry) -> None:
    with pytest.raises(Exception, match="must contain at least one of"):
        await _call(hass, "save_current_as_theme", {})


async def test_update_theme(hass: HomeAssistant, entry, mock_controller) -> None:
    await _call(
        hass, "update_theme", {"entity_id": NIGHT, "groups": [{"entity_id": G3, "brightness_pct": 25}]}
    )
    assert mock_controller.theme_groups[0] == [{"GroupNumber": 3, "Intensity": 25, "Color": 0}]


async def test_rename_keeps_entity(hass: HomeAssistant, entry, mock_controller) -> None:
    await _call(hass, "rename_theme", {"entity_id": NIGHT, "name": "Late Night"})
    assert mock_controller.themes[0]["Name"] == "Late Night"
    assert hass.states.get(NIGHT).attributes["friendly_name"] == "Luxor lxtwo-000000001 Theme Late Night"


async def test_delete_theme(hass: HomeAssistant, entry, mock_controller) -> None:
    await _call(hass, "delete_theme", {"entity_id": NIGHT})
    assert 0 not in mock_controller.themes
    assert er.async_get(hass).async_get(NIGHT) is None
    await hass.async_block_till_done()
    assert hass.states.get(NIGHT) is None


async def test_restricted_controller(hass: HomeAssistant, entry, mock_controller) -> None:
    mock_controller.restricted = True
    with pytest.raises(HomeAssistantError, match="locked"):
        await _call(hass, "create_theme", {"name": "Nope"})
    assert hass.states.get(NIGHT).state == STATE_ON  # nothing else disturbed
