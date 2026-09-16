"""Tests for the config and options flow."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_profiles.config_flow import build_default_profiles
from custom_components.climate_profiles.const import (
    CONF_CLIMATE_ENTITY,
    CONF_CUSTOM_NAME,
    CONF_DISPLAY_ENTITY,
    CONF_FAN_ENTITY,
    CONF_PROFILE_COLOR,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_PROFILE_VALUES,
    CONF_PROFILES,
    CONF_SILENT_ENTITY,
    DOMAIN,
)
from custom_components.climate_profiles.models import Capabilities, EntityMap

from .conftest import CLIMATE, DISPLAY, FAN, SILENT, set_device_state


async def run_config_flow(hass, *, optional=True, defaults=True):
    """Walk through the whole config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Wohnzimmer", CONF_CLIMATE_ENTITY: CLIMATE}
    )
    assert result["step_id"] == "entities"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_FAN_ENTITY: FAN,
            CONF_DISPLAY_ENTITY: DISPLAY,
            CONF_SILENT_ENTITY: SILENT,
        }
        if optional
        else {},
    )
    assert result["step_id"] == "profiles"

    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"create_default_profiles": defaults}
    )


async def test_full_flow_creates_an_entry_with_starter_profiles(hass):
    set_device_state(hass)
    result = await run_config_flow(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Wohnzimmer"
    assert result["data"] == {
        CONF_CLIMATE_ENTITY: CLIMATE,
        CONF_FAN_ENTITY: FAN,
        CONF_DISPLAY_ENTITY: DISPLAY,
        CONF_SILENT_ENTITY: SILENT,
    }
    names = [p[CONF_PROFILE_NAME] for p in result["options"][CONF_PROFILES]]
    assert names == ["Aus", "Away", "Komfort", "Nacht", "Max"]
    assert result["options"][CONF_CUSTOM_NAME] == "Custom"


async def test_optional_entities_may_be_skipped(hass):
    set_device_state(hass)
    result = await run_config_flow(hass, optional=False)

    assert result["data"] == {CONF_CLIMATE_ENTITY: CLIMATE}
    # No fan/display/silent entity -> no profile defines those values.
    for profile in result["options"][CONF_PROFILES]:
        assert not {"fan", "display", "silent"} & set(profile[CONF_PROFILE_VALUES])


async def test_starting_without_profiles(hass):
    set_device_state(hass)
    result = await run_config_flow(hass, defaults=False)
    assert result["options"][CONF_PROFILES] == []


async def test_unknown_entity_is_rejected(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Wohnzimmer", CONF_CLIMATE_ENTITY: "climate.gibt_es_nicht"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_CLIMATE_ENTITY: "entity_not_found"}


async def test_the_same_climate_entity_cannot_be_added_twice(hass):
    set_device_state(hass)
    MockConfigEntry(
        domain=DOMAIN, data={CONF_CLIMATE_ENTITY: CLIMATE}, unique_id=CLIMATE
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Nochmal", CONF_CLIMATE_ENTITY: CLIMATE}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# --- default profiles ------------------------------------------------------


def test_default_profiles_skip_what_the_device_cannot_do():
    caps = Capabilities(
        hvac_modes=("off", "heat"),  # no cool at all
        min_temp=17,
        max_temp=30,
        temp_step=0.5,
    )
    profiles = build_default_profiles(caps, EntityMap(climate=CLIMATE))
    # Only the "off" profile survives, everything else needs cooling.
    assert [p.name for p in profiles] == ["Aus"]


def test_default_profiles_clamp_to_the_devices_range():
    caps = Capabilities(
        hvac_modes=("off", "cool"),
        swing_modes=("off", "vertical"),
        min_temp=18,
        max_temp=30,
        temp_step=1,
    )
    profiles = build_default_profiles(caps, EntityMap(climate=CLIMATE))
    maximum = next(p for p in profiles if p.name == "Max")
    assert maximum.values["temperature"] == 18  # blueprint says 16


# --- options flow ----------------------------------------------------------


async def setup_options(hass, profiles=None):
    """Set up an entry and open its options flow."""
    set_device_state(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wohnzimmer",
        data={
            CONF_CLIMATE_ENTITY: CLIMATE,
            CONF_FAN_ENTITY: FAN,
            CONF_DISPLAY_ENTITY: DISPLAY,
            CONF_SILENT_ENTITY: SILENT,
        },
        options={CONF_PROFILES: profiles or [], CONF_CUSTOM_NAME: "Custom"},
        unique_id=CLIMATE,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_adding_a_profile(hass):
    entry = await setup_options(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_profile"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_PROFILE_NAME: "Nacht",
            CONF_PROFILE_COLOR: [139, 92, 246],
            "hvac_mode": "cool",
            "temperature": 26,
            "silent": "on",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    profiles = result["data"][CONF_PROFILES]
    assert len(profiles) == 1
    assert profiles[0][CONF_PROFILE_NAME] == "Nacht"
    assert profiles[0][CONF_PROFILE_COLOR] == "#8b5cf6"
    # Only what was filled in is stored - no implicit defaults.
    assert profiles[0][CONF_PROFILE_VALUES] == {
        "hvac_mode": "cool",
        "temperature": 26,
        "silent": "on",
    }


async def test_editing_keeps_the_id_and_can_clear_a_value(hass):
    stored = [
        {
            "id": "keep-me",
            "name": "Komfort",
            "color": "#22c55e",
            "values": {"hvac_mode": "cool", "temperature": 24, "fan_mode": "auto"},
        }
    ]
    entry = await setup_options(hass, stored)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "edit_profile"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PROFILE_ID: "keep-me"}
    )
    assert result["step_id"] == "edit_values"

    # Renamed, and fan_mode left empty -> the value is dropped.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_PROFILE_NAME: "Wohlfuehlen",
            CONF_PROFILE_COLOR: [34, 197, 94],
            "hvac_mode": "cool",
            "temperature": 24,
        },
    )
    profile = result["data"][CONF_PROFILES][0]
    assert profile[CONF_PROFILE_ID] == "keep-me"
    assert profile[CONF_PROFILE_NAME] == "Wohlfuehlen"
    assert profile[CONF_PROFILE_VALUES] == {"hvac_mode": "cool", "temperature": 24}


async def test_deleting_profiles(hass):
    stored = [
        {"id": "a", "name": "A", "color": "#111111", "values": {"hvac_mode": "off"}},
        {"id": "b", "name": "B", "color": "#222222", "values": {"hvac_mode": "cool"}},
    ]
    entry = await setup_options(hass, stored)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "delete_profile"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"selected": ["a"]}
    )
    assert [p[CONF_PROFILE_ID] for p in result["data"][CONF_PROFILES]] == ["b"]


