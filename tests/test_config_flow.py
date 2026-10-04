"""Tests for the config and options flow."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_profiles.const import (
    CONF_ADDITIONAL,
    CONF_CLIMATE_ENTITY,
    CONF_CUSTOM_COLOR,
    CONF_CUSTOM_ICON,
    CONF_CUSTOM_NAME,
    CONF_PROFILE_CAPTURE,
    CONF_PROFILE_COLOR,
    CONF_PROFILE_DETECT,
    CONF_PROFILE_ICON,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_PROFILE_VALUES,
    CONF_PROFILES,
    DOMAIN,
)

from .conftest import (
    CLIMATE,
    FAN,
    additional_option,
    open_step,
    set_device_state,
)


async def run_config_flow(hass):
    """Walk through the whole config flow - one step, and it is done."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Wohnzimmer", CONF_CLIMATE_ENTITY: CLIMATE}
    )


async def test_the_flow_creates_an_entry_without_profiles(hass):
    """Setup is one form: no starter set is invented for the device."""
    set_device_state(hass)
    result = await run_config_flow(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Wohnzimmer"
    assert result["data"] == {CONF_CLIMATE_ENTITY: CLIMATE}
    assert result["options"][CONF_PROFILES] == []
    assert result["options"][CONF_CUSTOM_NAME] == "Custom"


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


async def test_a_new_entry_for_the_same_entity_starts_empty(hass):
    """Deleting an entry takes its profiles with it - they live in its options."""
    set_device_state(hass)
    from .test_integration import PROFILES, setup_entry

    entry = await setup_entry(hass, {CONF_CLIMATE_ENTITY: CLIMATE}, profiles=PROFILES)
    assert len(entry.options[CONF_PROFILES]) == len(PROFILES)

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    result = await run_config_flow(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_PROFILES] == []


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


# --- the profile list ------------------------------------------------------


def custom_fields() -> dict:
    """Return the three "custom" fields, which the profile form always carries."""
    return {
        CONF_CUSTOM_NAME: "Custom",
        CONF_CUSTOM_COLOR: [120, 144, 156],
    }


async def submit_profiles(hass, entry, rows, **extra):
    """Submit the profile list as the form hands it back."""
    result = await open_step(hass, entry, "profiles")
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PROFILES: rows, **custom_fields(), **extra}
    )


async def submit_values(hass, entry, rows, **extra):
    """Submit the value list as the form hands it back."""
    result = await open_step(hass, entry, "values")
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ADDITIONAL: rows, **extra}
    )


