"""A profile the device cannot hold.

Two values of one profile can contradict each other on a real device: a silent
mode that forces its own fan speed makes "fan mode full, silent on" impossible
to reach. The integration cannot know that - it is device knowledge - but it
can see the result, and it must not mistake it for something else.
"""

from __future__ import annotations

import asyncio

import pytest

from custom_components.climate_profiles import coordinator as coordinator_module
from custom_components.climate_profiles.const import DOMAIN

from .conftest import set_device_state, settle
from .test_integration import PROFILES, SENSOR, setup_entry

#: Asks for the full fan and silent mode at once. The reference device drops
#: the fan to its silent speed as soon as silent mode goes on.
MAX = {
    "id": "max",
    "name": "Max",
    "color": "#ef4444",
    "values": {"hvac_mode": "cool", "fan_mode": "full", "silent": "on"},
}


async def apply(hass, profile: str) -> None:
    """Apply a profile through the service."""
    await hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": SENSOR, "profile": profile},
        blocking=True,
    )


async def test_an_unreached_profile_is_not_offered_as_a_manual_change(
    hass, entry_data, calls
):
    """What the device did with Max is not a hand edit of the profile before."""
    set_device_state(hass)
    await setup_entry(hass, entry_data, profiles=[*PROFILES, MAX])
    assert hass.states.get(SENSOR).state == "Komfort"

    await apply(hass, "Max")
    # The device takes silent mode and overrides the fan with its own speed.
    set_device_state(hass, fan_mode="silent", silent="on")
    await settle(hass)

    attributes = hass.states.get(SENSOR).attributes
    assert hass.states.get(SENSOR).state == "Custom"
    assert attributes["changed_values"] == [], (
        "the capture bar would offer to write Max's result into "
        f"{attributes['last_matched_profile_id']!r}"
    )


# --- the verdict -----------------------------------------------------------
QUIET = 0.3


@pytest.fixture(autouse=True)
def short_waits(monkeypatch):
    """Judge after 0.3 s of quiet instead of the real device timings."""
    monkeypatch.setattr(coordinator_module, "REACH_QUIET_SECONDS", QUIET)
    monkeypatch.setattr(coordinator_module, "REACH_MAX_SECONDS", 2.0)


async def wait(hass, seconds: float) -> None:
    """Let real time pass - the reach check runs on the event loop's clock."""
    await asyncio.sleep(seconds)
    await hass.async_block_till_done()


async def test_an_unreached_profile_says_which_values_did_not_take(
    hass, entry_data, calls, caplog
):
    set_device_state(hass)
    await setup_entry(hass, entry_data, profiles=[*PROFILES, MAX])

    await apply(hass, "Max")
    set_device_state(hass, fan_mode="silent", silent="on")
    await wait(hass, QUIET * 3)

    unreached = hass.states.get(SENSOR).attributes["unreached"]
    assert unreached["profile"] == "Max"
    assert unreached["values"] == {"fan_mode": {"wanted": "full", "actual": "silent"}}
    assert "Max was applied but did not take" in caplog.text


async def test_a_profile_that_takes_reports_nothing(hass, entry_data, calls):
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    await apply(hass, "Aus")
    set_device_state(hass, hvac_mode="off")
    await wait(hass, QUIET * 3)

    assert hass.states.get(SENSOR).state == "Aus"
    assert hass.states.get(SENSOR).attributes["unreached"] is None


async def test_a_slow_device_is_waited_for(hass, entry_data, calls):
    """Every state change restarts the quiet period, up to the maximum."""
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    await apply(hass, "Aus")
    # Something moves before the device gets round to switching off ...
    await wait(hass, QUIET * 0.6)
    set_device_state(hass, fan_mode="low")
    await wait(hass, QUIET * 0.6)
    # ... and the switch-off arrives after the first quiet period has passed.
    set_device_state(hass, hvac_mode="off", fan_mode="low")
    await wait(hass, QUIET * 3)

    assert hass.states.get(SENSOR).state == "Aus"
    assert hass.states.get(SENSOR).attributes["unreached"] is None


async def test_applying_another_profile_clears_the_verdict(hass, entry_data, calls):
    set_device_state(hass)
    await setup_entry(hass, entry_data, profiles=[*PROFILES, MAX])

    await apply(hass, "Max")
    set_device_state(hass, fan_mode="silent", silent="on")
    await wait(hass, QUIET * 3)
    assert hass.states.get(SENSOR).attributes["unreached"] is not None

    await apply(hass, "Komfort")
    set_device_state(hass)
    await wait(hass, QUIET * 3)

    assert hass.states.get(SENSOR).state == "Komfort"
    assert hass.states.get(SENSOR).attributes["unreached"] is None