async def test_reordering_profiles(hass):
    stored = [
        {"id": "a", "name": "A", "color": "#111111", "values": {"hvac_mode": "off"}},
        {"id": "b", "name": "B", "color": "#222222", "values": {"hvac_mode": "cool"}},
        {"id": "c", "name": "C", "color": "#333333", "values": {"hvac_mode": "dry"}},
    ]
    entry = await setup_options(hass, stored)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "reorder"}
    )
    # Only two of three picked: the rest keeps its relative position at the end.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"order": ["c", "b"]}
    )
    assert [p[CONF_PROFILE_ID] for p in result["data"][CONF_PROFILES]] == [
        "c",
        "b",
        "a",
    ]


async def test_changing_the_optional_entities(hass):
    entry = await setup_options(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "entities"}
    )
    # Clearing display and silent removes them from the entry's data.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_FAN_ENTITY: FAN}
    )
    await hass.async_block_till_done()

    assert entry.data == {CONF_CLIMATE_ENTITY: CLIMATE, CONF_FAN_ENTITY: FAN}


async def test_renaming_the_custom_profile(hass):
    entry = await setup_options(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "custom_name"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_CUSTOM_NAME: "Manuell"}
    )
    assert result["data"][CONF_CUSTOM_NAME] == "Manuell"
