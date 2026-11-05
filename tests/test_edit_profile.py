"""Tests for editing a profile's values - what the card's edit mode calls."""

from __future__ import annotations

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_profiles.const import (
    CONF_ADDITIONAL,
    CONF_CLIMATE_ENTITY,
    CONF_CUSTOM_NAME,
    CONF_PROFILES,
    DOMAIN,
)

from .conftest import CLIMATE, additional_option, set_device_state, settle
from .test_integration import PROFILES, SENSOR, setup_entry


def _values(entry, profile_id: str) -> dict:
    return next(p for p in entry.options[CONF_PROFILES] if p["id"] == profile_id)[
        "values"
    ]


async def edit(hass, profile: str, values: dict) -> None:
    await hass.services.async_call(
        DOMAIN,
        "edit_profile",
        {"entity_id": SENSOR, "profile": profile, "values": values},
        blocking=True,
    )
    await settle(hass)


async def test_a_value_of_another_profile_is_only_stored(hass, entry_data, calls):
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)

    await edit(hass, "Kuehlung", {"temperature": 21})

    assert _values(entry, "kuehlung")["temperature"] == 21
    assert not calls["set_temperature"]


async def test_a_value_of_the_active_profile_is_applied(hass, entry_data, calls):
    """Komfort is active - raised, it stays active and the device follows."""
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)
    assert hass.states.get(SENSOR).state == "Komfort"

    await edit(hass, "Komfort", {"temperature": 25})

    assert _values(entry, "komfort")["temperature"] == 25
    assert calls["set_temperature"][-1].data["temperature"] == 25


async def test_a_value_is_put_in_and_taken_out(hass, entry_data, calls):
    """Every value can be set - also one the profile did not set before."""
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)

    await edit(hass, "Kuehlung", {"fan_mode": "HIGH", "display": True})
    assert _values(entry, "kuehlung") == {
        "hvac_mode": "cool",
        "temperature": 22,
        # In the device's own spelling, and the way the options store it.
        "fan_mode": "high",
        "display": "on",
    }

    await edit(hass, "Kuehlung", {"fan_mode": None, "Display": None})
    assert _values(entry, "kuehlung") == {"hvac_mode": "cool", "temperature": 22}


async def test_the_mode_cannot_be_taken_out(hass, entry_data):
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    with pytest.raises(ServiceValidationError) as err:
        await edit(hass, "Kuehlung", {"hvac_mode": None})
    assert err.value.translation_key == "profile_needs_a_mode"


async def test_write_protection_does_not_keep_an_edit_out(hass, entry_data, calls):
    """Protection is about changes made on the device, not to the profile."""
    set_device_state(hass)
    profiles = [{**p, "protected": True} for p in PROFILES]
    entry = await setup_entry(hass, entry_data, profiles=profiles)

    await edit(hass, "Kuehlung", {"temperature": 20})

    assert _values(entry, "kuehlung")["temperature"] == 20


async def test_a_value_the_device_cannot_take_is_refused(hass, entry_data):
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    with pytest.raises(ServiceValidationError) as err:
        await edit(hass, "Kuehlung", {"display": "vielleicht"})
    assert err.value.translation_key == "invalid_profile_value"


async def test_an_unknown_profile_is_refused(hass, entry_data):
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    with pytest.raises(ServiceValidationError) as err:
        await edit(hass, "Gibt es nicht", {"temperature": 20})
    assert err.value.translation_key == "unknown_profile"


async def test_the_entities_of_beta_1_are_taken_out(hass):
    """3.0.0-beta.1 made an entity per profile value; nothing provides them now."""
    set_device_state(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        title="Living room",
        data={CONF_CLIMATE_ENTITY: CLIMATE},
        options={
            CONF_PROFILES: PROFILES,
            CONF_CUSTOM_NAME: "Custom",
            CONF_ADDITIONAL: additional_option(),
        },
        unique_id=CLIMATE,
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    stale = registry.async_get_or_create(
        "number",
        DOMAIN,
        f"{entry.entry_id}_value_komfort_temperature",
        config_entry=entry,
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(stale.entity_id) is None
    assert registry.async_get(SENSOR) is not None