async def test_the_menu_has_the_two_lists(hass):
    entry = await setup_options(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {"values", "profiles"}


async def test_adding_a_profile(hass):
    """A row without an id is a new profile - that is what the + button adds."""
    entry = await setup_options(hass)

    result = await submit_profiles(
        hass,
        entry,
        [
            {
                CONF_PROFILE_NAME: "Nacht",
                CONF_PROFILE_COLOR: [139, 92, 246],
                CONF_PROFILE_CAPTURE: "ask",
                "hvac_mode": "cool",
                "temperature": 26,
                "silent": "on",
            }
        ],
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    profiles = result["data"][CONF_PROFILES]
    assert len(profiles) == 1
    assert profiles[0][CONF_PROFILE_NAME] == "Nacht"
    assert profiles[0][CONF_PROFILE_COLOR] == "#8b5cf6"
    assert profiles[0][CONF_PROFILE_ID]
    # Only what was filled in is stored - no implicit defaults.
    assert profiles[0][CONF_PROFILE_VALUES] == {
        "hvac_mode": "cool",
        "temperature": 26,
        "silent": "on",
    }


async def test_the_list_shows_what_is_stored(hass):
    """Every profile is a row, with its values in it and its id read only."""
    stored = [
        {
            "id": "keep-me",
            "name": "Komfort",
            "color": "#22c55e",
            "icon": "mdi:sofa",
            "values": {"hvac_mode": "cool", "temperature": 24},
        }
    ]
    entry = await setup_options(hass, stored)

    result = await open_step(hass, entry, "profiles")

    schema = result["data_schema"].schema
    rows = next(
        key.description["suggested_value"] for key in schema if key == CONF_PROFILES
    )
    assert rows == [
        {
            CONF_PROFILE_NAME: "Komfort",
            CONF_PROFILE_COLOR: [34, 197, 94],
            CONF_PROFILE_ICON: "mdi:sofa",
            CONF_PROFILE_DETECT: True,
            CONF_PROFILE_CAPTURE: "ask",
            CONF_PROFILE_ID: "keep-me",
            "hvac_mode": "cool",
            "temperature": 24,
        }
    ]
    # One field per value the entry knows, the additional ones included.
    fields = schema[CONF_PROFILES].config["fields"]
    assert "fan" in fields
    assert fields["hvac_mode"]["required"] is True
    # Required, so a new row opens with the first option - "ask" - picked.
    assert fields[CONF_PROFILE_CAPTURE]["required"] is True
    assert fields[CONF_PROFILE_CAPTURE]["selector"]["select"]["options"][0] == "ask"
    # The id rides along in the row but has no field: nothing to edit, and
    # nothing to mistype. `read_only` would not help - the frontend's text
    # selector ignores it and draws an ordinary box.
    assert CONF_PROFILE_ID not in fields


async def test_a_row_may_carry_its_hidden_id(hass):
    """It is no field, so the stock validator would refuse it as "not allowed"."""
    stored = [
        {
            "id": "keep-me",
            "name": "Komfort",
            "color": "#22c55e",
            "values": {"hvac_mode": "cool"},
        }
    ]
    entry = await setup_options(hass, stored)
    result = await open_step(hass, entry, "profiles")

    rows = next(
        key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key == CONF_PROFILES
    )
    # What the form hands out is what it has to accept back.
    assert result["data_schema"]({CONF_PROFILES: rows, **custom_fields()})


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

    # Renamed, and fan_mode cleared -> the value is dropped.
    result = await submit_profiles(
        hass,
        entry,
        [
            {
                CONF_PROFILE_ID: "keep-me",
                CONF_PROFILE_NAME: "Wohlfuehlen",
                CONF_PROFILE_COLOR: [34, 197, 94],
                CONF_PROFILE_CAPTURE: "ask",
                "hvac_mode": "cool",
                "temperature": 24,
            }
        ],
    )
    profile = result["data"][CONF_PROFILES][0]
    assert profile[CONF_PROFILE_ID] == "keep-me"
    assert profile[CONF_PROFILE_NAME] == "Wohlfuehlen"
    assert profile[CONF_PROFILE_VALUES] == {"hvac_mode": "cool", "temperature": 24}


async def test_deleting_a_profile_is_a_row_that_is_gone(hass):
    stored = [
        {"id": "a", "name": "A", "color": "#111111", "values": {"hvac_mode": "off"}},
        {"id": "b", "name": "B", "color": "#222222", "values": {"hvac_mode": "cool"}},
    ]
    entry = await setup_options(hass, stored)

    result = await submit_profiles(
        hass,
        entry,
        [
            {
                CONF_PROFILE_ID: "b",
                CONF_PROFILE_NAME: "B",
                CONF_PROFILE_COLOR: [34, 34, 34],
                CONF_PROFILE_CAPTURE: "ask",
                "hvac_mode": "cool",
            }
        ],
    )
    assert [p[CONF_PROFILE_ID] for p in result["data"][CONF_PROFILES]] == ["b"]


async def test_the_order_of_the_rows_is_the_order(hass):
    stored = [
        {"id": "a", "name": "A", "color": "#111111", "values": {"hvac_mode": "off"}},
        {"id": "b", "name": "B", "color": "#222222", "values": {"hvac_mode": "cool"}},
        {"id": "c", "name": "C", "color": "#333333", "values": {"hvac_mode": "dry"}},
    ]
    entry = await setup_options(hass, stored)

    result = await submit_profiles(
        hass,
        entry,
        [
            {
                CONF_PROFILE_ID: pid,
                CONF_PROFILE_NAME: pid.upper(),
                CONF_PROFILE_COLOR: [17, 17, 17],
                CONF_PROFILE_CAPTURE: "ask",
                "hvac_mode": mode,
            }
            for pid, mode in (("c", "dry"), ("b", "cool"), ("a", "off"))
        ],
    )
    assert [p[CONF_PROFILE_ID] for p in result["data"][CONF_PROFILES]] == [
        "c",
        "b",
        "a",
    ]


async def test_a_row_without_a_mode_is_refused(hass):
    """`hvac_mode` is the one value a profile has to name.

    The selector enforces it, so the row never reaches the flow - which is
    why this asserts on the refusal rather than on an error message.
    """
    entry = await setup_options(hass)

    with pytest.raises(InvalidData):
        await submit_profiles(
            hass,
            entry,
            [
                {
                    CONF_PROFILE_NAME: "Leer",
                    CONF_PROFILE_COLOR: [1, 2, 3],
                    CONF_PROFILE_CAPTURE: "ask",
                }
            ],
        )


async def test_editing_the_custom_profile(hass):
    """It has no values, but it is a button on the card like any other."""
    entry = await setup_options(hass)

    result = await submit_profiles(
        hass,
        entry,
        [],
        **{
            CONF_CUSTOM_NAME: "Manuell",
            CONF_CUSTOM_COLOR: [139, 92, 246],
            CONF_CUSTOM_ICON: "mdi:hand-back-right",
        },
    )
    assert result["data"][CONF_CUSTOM_NAME] == "Manuell"
    assert result["data"][CONF_CUSTOM_COLOR] == "#8b5cf6"
    assert result["data"][CONF_CUSTOM_ICON] == "mdi:hand-back-right"


# --- the value list --------------------------------------------------------


async def test_adding_an_additional_value(hass):
    entry = await setup_options(hass, additional=False)

    await submit_values(hass, entry, [{"entity": FAN}])
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

    await submit_values(
        hass, entry, [{"entity": "switch.one"}, {"entity": "switch.two"}]
    )
    await hass.async_block_till_done()

    names = [value["name"] for value in entry.options[CONF_ADDITIONAL]]
    assert names == ["Silent", "Silent (2)"]


async def test_a_value_pointing_at_nothing_is_refused(hass):
    entry = await setup_options(hass, additional=False)

    result = await submit_values(hass, entry, [{"entity": "number.gibt_es_nicht"}])

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_ADDITIONAL: "entity_not_found"}
