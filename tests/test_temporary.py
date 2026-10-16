"""Tests for temporary profiles: started by hand while automatic mode is on."""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.climate_profiles.const import (
    AUTOMATIC_STORAGE_KEY,
    CONF_PROFILE_SENSOR,
    DOMAIN,
)
from custom_components.climate_profiles.models import ClimateProfile

from .conftest import set_device_state, settle
from .test_automatic import PROFILE_SENSOR, automatic
from .test_integration import PROFILES, SENSOR, setup_entry

#: "Komfort" may be started for 30 minutes, "Aus" for the default hour.
TEMPORARY_PROFILES = [
    {**PROFILES[0], "temporary": True},
    {**PROFILES[1], "temporary": True, "duration": 30},
    PROFILES[2],
]


async def setup_temporary(hass, entry_data, *, on: bool = True):
    """Set up an entry whose sensor names "Kuehlung", automatic mode ``on``."""
    hass.states.async_set(PROFILE_SENSOR, "Kuehlung")
    set_device_state(hass, temperature=26)
    entry = await setup_entry(
        hass,
        entry_data,
        profiles=TEMPORARY_PROFILES,
        options={CONF_PROFILE_SENSOR: PROFILE_SENSOR},
    )
    if on:
        await entry.runtime_data.async_set_automatic(True)
        await settle(hass)
    return entry


async def apply(hass, profile: str) -> None:
    """Call ``apply_profile`` the way the card does."""
    await hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": SENSOR, "profile": profile},
        blocking=True,
    )
    await settle(hass)


async def end(hass) -> None:
    """Call ``end_temporary``."""
    await hass.services.async_call(
        DOMAIN, "end_temporary", {"entity_id": SENSOR}, blocking=True
    )
    await settle(hass)


def written(calls) -> int:
    """Return how many service calls the integration made so far."""
    return sum(len(recorded) for recorded in calls.values())


# --- the model -------------------------------------------------------------


def test_temporary_is_stored_only_when_set():
    plain = ClimateProfile(id="a", name="A", values={"hvac_mode": "off"})
    assert "temporary" not in plain.as_dict()
    assert "duration" not in plain.as_dict()

    timed = ClimateProfile.from_dict(
        {"id": "b", "name": "B", "values": {}, "temporary": True, "duration": 30}
    )
    assert timed.temporary is True
    assert timed.duration == 30
    assert ClimateProfile.from_dict(timed.as_dict()) == timed


@pytest.mark.parametrize(
    ("stored", "minutes"), [(None, 60), ("", 60), (0, 1), (99999, 1440), (12.7, 12)]
)
def test_a_duration_is_whole_minutes_within_a_day(stored, minutes):
    raw = {"id": "a", "name": "A", "values": {}, "temporary": True, "duration": stored}
    assert ClimateProfile.from_dict(raw).duration == minutes


# --- starting --------------------------------------------------------------


async def test_a_temporary_profile_overrides_the_sensor(hass, entry_data, calls):
    await setup_temporary(hass, entry_data)
    before = dt_util.utcnow()

    await apply(hass, "Komfort")

    assert calls["set_temperature"][-1].data["temperature"] == 24
    state = automatic(hass)
    assert state["status"] == "temporary"
    assert state["temporary"]["profile_id"] == "komfort"
    until = dt_util.parse_datetime(state["temporary"]["until"])
    assert timedelta(minutes=29) < until - before < timedelta(minutes=31)
    # What the sensor names is still shown: it takes over afterwards.
    assert state["target_id"] == "kuehlung"


async def test_the_sensor_does_not_end_it(hass, entry_data, calls):
    await setup_temporary(hass, entry_data)
    await apply(hass, "Komfort")
    count = written(calls)

    hass.states.async_set(PROFILE_SENSOR, "Aus")
    await settle(hass)

    assert written(calls) == count
    assert automatic(hass)["status"] == "temporary"
    assert automatic(hass)["target_id"] == "aus"


async def test_a_regular_profile_is_still_refused(hass, entry_data, calls):
    await setup_temporary(hass, entry_data)

    with pytest.raises(ServiceValidationError) as err:
        await apply(hass, "Kuehlung")
    assert err.value.translation_key == "automatic_mode_on"


async def test_a_second_one_replaces_the_first(hass, entry_data, calls):
    await setup_temporary(hass, entry_data)
    await apply(hass, "Komfort")

    await apply(hass, "Aus")

    assert calls["set_hvac_mode"][-1].data["hvac_mode"] == "off"
    assert automatic(hass)["temporary"]["profile_id"] == "aus"
    until = dt_util.parse_datetime(automatic(hass)["temporary"]["until"])
    assert until - dt_util.utcnow() > timedelta(minutes=59)


