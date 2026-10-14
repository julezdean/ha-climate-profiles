"""Tests for automatic mode: a sensor of the user's names the profile."""

from __future__ import annotations

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from custom_components.climate_profiles.const import (
    AUTOMATIC_STORAGE_KEY,
    CONF_PROFILE_SENSOR,
    DOMAIN,
)

from .conftest import open_step, set_device_state, settle
from .test_integration import SELECT, SENSOR, setup_entry

PROFILE_SENSOR = "sensor.wanted_profile"
SWITCH = "switch.living_room_automatic_mode"


async def setup_automatic(hass, entry_data, *, wanted: str = "Kuehlung"):
    """Set up an entry that follows ``PROFILE_SENSOR``, automatic mode off."""
    hass.states.async_set(PROFILE_SENSOR, wanted)
    set_device_state(hass, temperature=26)
    return await setup_entry(
        hass, entry_data, options={CONF_PROFILE_SENSOR: PROFILE_SENSOR}
    )


def automatic(hass) -> dict:
    """Return the sensor's ``automatic`` attribute."""
    return hass.states.get(SENSOR).attributes["automatic"]


async def switch_on(hass, entry) -> None:
    """Switch automatic mode on through the coordinator.

    Not through the switch service: the ``calls`` fixture mocks
    ``switch.turn_on``, because the device's own switches go through it.
    """
    await entry.runtime_data.async_set_automatic(True)
    await settle(hass)


# --- without a sensor ------------------------------------------------------


async def test_without_a_sensor_there_is_no_automatic_mode(hass, entry_data):
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)

    assert hass.states.get(SWITCH) is None
    assert hass.states.get(SENSOR).attributes["automatic"] is None
    with pytest.raises(ServiceValidationError) as err:
        await entry.runtime_data.async_set_automatic(True)
    assert err.value.translation_key == "automatic_needs_sensor"


# --- the target ------------------------------------------------------------


async def test_the_target_is_shown_while_automatic_mode_is_off(hass, entry_data, calls):
    await setup_automatic(hass, entry_data)

    assert hass.states.get(SWITCH).state == "off"
    assert automatic(hass) == {
        "status": "off",
        "sensor": PROFILE_SENSOR,
        "sensor_state": "Kuehlung",
        "target": "Kuehlung",
        "target_id": "kuehlung",
        "problem": None,
        "temporary": None,
    }
    # Off is off: nothing is written for it.
    assert not calls["set_temperature"]


async def test_the_target_follows_the_sensor(hass, entry_data):
    await setup_automatic(hass, entry_data)

    hass.states.async_set(PROFILE_SENSOR, "komfort")
    await hass.async_block_till_done()
    assert automatic(hass)["target_id"] == "komfort"

    hass.states.async_set(PROFILE_SENSOR, "Gibt es nicht")
    await hass.async_block_till_done()
    assert automatic(hass)["target"] is None
    assert automatic(hass)["problem"] == "unknown_profile"
    assert automatic(hass)["sensor_state"] == "Gibt es nicht"

    hass.states.async_set(PROFILE_SENSOR, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    assert automatic(hass)["problem"] == "sensor_unavailable"


# --- following -------------------------------------------------------------


async def test_switching_on_applies_the_target(hass, entry_data, calls):
    entry = await setup_automatic(hass, entry_data)

    await switch_on(hass, entry)

    assert hass.states.get(SWITCH).state == "on"
    assert automatic(hass)["status"] == "following"
    assert calls["set_temperature"][-1].data["temperature"] == 22


async def test_a_new_target_is_applied(hass, entry_data, calls):
    entry = await setup_automatic(hass, entry_data)
    await switch_on(hass, entry)

    hass.states.async_set(PROFILE_SENSOR, "Aus")
    await settle(hass)

    assert calls["set_hvac_mode"][-1].data["hvac_mode"] == "off"


async def test_the_same_target_again_writes_nothing(hass, entry_data, calls):
    """A sensor reporting the same name does not undo a change made by hand."""
    entry = await setup_automatic(hass, entry_data)
    await switch_on(hass, entry)
    written = len(calls["set_temperature"])

    hass.states.async_set(PROFILE_SENSOR, "Kuehlung", {"changed": "attribute"})
    await settle(hass)

    assert len(calls["set_temperature"]) == written


@pytest.mark.parametrize("state", [STATE_UNAVAILABLE, "Gibt es nicht"])
async def test_no_target_writes_nothing(hass, entry_data, calls, state):
    entry = await setup_automatic(hass, entry_data)
    await switch_on(hass, entry)
    written = sum(len(recorded) for recorded in calls.values())

    hass.states.async_set(PROFILE_SENSOR, state)
    await settle(hass)

    assert sum(len(recorded) for recorded in calls.values()) == written
    assert automatic(hass)["status"] == "waiting"
    # Switched on is what was chosen; waiting is what it does.
    assert hass.states.get(SWITCH).state == "on"


async def test_a_target_after_waiting_is_applied(hass, entry_data, calls):
    entry = await setup_automatic(hass, entry_data, wanted=STATE_UNAVAILABLE)
    await switch_on(hass, entry)
    assert not calls["set_temperature"]

    hass.states.async_set(PROFILE_SENSOR, "Kuehlung")
    await settle(hass)

    assert calls["set_temperature"][-1].data["temperature"] == 22


async def test_switching_off_stops_following(hass, entry_data, calls):
    entry = await setup_automatic(hass, entry_data)
    await switch_on(hass, entry)
    await entry.runtime_data.async_set_automatic(False)
    written = sum(len(recorded) for recorded in calls.values())

    hass.states.async_set(PROFILE_SENSOR, "Aus")
    await settle(hass)

    assert sum(len(recorded) for recorded in calls.values()) == written
    assert automatic(hass)["status"] == "off"


async def test_a_renamed_profile_is_found(hass, entry_data, calls):
    """The sensor named a profile that did not exist - now it does."""
    entry = await setup_automatic(hass, entry_data, wanted="Nacht")
    await switch_on(hass, entry)
    assert automatic(hass)["problem"] == "unknown_profile"

    profiles = [dict(item) for item in entry.options["profiles"]]
    profiles[2]["name"] = "Nacht"
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "profiles": profiles}
    )
    await settle(hass)

    assert automatic(hass)["target_id"] == "kuehlung"
    assert calls["set_temperature"][-1].data["temperature"] == 22


