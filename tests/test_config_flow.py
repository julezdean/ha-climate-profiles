"""Tests for the config and options flow."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_profiles.config_flow import build_default_profiles
from custom_components.climate_profiles.const import (
    CONF_ADDITIONAL,
    CONF_CLIMATE_ENTITY,
    CONF_CUSTOM_NAME,
    CONF_PROFILE_COLOR,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_PROFILE_VALUES,
    CONF_PROFILES,
    DOMAIN,
)
from custom_components.climate_profiles.models import Capabilities

from .conftest import (
    CLIMATE,
    FAN,
    additional_option,
    set_device_state,
)


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
    assert result["step_id"] == "profiles"

    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"create_default_profiles": defaults}
    )


async def test_full_flow_creates_an_entry_with_starter_profiles(hass):
    set_device_state(hass)
    result = await run_config_flow(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Wohnzimmer"
    assert result["data"] == {CONF_CLIMATE_ENTITY: CLIMATE}
    names = [p[CONF_PROFILE_NAME] for p in result["options"][CONF_PROFILES]]
    assert names == ["Off", "Away", "Comfort", "Night", "Max"]
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
    profiles = build_default_profiles(caps)
    # Only the "off" profile survives, everything else needs cooling.
    assert [p.name for p in profiles] == ["Off"]


def test_default_profiles_clamp_to_the_devices_range():
    caps = Capabilities(
        hvac_modes=("off", "cool"),
        swing_modes=("off", "vertical"),
        min_temp=18,
        max_temp=30,
        temp_step=1,
    )
    profiles = build_default_profiles(caps)
    maximum = next(p for p in profiles if p.name == "Max")
    assert maximum.values["temperature"] == 18  # blueprint says 16


# --- options flow ----------------------------------------------------------


async def setup_options(hass, profiles=None, *, additional=True):
    """Set up an entry and open its options flow."""
    set_device_state(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wohnzimmer",
        data={CONF_CLIMATE_ENTITY: CLIMATE},
        options={
            CONF_PROFILES: profiles or [],
            CONF_CUSTOM_NAME: "Custom",
            CONF_ADDITIONAL: additional_option() if additional else [],
        },
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


async def test_adding_an_additional_value(hass):
    entry = await setup_options(hass, additional=False)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_value"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entity": FAN}
    )
    await hass.async_block_till_done()

    added = entry.options[CONF_ADDITIONAL]
    assert len(added) == 1
    assert added[0]["entity"] == FAN
    # No name given, so it is taken from the entity.
    assert added[0]["name"]
    assert added[0]["id"]


async def test_a_pre_filled_name_that_is_taken_gets_a_counter(hass):
    """Two switches are both called "Silent" without anybody deciding that."""
    entry = await setup_options(hass, additional=False)
    hass.states.async_set("switch.one", "off", {"friendly_name": "Silent"})
    hass.states.async_set("switch.two", "off", {"friendly_name": "Silent"})

    for entity_id in ("switch.one", "switch.two"):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": "add_value"}
        )
        await hass.config_entries.options.async_configure(
            result["flow_id"], {"entity": entity_id}
        )
        await hass.async_block_till_done()

    names = [value["name"] for value in entry.options[CONF_ADDITIONAL]]
    assert names == ["Silent", "Silent (2)"]


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