async def test_outside_automatic_mode_it_is_a_profile_like_any(hass, entry_data, calls):
    await setup_temporary(hass, entry_data, on=False)

    await apply(hass, "Komfort")

    assert calls["set_temperature"][-1].data["temperature"] == 24
    assert automatic(hass)["status"] == "off"
    assert automatic(hass)["temporary"] is None


# --- ending ----------------------------------------------------------------


async def test_ending_it_hands_back_to_the_sensor(hass, entry_data, calls):
    """The sensor's profile is written again, though it was applied before."""
    await setup_temporary(hass, entry_data)
    await apply(hass, "Komfort")

    await end(hass)

    assert calls["set_temperature"][-1].data["temperature"] == 22
    assert automatic(hass)["status"] == "following"
    assert automatic(hass)["temporary"] is None


async def test_it_ends_when_its_time_is_up(hass, entry_data, calls):
    await setup_temporary(hass, entry_data)
    await apply(hass, "Komfort")

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=31))
    await settle(hass)

    assert calls["set_temperature"][-1].data["temperature"] == 22
    assert automatic(hass)["status"] == "following"


async def test_without_a_profile_to_hand_back_to_nothing_is_written(
    hass, entry_data, calls
):
    await setup_temporary(hass, entry_data)
    await apply(hass, "Komfort")
    hass.states.async_set(PROFILE_SENSOR, STATE_UNAVAILABLE)
    await settle(hass)
    count = written(calls)

    await end(hass)

    assert written(calls) == count
    assert automatic(hass)["status"] == "waiting"

    hass.states.async_set(PROFILE_SENSOR, "Kuehlung")
    await settle(hass)
    assert calls["set_temperature"][-1].data["temperature"] == 22


async def test_switching_automatic_mode_off_ends_it(hass, entry_data, calls):
    """Its values stay - there is nothing to hand back to."""
    entry = await setup_temporary(hass, entry_data)
    await apply(hass, "Komfort")
    count = written(calls)

    await entry.runtime_data.async_set_automatic(False)
    await settle(hass)

    assert written(calls) == count
    assert automatic(hass)["temporary"] is None


async def test_ending_without_one_does_nothing(hass, entry_data, calls):
    await setup_temporary(hass, entry_data)
    count = written(calls)

    await end(hass)

    assert written(calls) == count


# --- restarts --------------------------------------------------------------


async def test_it_survives_a_restart(hass, entry_data, calls, hass_storage):
    entry = await setup_temporary(hass, entry_data, on=False)
    until = dt_util.utcnow() + timedelta(minutes=10)
    hass_storage[AUTOMATIC_STORAGE_KEY] = {
        "version": 1,
        "key": AUTOMATIC_STORAGE_KEY,
        "data": {
            entry.entry_id: {
                "on": True,
                "applied": None,
                "temporary": {"id": "komfort", "until": until.isoformat()},
            }
        },
    }

    await hass.config_entries.async_reload(entry.entry_id)
    await settle(hass)

    assert automatic(hass)["status"] == "temporary"
    assert dt_util.parse_datetime(automatic(hass)["temporary"]["until"]) == until
    assert not calls["set_temperature"]


async def test_one_that_ran_out_during_a_restart_ends(
    hass, entry_data, calls, hass_storage
):
    entry = await setup_temporary(hass, entry_data, on=False)
    hass_storage[AUTOMATIC_STORAGE_KEY] = {
        "version": 1,
        "key": AUTOMATIC_STORAGE_KEY,
        "data": {
            entry.entry_id: {
                "on": True,
                "applied": None,
                "temporary": {
                    "id": "komfort",
                    "until": (dt_util.utcnow() - timedelta(minutes=1)).isoformat(),
                },
            }
        },
    }

    await hass.config_entries.async_reload(entry.entry_id)
    await settle(hass)

    assert automatic(hass)["status"] == "following"
    assert calls["set_temperature"][-1].data["temperature"] == 22


# --- duration per call and deleted profiles --------------------------------


async def test_a_call_can_set_its_own_duration(hass, entry_data, calls):
    await setup_temporary(hass, entry_data)

    await hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": SENSOR, "profile": "Komfort", "duration": 5},
        blocking=True,
    )
    await settle(hass)

    until = dt_util.parse_datetime(automatic(hass)["temporary"]["until"])
    assert timedelta(minutes=4) < until - dt_util.utcnow() <= timedelta(minutes=5)


async def test_a_duration_does_not_make_a_profile_temporary(hass, entry_data, calls):
    await setup_temporary(hass, entry_data)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "apply_profile",
            {"entity_id": SENSOR, "profile": "Kuehlung", "duration": 5},
            blocking=True,
        )


async def test_deleting_the_running_profile_hands_back(hass, entry_data, calls):
    entry = await setup_temporary(hass, entry_data)
    await apply(hass, "Komfort")

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            "profiles": [p for p in entry.options["profiles"] if p["id"] != "komfort"],
        },
    )
    await settle(hass)

    assert automatic(hass)["status"] == "following"
    assert automatic(hass)["temporary"] is None
    assert calls["set_temperature"][-1].data["temperature"] == 22