# --- choosing by hand ------------------------------------------------------


async def test_profiles_cannot_be_chosen_by_hand(hass, entry_data, calls):
    entry = await setup_automatic(hass, entry_data)
    await switch_on(hass, entry)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "apply_profile",
            {"entity_id": SENSOR, "profile": "Komfort"},
            blocking=True,
        )
    assert err.value.translation_key == "automatic_mode_on"

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": SELECT, "option": "Komfort"},
            blocking=True,
        )
    # Every profile stays an option, or the select's state would read unknown
    # while the sensor names one.
    assert "Komfort" in hass.states.get(SELECT).attributes["options"]


async def test_values_can_still_be_set_by_hand(hass, entry_data, calls):
    """Changing the device is not choosing a profile."""
    entry = await setup_automatic(hass, entry_data)
    await switch_on(hass, entry)

    await hass.services.async_call(
        DOMAIN,
        "set_value",
        {"entity_id": SENSOR, "temperature": 21},
        blocking=True,
    )

    assert calls["set_temperature"][-1].data["temperature"] == 21


async def test_choosing_by_hand_works_again_once_off(hass, entry_data, calls):
    entry = await setup_automatic(hass, entry_data)
    await switch_on(hass, entry)
    await entry.runtime_data.async_set_automatic(False)

    await hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": SENSOR, "profile": "Komfort"},
        blocking=True,
    )

    assert calls["set_temperature"][-1].data["temperature"] == 24


# --- the switch ------------------------------------------------------------


async def test_the_switch_turns_automatic_mode_on_and_off(hass, entry_data):
    entry = await setup_automatic(hass, entry_data)

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": SWITCH}, blocking=True
    )
    assert entry.runtime_data.automatic_on
    assert hass.states.get(SWITCH).state == "on"

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": SWITCH}, blocking=True
    )
    assert not entry.runtime_data.automatic_on
    assert hass.states.get(SWITCH).state == "off"


async def test_removing_the_sensor_removes_the_switch(hass, entry_data):
    entry = await setup_automatic(hass, entry_data)
    await entry.runtime_data.async_set_automatic(True)

    hass.config_entries.async_update_entry(
        entry,
        options={k: v for k, v in entry.options.items() if k != CONF_PROFILE_SENSOR},
    )
    await settle(hass)

    assert er.async_get(hass).async_get(SWITCH) is None
    assert hass.states.get(SENSOR).attributes["automatic"] is None
    assert not entry.runtime_data.automatic_on


# --- restarts --------------------------------------------------------------


async def test_a_restart_does_not_write_the_same_target_again(
    hass, entry_data, calls, hass_storage
):
    """What was changed by hand since stays."""
    entry = await setup_automatic(hass, entry_data)
    # The entry id is only known now; store it and set up once more.
    hass_storage[AUTOMATIC_STORAGE_KEY] = {
        "version": 1,
        "key": AUTOMATIC_STORAGE_KEY,
        "data": {entry.entry_id: {"on": True, "applied": "kuehlung"}},
    }
    await hass.config_entries.async_reload(entry.entry_id)
    await settle(hass)

    assert entry.runtime_data.automatic_on
    assert not calls["set_temperature"]


async def test_a_restart_writes_a_new_target(hass, entry_data, calls, hass_storage):
    entry = await setup_automatic(hass, entry_data, wanted="Aus")
    hass_storage[AUTOMATIC_STORAGE_KEY] = {
        "version": 1,
        "key": AUTOMATIC_STORAGE_KEY,
        "data": {entry.entry_id: {"on": True, "applied": "kuehlung"}},
    }
    await hass.config_entries.async_reload(entry.entry_id)
    await settle(hass)

    assert calls["set_hvac_mode"][-1].data["hvac_mode"] == "off"


# --- options ---------------------------------------------------------------


async def test_the_options_set_and_clear_the_sensor(hass, entry_data):
    set_device_state(hass)
    hass.states.async_set(PROFILE_SENSOR, "Komfort")
    entry = await setup_entry(hass, entry_data)

    result = await open_step(hass, entry, "automatic")
    assert result["type"] is FlowResultType.FORM
    selector = result["data_schema"].schema[CONF_PROFILE_SENSOR]
    # Its own sensor would only follow itself.
    assert selector.config["exclude_entities"] == [SENSOR]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PROFILE_SENSOR: PROFILE_SENSOR}
    )
    await settle(hass)
    assert entry.options[CONF_PROFILE_SENSOR] == PROFILE_SENSOR
    assert hass.states.get(SWITCH) is not None

    result = await open_step(hass, entry, "automatic")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    await settle(hass)
    assert CONF_PROFILE_SENSOR not in entry.options
    assert hass.states.get(SWITCH) is None
