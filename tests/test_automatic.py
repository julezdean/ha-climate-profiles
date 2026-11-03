"""Tests for automatic mode: a sensor of the user's names the profile."""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE, STATE_UNAVAILABLE
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from custom_components.climate_profiles import coordinator as coordinator_module
from custom_components.climate_profiles.const import (
    AUTOMATIC_STORAGE_KEY,
    CONF_CLIMATE_ENTITY,
    CONF_PROFILE_SENSOR,
    CONF_PROFILES,
    DOMAIN,
    SELECTION_STORAGE_KEY,
)

from .conftest import CLIMATE, open_step, restart, set_device_state, settle
from .test_integration import PROFILES, SELECT, SENSOR, setup_entry

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
        "switch": SWITCH,
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
    await restart(
        hass,
        entry,
        hass_storage,
        {AUTOMATIC_STORAGE_KEY: {entry.entry_id: {"on": True, "applied": "kuehlung"}}},
    )
    await settle(hass)

    assert entry.runtime_data.automatic_on
    assert not calls["set_temperature"]


async def test_a_restart_writes_a_new_target(hass, entry_data, calls, hass_storage):
    entry = await setup_automatic(hass, entry_data, wanted="Aus")
    await restart(
        hass,
        entry,
        hass_storage,
        {AUTOMATIC_STORAGE_KEY: {entry.entry_id: {"on": True, "applied": "kuehlung"}}},
    )
    await settle(hass)

    assert calls["set_hvac_mode"][-1].data["hvac_mode"] == "off"


async def test_rooms_switching_together_each_keep_what_they_chose(
    hass, entry_data, calls, hass_storage, monkeypatch
):
    """Every room is stored, not only the one that happened to write last.

    The sensor switching several rooms at once made each of them write the
    shared file at the same moment; all but one lost their entry, and woke up
    after a restart with a profile they had left.
    """
    # Reading the file really goes to the executor, and others run before
    # what was read comes back. The mocked storage answers at once, which
    # hides exactly that.
    load = Store.async_load

    async def slow_load(self):
        data = await load(self)
        await asyncio.sleep(0)
        return data

    monkeypatch.setattr(Store, "async_load", slow_load)
    living_room = await setup_automatic(hass, entry_data)
    bedroom_climate = "climate.bedroom"
    hass.states.async_set(
        bedroom_climate, "cool", dict(hass.states.get(CLIMATE).attributes)
    )
    bedroom = await setup_entry(
        hass,
        {CONF_CLIMATE_ENTITY: bedroom_climate},
        options={CONF_PROFILE_SENSOR: PROFILE_SENSOR},
        title="Bedroom",
    )
    for entry in (living_room, bedroom):
        await entry.runtime_data.async_set_automatic(True)
    await settle(hass)

    hass.states.async_set(PROFILE_SENSOR, "Aus")
    await settle(hass)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()

    rooms = (living_room.entry_id, bedroom.entry_id)
    assert hass_storage[SELECTION_STORAGE_KEY]["data"] == dict.fromkeys(rooms, "aus")
    stored = hass_storage[AUTOMATIC_STORAGE_KEY]["data"]
    assert {room: stored[room]["applied"] for room in rooms} == dict.fromkeys(
        rooms, "aus"
    )


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


# --- a write protected profile under automatic mode -------------------------


async def test_a_protected_profile_held_by_it_cannot_be_changed(
    hass, entry_data, calls
):
    """A change could only make it custom - which protection is there to stop."""
    profiles = [dict(item) for item in PROFILES]
    profiles[2] = {**profiles[2], "protected": True}
    hass.states.async_set(PROFILE_SENSOR, "Kuehlung")
    set_device_state(hass, temperature=22)
    entry = await setup_entry(
        hass,
        entry_data,
        profiles=profiles,
        options={CONF_PROFILE_SENSOR: PROFILE_SENSOR},
    )
    await switch_on(hass, entry)
    count = len(calls["set_temperature"])

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "set_value",
            {"entity_id": SENSOR, "temperature": 21},
            blocking=True,
        )
    assert err.value.translation_key == "automatic_profile_protected"
    assert len(calls["set_temperature"]) == count

    # Off, it is a protected profile like any other: the change goes through
    # and the state is custom.
    await entry.runtime_data.async_set_automatic(False)
    await hass.services.async_call(
        DOMAIN,
        "set_value",
        {"entity_id": SENSOR, "temperature": 21},
        blocking=True,
    )
    assert calls["set_temperature"][-1].data["temperature"] == 21


# --- holding, not detecting -------------------------------------------------