# --- profiles that take priority ---------------------------------------------

#: "Aus" stands for an open window: it wins over the temporary "Komfort".
PRIORITY_PROFILES = [
    {**PROFILES[0], "priority": True},
    {**PROFILES[1], "temporary": True, "duration": 30},
    PROFILES[2],
]


async def setup_priority(hass, entry_data, hass_storage=None):
    """Set up an entry whose sensor names "Kuehlung", automatic mode on."""
    hass.states.async_set(PROFILE_SENSOR, "Kuehlung")
    set_device_state(hass, temperature=26)
    entry = await setup_entry(
        hass,
        entry_data,
        profiles=PRIORITY_PROFILES,
        options={CONF_PROFILE_SENSOR: PROFILE_SENSOR},
    )
    await entry.runtime_data.async_set_automatic(True)
    await settle(hass)
    return entry


def test_priority_is_stored_only_when_set():
    plain = ClimateProfile(id="a", name="A", values={"hvac_mode": "off"})
    assert "priority" not in plain.as_dict()

    window = ClimateProfile.from_dict(
        {"id": "b", "name": "B", "values": {}, "priority": True}
    )
    assert window.priority is True
    assert ClimateProfile.from_dict(window.as_dict()) == window


async def test_a_priority_profile_ends_a_running_temporary_one(hass, entry_data, calls):
    await setup_priority(hass, entry_data)
    await apply(hass, "Komfort")
    assert automatic(hass)["status"] == "temporary"

    hass.states.async_set(PROFILE_SENSOR, "Aus")
    await settle(hass)

    assert automatic(hass)["status"] == "following"
    assert automatic(hass)["temporary"] is None
    assert calls["set_hvac_mode"][-1].data["hvac_mode"] == "off"


async def test_no_temporary_profile_starts_while_one_takes_priority(
    hass, entry_data, calls
):
    await setup_priority(hass, entry_data)
    hass.states.async_set(PROFILE_SENSOR, "Aus")
    await settle(hass)
    count = written(calls)

    with pytest.raises(ServiceValidationError) as err:
        await apply(hass, "Komfort")

    assert err.value.translation_key == "temporary_blocked_by_priority"
    assert err.value.translation_placeholders == {
        "profile": "Komfort",
        "target": "Aus",
    }
    assert written(calls) == count
    assert automatic(hass)["status"] == "following"


async def test_once_the_sensor_moves_on_it_can_start_again(hass, entry_data, calls):
    await setup_priority(hass, entry_data)
    hass.states.async_set(PROFILE_SENSOR, "Aus")
    await settle(hass)
    hass.states.async_set(PROFILE_SENSOR, "Kuehlung")
    await settle(hass)

    await apply(hass, "Komfort")

    assert automatic(hass)["status"] == "temporary"


async def test_a_profile_without_priority_leaves_it_running(hass, entry_data, calls):
    await setup_priority(hass, entry_data)
    hass.states.async_set(PROFILE_SENSOR, "Aus")
    await settle(hass)
    hass.states.async_set(PROFILE_SENSOR, "Kuehlung")
    await settle(hass)
    await apply(hass, "Komfort")

    hass.states.async_set(PROFILE_SENSOR, "Komfort")
    await settle(hass)

    assert automatic(hass)["status"] == "temporary"
    assert automatic(hass)["target_id"] == "komfort"


async def test_priority_means_nothing_outside_automatic_mode(hass, entry_data, calls):
    entry = await setup_priority(hass, entry_data)
    hass.states.async_set(PROFILE_SENSOR, "Aus")
    await settle(hass)
    await entry.runtime_data.async_set_automatic(False)
    await settle(hass)

    await apply(hass, "Komfort")

    assert calls["set_temperature"][-1].data["temperature"] == 24
    assert automatic(hass)["status"] == "off"


async def test_a_restart_ends_one_that_lost_to_priority(
    hass, entry_data, calls, hass_storage
):
    entry = await setup_priority(hass, entry_data)
    await entry.runtime_data.async_set_automatic(False)
    await settle(hass)
    hass.states.async_set(PROFILE_SENSOR, "Aus")
    until = dt_util.utcnow() + timedelta(minutes=10)
    hass_storage[AUTOMATIC_STORAGE_KEY] = {
        "version": 1,
        "key": AUTOMATIC_STORAGE_KEY,
        "data": {
            entry.entry_id: {
                "on": True,
                "applied": None,
                "temporary": {"id": "komfort", "until": until.isoformat()},
            }
        },
    }

    await hass.config_entries.async_reload(entry.entry_id)
    await settle(hass)

    assert automatic(hass)["status"] == "following"
    assert automatic(hass)["target_id"] == "aus"
