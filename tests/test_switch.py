"""The write protection of each profile, as a switch."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.climate_profiles.const import CONF_PROFILES, DOMAIN

from .conftest import CLIMATE, set_device_state, settle
from .test_integration import PROFILES, SENSOR, setup_entry

KOMFORT = "switch.living_room_komfort_write_protected"
AUS = "switch.living_room_aus_write_protected"


def stored(entry, profile_id: str) -> dict:
    return next(p for p in entry.options[CONF_PROFILES] if p["id"] == profile_id)


async def switch(hass: HomeAssistant, entity_id: str, on: bool) -> None:
    await hass.services.async_call(
        "switch",
        "turn_on" if on else "turn_off",
        {"entity_id": entity_id},
        blocking=True,
    )
    await settle(hass)


async def test_every_profile_has_a_switch(hass, entry_data):
    profiles = [dict(p) for p in PROFILES]
    profiles[0]["protected"] = True  # Aus
    set_device_state(hass)
    await setup_entry(hass, entry_data, profiles=profiles)

    assert hass.states.get(AUS).state == STATE_ON
    assert hass.states.get(KOMFORT).state == STATE_OFF
    assert hass.states.get(KOMFORT).attributes["friendly_name"] == (
        "Living room Komfort write protected"
    )
    entry = er.async_get(hass).async_get(KOMFORT)
    assert entry.entity_category is EntityCategory.CONFIG


async def test_switching_stores_the_protection_without_a_reload(hass, entry_data):
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)

    seen: list[str] = []
    hass.bus.async_listen(
        "state_changed",
        lambda event: (
            seen.append(event.data["new_state"].state)
            if event.data["entity_id"] == SENSOR and event.data["new_state"]
            else None
        ),
    )

    await switch(hass, KOMFORT, True)
    assert stored(entry, "komfort")["protected"] is True
    assert hass.states.get(KOMFORT).state == STATE_ON
    listed = hass.states.get(SENSOR).attributes["profiles"]
    assert next(p for p in listed if p["id"] == "komfort")["protected"] is True

    await switch(hass, KOMFORT, False)
    assert "protected" not in stored(entry, "komfort")
    assert hass.states.get(KOMFORT).state == STATE_OFF
    assert "unavailable" not in seen, f"the sensor went through {seen}"


async def test_the_sensor_names_each_profiles_switch(hass, entry_data):
    """The card flips the switch itself, so it has to know which one it is."""
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    listed = hass.states.get(SENSOR).attributes["profiles"]
    assert next(p for p in listed if p["id"] == "komfort")["protection_entity"] == (
        KOMFORT
    )


async def test_a_new_profile_gets_a_switch_and_a_deleted_one_loses_it(hass, entry_data):
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)
    nacht = {
        "id": "nacht",
        "name": "Nacht",
        "color": "#8b5cf6",
        "values": {"hvac_mode": "cool", "temperature": 26},
    }

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_PROFILES: [*PROFILES, nacht]}
    )
    await settle(hass)

    added = "switch.living_room_nacht_write_protected"
    assert hass.states.get(added).state == STATE_OFF
    # And the card learns about it without waiting for the next change.
    listed = hass.states.get(SENSOR).attributes["profiles"]
    assert next(p for p in listed if p["id"] == "nacht")["protection_entity"] == added

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_PROFILES: PROFILES}
    )
    await settle(hass)

    assert hass.states.get(added) is None
    assert er.async_get(hass).async_get(added) is None


async def test_a_switch_left_behind_is_removed_on_setup(hass, entry_data):
    """A profile deleted while the entry was not loaded took nothing with it."""
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_PROFILES: PROFILES[1:]}
    )
    assert er.async_get(hass).async_get(AUS) is not None

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get(AUS) is None
    assert hass.states.get(KOMFORT) is not None


async def test_renaming_a_profile_renames_its_switch_only(hass, entry_data):
    """The entity id stays - automations point at it."""
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)

    renamed = [
        {**p, "name": "Gemütlich"} if p["id"] == "komfort" else p for p in PROFILES
    ]
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_PROFILES: renamed}
    )
    await settle(hass)

    assert hass.states.get(KOMFORT).attributes["friendly_name"] == (
        "Living room Gemütlich write protected"
    )


async def test_the_switch_does_not_follow_the_device(hass, entry_data):
    """Protection is a setting: it can be changed while the device is away."""
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)

    hass.states.async_set(CLIMATE, STATE_UNAVAILABLE)
    await settle(hass)
    assert hass.states.get(SENSOR).state == STATE_UNAVAILABLE
    assert hass.states.get(KOMFORT).state == STATE_OFF

    await switch(hass, KOMFORT, True)
    assert stored(entry, "komfort")["protected"] is True


async def test_switches_belong_to_the_device(hass, entry_data):
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)

    registry = er.async_get(hass)
    sensor = registry.async_get(SENSOR)
    protection = registry.async_get(KOMFORT)
    assert protection.device_id == sensor.device_id
    assert protection.platform == DOMAIN
    assert protection.config_entry_id == entry.entry_id
