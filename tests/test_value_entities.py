"""Tests for the entities of the values each profile sets."""

from __future__ import annotations

from homeassistant.const import EntityCategory
from homeassistant.helpers import entity_registry as er

from custom_components.climate_profiles.const import CONF_PROFILES

from .conftest import set_device_state, settle
from .test_integration import PROFILES, SENSOR, setup_entry

KOMFORT_TEMPERATURE = "number.living_room_komfort_temperature"
KOMFORT_MODE = "select.living_room_komfort_mode"
KOMFORT_FAN_MODE = "select.living_room_komfort_fan_mode"
KOMFORT_DISPLAY = "switch.living_room_komfort_display"
KUEHLUNG_TEMPERATURE = "number.living_room_kuehlung_temperature"


def _profile(entry, profile_id: str) -> dict:
    return next(p for p in entry.options[CONF_PROFILES] if p["id"] == profile_id)


async def test_every_value_a_profile_sets_is_an_entity(hass, entry_data):
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    assert hass.states.get(KOMFORT_TEMPERATURE).state == "24.0"
    assert hass.states.get(KOMFORT_MODE).state == "cool"
    assert hass.states.get(KOMFORT_FAN_MODE).state == "auto"
    assert hass.states.get(KOMFORT_DISPLAY).state == "off"
    assert hass.states.get(KUEHLUNG_TEMPERATURE).state == "22.0"
    # The select offers what the device offers.
    assert hass.states.get(KOMFORT_MODE).attributes["options"] == [
        "off",
        "cool",
        "dry",
        "fan_only",
        "heat",
        "auto",
    ]
    # Settings: under Configuration on the device page.
    entry = er.async_get(hass).async_get(KOMFORT_TEMPERATURE)
    assert entry.entity_category is EntityCategory.CONFIG
    assert entry.disabled_by is None


async def test_a_value_the_profile_does_not_set_has_no_entity(hass, entry_data):
    """Kuehlung says nothing about the fan, so there is nothing to show."""
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    assert hass.states.get("select.living_room_kuehlung_fan_mode") is None
    assert hass.states.get("switch.living_room_kuehlung_display") is None
    assert hass.states.get("number.living_room_aus_temperature") is None


async def test_changing_a_value_of_another_profile_only_stores_it(
    hass, entry_data, calls
):
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": KUEHLUNG_TEMPERATURE, "value": 21},
        blocking=True,
    )
    await settle(hass)

    assert _profile(entry, "kuehlung")["values"]["temperature"] == 21
    assert hass.states.get(KUEHLUNG_TEMPERATURE).state == "21.0"
    assert not calls["set_temperature"]


async def test_changing_a_value_of_the_active_profile_applies_it(
    hass, entry_data, calls
):
    """Komfort is active - raised, it stays active and the device follows."""
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)
    assert hass.states.get(SENSOR).state == "Komfort"

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": KOMFORT_TEMPERATURE, "value": 25},
        blocking=True,
    )
    await settle(hass)

    assert _profile(entry, "komfort")["values"]["temperature"] == 25
    assert calls["set_temperature"][-1].data["temperature"] == 25
    # The device has not answered yet, it is mocked: the chosen profile is
    # shown while it is applied.
    assert entry.runtime_data._selected == "komfort"


async def test_write_protection_does_not_keep_the_entity_out(hass, entry_data):
    """Protection is about changes made on the device, not to the profile."""
    set_device_state(hass)
    profiles = [{**p, "protected": True} for p in PROFILES]
    entry = await setup_entry(hass, entry_data, profiles=profiles)

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": KUEHLUNG_TEMPERATURE, "value": 20},
        blocking=True,
    )
    await settle(hass)

    assert _profile(entry, "kuehlung")["values"]["temperature"] == 20


async def test_switches_and_selects_store_what_they_are_set_to(hass, entry_data):
    set_device_state(hass, hvac_mode="heat")
    entry = await setup_entry(hass, entry_data)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": KOMFORT_DISPLAY}, blocking=True
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": KOMFORT_FAN_MODE, "option": "high"},
        blocking=True,
    )
    await settle(hass)

    values = _profile(entry, "komfort")["values"]
    assert values["display"] == "on"
    assert values["fan_mode"] == "high"


async def test_an_option_the_device_no_longer_offers_is_unknown(hass, entry_data):
    set_device_state(hass)
    profiles = [
        *PROFILES,
        {
            "id": "turbo",
            "name": "Turbo",
            "values": {"hvac_mode": "cool", "fan_mode": "turbo", "temperature": 40},
        },
    ]
    await setup_entry(hass, entry_data, profiles=profiles)

    assert hass.states.get("select.living_room_turbo_fan_mode").state == "unknown"
    # Out of the device's range, so not something to pick either.
    assert hass.states.get("number.living_room_turbo_temperature").state == "unknown"


async def test_a_hidden_profile_has_entities_too(hass, entry_data):
    set_device_state(hass)
    profiles = [{**p, "hidden": True} if p["id"] == "kuehlung" else p for p in PROFILES]
    await setup_entry(hass, entry_data, profiles=profiles)

    assert hass.states.get(KUEHLUNG_TEMPERATURE).state == "22.0"


async def test_entities_follow_the_values_a_profile_sets(hass, entry_data):
    """Taken out, the entity goes; put in, it comes - without a reload."""
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)
    registry = er.async_get(hass)
    assert registry.async_get(KUEHLUNG_TEMPERATURE) is not None

    profiles = [
        {**p, "values": {"hvac_mode": "cool", "fan_mode": "low"}}
        if p["id"] == "kuehlung"
        else p
        for p in PROFILES
    ]
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_PROFILES: profiles}
    )
    await settle(hass)

    assert registry.async_get(KUEHLUNG_TEMPERATURE) is None
    assert hass.states.get("select.living_room_kuehlung_fan_mode").state == "low"


async def test_a_renamed_profile_renames_its_entities(hass, entry_data):
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)

    profiles = [{**p, "name": "Kalt"} if p["id"] == "kuehlung" else p for p in PROFILES]
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_PROFILES: profiles}
    )
    await settle(hass)

    state = hass.states.get(KUEHLUNG_TEMPERATURE)
    assert state.attributes["friendly_name"] == "Living room Kalt temperature"
