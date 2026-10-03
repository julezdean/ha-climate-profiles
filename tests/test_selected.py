"""Profiles that are active because they were chosen, not because they fit.

Derived profiles are right for a device somebody also operates by hand. For
profiles used as the named targets of an automation they are in the way: two
profiles with the same values cannot both exist, and a profile becomes active
without anybody choosing it.
"""

from __future__ import annotations

import asyncio

import pytest
from homeassistant.core import HomeAssistant

from custom_components.climate_profiles import coordinator as coordinator_module
from custom_components.climate_profiles.const import (
    CONF_AUTO_CAPTURE,
    CONF_DETECT,
    CONF_PROFILES,
    DOMAIN,
)

from .conftest import set_device_state, settle
from .test_integration import SENSOR, setup_entry

#: Two profiles that say exactly the same thing. Only a choice can tell them
#: apart - with detection on, the second one is unreachable.
TWINS = [
    {
        "id": "komfort",
        "name": "Komfort",
        "color": "#22c55e",
        "values": {"hvac_mode": "cool", "temperature": 24},
    },
    {
        "id": "emica",
        "name": "Emica",
        "color": "#8b5cf6",
        "values": {"hvac_mode": "cool", "temperature": 24},
    },
]


async def apply(hass: HomeAssistant, profile: str) -> None:
    await hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": SENSOR, "profile": profile},
        blocking=True,
    )
    await settle(hass)


async def set_value(hass: HomeAssistant, device: dict | None = None, **data) -> None:
    """Change a value through the integration, and let the device follow.

    The service calls are mocked, so the device has to be moved by hand here -
    a real one reports the new state within the call, as the logs of a real
    device show.
    """
    await hass.services.async_call(
        DOMAIN, "set_value", {"entity_id": SENSOR, **data}, blocking=True
    )
    if device is not None:
        set_device_state(hass, **device)
    await settle(hass)


async def test_with_detection_off_only_the_chosen_profile_is_active(
    hass: HomeAssistant, entry_data, calls
):
    set_device_state(hass)
    await setup_entry(hass, entry_data, profiles=TWINS, options={CONF_DETECT: False})

    # The values fit both profiles, but nobody chose one.
    assert hass.states.get(SENSOR).state == "Custom"

    await apply(hass, "Emica")
    assert hass.states.get(SENSOR).state == "Emica"

    # And the twin stays reachable - the choice is what tells them apart.
    await apply(hass, "Komfort")
    assert hass.states.get(SENSOR).state == "Komfort"


async def test_with_detection_on_the_twin_is_unreachable(
    hass: HomeAssistant, entry_data, calls
):
    """What the option is there for: derived, one of the two always wins."""
    set_device_state(hass)
    await setup_entry(hass, entry_data, profiles=TWINS)

    await apply(hass, "Emica")

    assert hass.states.get(SENSOR).state == "Komfort"


async def test_a_deviation_is_custom_even_if_another_profile_fits(
    hass: HomeAssistant, entry_data, calls
):
    set_device_state(hass)
    other = {
        "id": "kuehl",
        "name": "Kuehl",
        "color": "#111111",
        "values": {"hvac_mode": "cool", "temperature": 26},
    }
    await setup_entry(
        hass, entry_data, profiles=[*TWINS, other], options={CONF_DETECT: False}
    )
    await apply(hass, "Komfort")

    set_device_state(hass, temperature=26)
    await settle(hass)

    assert hass.states.get(SENSOR).state == "Custom"


async def test_the_choice_survives_a_restart(hass: HomeAssistant, entry_data, calls):
    set_device_state(hass)
    entry = await setup_entry(
        hass, entry_data, profiles=TWINS, options={CONF_DETECT: False}
    )
    await apply(hass, "Emica")

    await hass.config_entries.async_reload(entry.entry_id)
    await settle(hass)

    assert hass.states.get(SENSOR).state == "Emica"


async def test_a_restored_choice_counts_only_while_it_holds(
    hass: HomeAssistant, entry_data, calls
):
    """A device that moved in the meantime must not be claimed for a profile."""
    set_device_state(hass)
    entry = await setup_entry(
        hass, entry_data, profiles=TWINS, options={CONF_DETECT: False}
    )
    await apply(hass, "Emica")

    set_device_state(hass, temperature=26)
    await hass.config_entries.async_reload(entry.entry_id)
    await settle(hass)

    assert hass.states.get(SENSOR).state == "Custom"


# --- capturing automatically ------------------------------------------------


@pytest.fixture(autouse=True)
def quick_auto_capture(monkeypatch):
    monkeypatch.setattr(coordinator_module, "AUTO_CAPTURE_QUIET_SECONDS", 0.2)


def stored(entry, name: str) -> dict:
    return next(p for p in entry.options[CONF_PROFILES] if p["name"] == name)


async def test_a_change_is_written_into_the_active_profile(
    hass: HomeAssistant, entry_data, calls
):
    set_device_state(hass)
    entry = await setup_entry(
        hass,
        entry_data,
        profiles=TWINS,
        options={CONF_DETECT: False, CONF_AUTO_CAPTURE: True},
    )
    await apply(hass, "Emica")

    await set_value(hass, device={"temperature": 22}, temperature=22)
    await asyncio.sleep(0.4)
    await hass.async_block_till_done()

    assert stored(entry, "Emica")["values"]["temperature"] == 22
    # And because the profile now says 22, it is active again.
    assert hass.states.get(SENSOR).state == "Emica"


async def test_a_value_the_profile_did_not_have_is_taken_into_it(
    hass: HomeAssistant, entry_data, calls
):
    """The same thing the "save into" button stores, without asking."""
    set_device_state(hass)
    entry = await setup_entry(
        hass,
        entry_data,
        profiles=TWINS,
        options={CONF_DETECT: False, CONF_AUTO_CAPTURE: True},
    )
    await apply(hass, "Emica")

    await set_value(hass, device={"fan_mode": "high"}, fan_mode="high")
    await asyncio.sleep(0.4)
    await hass.async_block_till_done()

    assert stored(entry, "Emica")["values"]["fan_mode"] == "high"
    # And the profile matches again, so it is active rather than custom.
    assert hass.states.get(SENSOR).state == "Emica"


async def test_a_protected_profile_is_never_written_to(
    hass: HomeAssistant, entry_data, calls
):
    set_device_state(hass)
    protected = [{**TWINS[0], "protected": True}]
    entry = await setup_entry(
        hass,
        entry_data,
        profiles=protected,
        options={CONF_DETECT: False, CONF_AUTO_CAPTURE: True},
    )
    await apply(hass, "Komfort")

    await set_value(hass, device={"temperature": 22}, temperature=22)
    await asyncio.sleep(0.4)
    await hass.async_block_till_done()

    assert stored(entry, "Komfort")["values"]["temperature"] == 24
    assert hass.states.get(SENSOR).state == "Custom"


async def test_what_the_device_does_on_its_own_is_not_written(
    hass: HomeAssistant, entry_data, calls
):
    """Otherwise a device overriding a value would store its override."""
    set_device_state(hass)
    entry = await setup_entry(
        hass,
        entry_data,
        profiles=TWINS,
        options={CONF_DETECT: False, CONF_AUTO_CAPTURE: True},
    )
    await apply(hass, "Emica")

    # Nobody asked for this - the device moved by itself.
    set_device_state(hass, temperature=26)
    await settle(hass)
    await asyncio.sleep(0.4)
    await hass.async_block_till_done()

    assert stored(entry, "Emica")["values"]["temperature"] == 24
    assert hass.states.get(SENSOR).state == "Custom"