async def test_the_profile_held_is_the_state_while_the_device_catches_up(
    hass, entry_data, calls, monkeypatch
):
    """No custom in between: the device has not answered yet, it is mocked."""
    entry = await setup_automatic(hass, entry_data)
    assert hass.states.get(SENSOR).state == "Custom"

    await switch_on(hass, entry)

    state = hass.states.get(SENSOR)
    assert state.state == "Kuehlung"
    assert state.attributes["active_profile_id"] == "kuehlung"
    # On its way: not a deviation yet.
    assert state.attributes["deviates"] == []

    # The device never follows. Judged, it is a deviation - and still the
    # profile automatic mode holds.
    monkeypatch.setattr(coordinator_module, "REACH_QUIET_SECONDS", 0.1)
    await entry.runtime_data._async_check_reached()
    await hass.async_block_till_done()
    state = hass.states.get(SENSOR)
    assert state.state == "Kuehlung"
    assert state.attributes["deviates"] == ["temperature"]
    assert state.attributes["unreached"]["profile_id"] == "kuehlung"


async def test_the_select_has_no_custom_in_automatic_mode(hass, entry_data, calls):
    entry = await setup_automatic(hass, entry_data)
    assert "Custom" in hass.states.get(SELECT).attributes["options"]

    await switch_on(hass, entry)

    select = hass.states.get(SELECT)
    assert select.attributes["options"] == ["Aus", "Komfort", "Kuehlung"]
    assert select.state == "Kuehlung"


async def test_a_change_on_the_device_is_a_deviation(hass, entry_data, calls):
    """A protected profile keeps the change out; the state stays its name."""
    hass.states.async_set(PROFILE_SENSOR, "Kuehlung")
    set_device_state(hass, temperature=22)
    profiles = [{**p, "protected": True} for p in PROFILES]
    entry = await setup_entry(
        hass,
        entry_data,
        profiles=profiles,
        options={CONF_PROFILE_SENSOR: PROFILE_SENSOR},
    )
    await switch_on(hass, entry)
    entry.runtime_data._clear_target()

    # The thermostat's own buttons.
    set_device_state(hass, temperature=25)
    await settle(hass)

    state = hass.states.get(SENSOR)
    assert state.state == "Kuehlung"
    assert state.attributes["deviates"] == ["temperature"]


async def test_without_anything_held_the_state_is_unknown(
    hass, entry_data, calls, hass_storage
):
    """After a restart, with a sensor that names nothing."""
    entry = await setup_automatic(hass, entry_data, wanted="Gibt es nicht")
    await restart(
        hass,
        entry,
        hass_storage,
        {AUTOMATIC_STORAGE_KEY: {entry.entry_id: {"on": True, "applied": None}}},
    )
    await settle(hass)

    state = hass.states.get(SENSOR)
    assert state.state == "unknown"
    assert state.attributes["active_profile_id"] is None
    assert hass.states.get(SELECT).state == "unknown"


async def test_with_the_sensor_naming_nothing_the_last_profile_stays(
    hass, entry_data, calls
):
    entry = await setup_automatic(hass, entry_data)
    await switch_on(hass, entry)

    hass.states.async_set(PROFILE_SENSOR, STATE_UNAVAILABLE)
    await settle(hass)

    assert hass.states.get(SENSOR).state == "Kuehlung"


async def test_after_a_restart_the_profile_held_is_the_reference_point(
    hass, entry_data, calls, hass_storage, monkeypatch
):
    """A change made by hand after the restart goes into the profile held."""
    monkeypatch.setattr(coordinator_module, "AUTO_CAPTURE_QUIET_SECONDS", 0.2)
    entry = await setup_automatic(hass, entry_data)
    await restart(
        hass,
        entry,
        hass_storage,
        {AUTOMATIC_STORAGE_KEY: {entry.entry_id: {"on": True, "applied": "kuehlung"}}},
    )
    await settle(hass)
    # Restarted on 26 °C: the device differs from Kuehlung, and that is shown.
    assert hass.states.get(SENSOR).state == "Kuehlung"
    assert hass.states.get(SENSOR).attributes["deviates"] == ["temperature"]

    set_device_state(hass, temperature=23)
    await settle(hass)
    await asyncio.sleep(0.4)
    await settle(hass)

    kuehlung = next(p for p in entry.options[CONF_PROFILES] if p["id"] == "kuehlung")
    assert kuehlung["values"]["temperature"] == 23


async def test_a_deviation_is_not_reported_while_a_profile_is_applied(
    hass, entry_data, calls
):
    """What differed from the profile before must not land on the next one."""
    entry = await setup_automatic(hass, entry_data)
    await switch_on(hass, entry)
    # The mocked device never took Kuehlung: judged, that is a deviation.
    entry.runtime_data._clear_target()
    await entry.runtime_data.async_refresh()
    assert entry.runtime_data.data.deviates == ("temperature",)

    seen: list[tuple[str, tuple[str, ...]]] = []
    entry.runtime_data.async_add_listener(
        lambda: seen.append(
            (entry.runtime_data.data.active.name, entry.runtime_data.data.deviates)
        )
    )
    hass.states.async_set(PROFILE_SENSOR, "Komfort")
    await settle(hass)

    komfort = [deviates for name, deviates in seen if name == "Komfort"]
    assert komfort
    assert all(deviates == () for deviates in komfort), seen
