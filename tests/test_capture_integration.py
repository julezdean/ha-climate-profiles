"""Capturing the current state back into a profile, end to end."""

from __future__ import annotations

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.climate_profiles.const import (
    CONF_PROFILES,
    DOMAIN,
)

from .conftest import set_device_state, settle
from .test_integration import PROFILES, SENSOR, setup_entry


def stored(entry) -> list[dict]:
    """Return the profiles as they are persisted right now."""
    return entry.options[CONF_PROFILES]


def by_name(entry, name: str) -> dict:
    """Return one stored profile."""
    return next(p for p in stored(entry) if p["name"] == name)


async def capture(hass, **data):
    """Call the capture service."""
    await hass.services.async_call(
        DOMAIN, "capture_profile", {"entity_id": SENSOR, **data}, blocking=True
    )
    await settle(hass)


# --- capturing into the profile you were in --------------------------------


async def test_a_manual_change_is_written_into_the_active_profile(hass, entry_data):
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)
    assert hass.states.get(SENSOR).state == "Komfort"

    set_device_state(hass, temperature=23)
    await settle(hass)
    assert hass.states.get(SENSOR).state == "Custom"

    await capture(hass)

    assert by_name(entry, "Komfort")["values"]["temperature"] == 23
    # And because the profile now matches again, it is active once more.
    assert hass.states.get(SENSOR).state == "Komfort"


async def test_the_sensor_says_what_would_be_captured(hass, entry_data):
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    set_device_state(hass, temperature=23, fan_mode="high")
    await settle(hass)

    attrs = hass.states.get(SENSOR).attributes
    assert attrs["last_matched_profile_id"] == "komfort"
    assert set(attrs["changed_values"]) == {"temperature", "fan_mode"}


async def test_a_partial_profile_grows_only_by_what_changed(hass, entry_data):
    """A profile for mode and temperature gains the fan you moved, nothing else."""
    set_device_state(hass, hvac_mode="cool", temperature=22)
    entry = await setup_entry(hass, entry_data)
    assert hass.states.get(SENSOR).state == "Kuehlung"

    set_device_state(hass, hvac_mode="cool", temperature=22, fan_mode="high")
    await settle(hass)
    await capture(hass)

    values = by_name(entry, "Kuehlung")["values"]
    assert values == {"hvac_mode": "cool", "temperature": 22, "fan_mode": "high"}
    # Untouched values stayed out of it.
    assert "swing_mode" not in values and "display" not in values


async def test_capturing_into_a_named_profile(hass, entry_data):
    set_device_state(hass, temperature=23)
    entry = await setup_entry(hass, entry_data)

    await capture(hass, profile="Kuehlung")
    assert by_name(entry, "Kuehlung")["values"]["temperature"] == 23


async def test_capturing_only_selected_values(hass, entry_data):
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)

    set_device_state(hass, temperature=23, fan_mode="high")
    await settle(hass)
    await capture(hass, values=["temperature"])

    values = by_name(entry, "Komfort")["values"]
    assert values["temperature"] == 23
    assert values["fan_mode"] == "auto", "fan_mode was not asked for"


async def test_after_a_restart_nothing_is_assumed(hass, entry_data):
    """No profile has matched yet, so there is no target to capture into."""
    set_device_state(hass, temperature=23)
    await setup_entry(hass, entry_data)
    assert hass.states.get(SENSOR).state == "Custom"
    assert hass.states.get(SENSOR).attributes["last_matched_profile_id"] is None

    with pytest.raises(ServiceValidationError):
        await capture(hass)


async def test_an_unknown_profile_is_refused(hass, entry_data):
    set_device_state(hass)
    await setup_entry(hass, entry_data)
    with pytest.raises(ServiceValidationError):
        await capture(hass, profile="gibt es nicht")


# --- write protection ------------------------------------------------------


async def test_a_protected_profile_refuses_to_be_overwritten(hass, entry_data):
    profiles = [dict(p) for p in PROFILES]
    profiles[1]["protected"] = True  # Komfort
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data, profiles=profiles)

    set_device_state(hass, temperature=23)
    await settle(hass)

    with pytest.raises(ServiceValidationError):
        await capture(hass)
    assert by_name(entry, "Komfort")["values"]["temperature"] == 24


async def test_protection_survives_editing_and_is_reported(hass, entry_data):
    profiles = [dict(p) for p in PROFILES]
    profiles[0]["protected"] = True  # Aus
    set_device_state(hass)
    await setup_entry(hass, entry_data, profiles=profiles)

    listed = hass.states.get(SENSOR).attributes["profiles"]
    assert listed[0]["protected"] is True
    assert listed[1]["protected"] is False


# --- save as a new profile -------------------------------------------------


async def test_saving_the_state_as_a_new_profile(hass, entry_data):
    set_device_state(hass, temperature=23, fan_mode="high")
    entry = await setup_entry(hass, entry_data)

    await hass.services.async_call(
        DOMAIN,
        "save_as_profile",
        {
            "entity_id": SENSOR,
            "name": "Mittagshitze",
            "color": "#f59e0b",
            "icon": "mdi:weather-sunny",
        },
        blocking=True,
    )
    await settle(hass)

    created = by_name(entry, "Mittagshitze")
    assert created["color"] == "#f59e0b"
    assert created["icon"] == "mdi:weather-sunny"
    # A new profile describes the whole state, there is nothing to inherit.
    assert created["values"]["temperature"] == 23
    assert created["values"]["fan_mode"] == "high"
    assert created["values"]["display"] == "off"
    # It is the last one, and it matches right away.
    assert stored(entry)[-1]["name"] == "Mittagshitze"
    assert hass.states.get(SENSOR).state == "Mittagshitze"


async def test_a_new_profile_needs_a_name(hass, entry_data):
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "save_as_profile",
            {"entity_id": SENSOR, "name": "   "},
            blocking=True,
        )


async def test_saving_only_selected_values(hass, entry_data):
    set_device_state(hass, temperature=23)
    entry = await setup_entry(hass, entry_data)

    await hass.services.async_call(
        DOMAIN,
        "save_as_profile",
        {"entity_id": SENSOR, "name": "Nur Temperatur", "values": ["temperature"]},
        blocking=True,
    )
    await settle(hass)
    assert by_name(entry, "Nur Temperatur")["values"] == {"temperature": 23}


# --- no reload -------------------------------------------------------------


async def test_capturing_does_not_reload_the_entities(hass, entry_data):
    """A reload would make every entity blink on each capture."""
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    set_device_state(hass, temperature=23)
    await settle(hass)

    seen: list[str] = []
    hass.bus.async_listen(
        "state_changed",
        lambda event: (
            seen.append(event.data["new_state"].state)
            if event.data["entity_id"] == SENSOR and event.data["new_state"]
            else None
        ),
    )

    await capture(hass)
    assert "unavailable" not in seen, f"the sensor went through {seen}"
    assert hass.states.get(SENSOR).state == "Komfort"


async def test_changes_are_reported_while_a_partial_profile_stays_active(
    hass, entry_data
):
    """The fan moved, "Kuehlung" still matches - and still offers to capture."""
    set_device_state(hass, hvac_mode="cool", temperature=22)
    await setup_entry(hass, entry_data)
    assert hass.states.get(SENSOR).state == "Kuehlung"

    set_device_state(hass, hvac_mode="cool", temperature=22, fan_mode="high")
    await settle(hass)

    state = hass.states.get(SENSOR)
    assert state.state == "Kuehlung", "a value it does not define cannot unmatch it"
    assert state.attributes["changed_values"] == ["fan_mode"]
    assert state.attributes["last_matched_profile_id"] == "kuehlung"
