"""Tests for readable keys: the migration from uuids, and the old ids still working."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.climate_profiles.const import (
    CONF_ADDITIONAL,
    CONF_CLIMATE_ENTITY,
    CONF_CUSTOM_NAME,
    CONF_PROFILES,
    CONF_VALUE_ORDER,
    DOMAIN,
)

from .conftest import CLIMATE, DISPLAY, FAN, SILENT, set_device_state, settle
from .test_integration import SENSOR

FAN_UUID = "afca532463034037803a1d6049c80653"
DISPLAY_UUID = "f166e4df0a454dbe93cc6b338def1721"
SILENT_UUID = "37aacc3d039c4c469ff07676b7eaf05f"
GONE_UUID = "36a089b0bd8b47619b1079682b15d870"


async def _setup_v1(hass) -> MockConfigEntry:
    """Set up an entry as 2.x stored it - uuids everywhere."""
    set_device_state(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        title="Living room",
        data={CONF_CLIMATE_ENTITY: CLIMATE},
        options={
            CONF_CUSTOM_NAME: "Custom",
            CONF_ADDITIONAL: [
                {"id": FAN_UUID, "name": "Fan speed", "entity": FAN, "order": 0},
                {"id": DISPLAY_UUID, "name": "Display", "entity": DISPLAY, "order": 1},
                {"id": SILENT_UUID, "name": "Display", "entity": SILENT, "order": 2},
            ],
            CONF_PROFILES: [
                {
                    "id": "komfort",
                    "name": "Komfort",
                    "values": {
                        "hvac_mode": "cool",
                        FAN_UUID: 42,
                        SILENT_UUID: "off",
                        # A value whose definition was deleted stays as it is.
                        GONE_UUID: "on",
                    },
                }
            ],
            CONF_VALUE_ORDER: [SILENT_UUID, "temperature", FAN_UUID],
        },
        unique_id=CLIMATE,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_uuids_become_readable_keys(hass):
    entry = await _setup_v1(hass)

    assert entry.version == 2
    assert [
        (value["id"], value["former_id"]) for value in entry.options[CONF_ADDITIONAL]
    ] == [
        ("fan_speed", FAN_UUID),
        ("display", DISPLAY_UUID),
        # Two values of one name: the second one gets a counter.
        ("display_2", SILENT_UUID),
    ]
    assert entry.options[CONF_PROFILES][0]["values"] == {
        "hvac_mode": "cool",
        "fan_speed": 42,
        "display_2": "off",
        GONE_UUID: "on",
    }
    assert entry.options[CONF_VALUE_ORDER] == ["display_2", "temperature", "fan_speed"]


async def test_the_migrated_profile_still_matches(hass):
    await _setup_v1(hass)

    assert hass.states.get(SENSOR).state == "Komfort"


async def test_set_value_takes_the_old_id(hass, calls):
    """An automation written for 2.x keeps working."""
    await _setup_v1(hass)

    await hass.services.async_call(
        DOMAIN,
        "set_value",
        {"entity_id": SENSOR, DISPLAY_UUID: "on"},
        blocking=True,
    )
    await settle(hass)

    assert calls["turn_on"][-1].data == {"entity_id": DISPLAY}


async def test_the_card_learns_the_old_id(hass):
    """``hide`` on a dashboard still names the uuid - the card needs both."""
    await _setup_v1(hass)

    definitions = hass.states.get(SENSOR).attributes["additional_values"]
    assert {(d["id"], d["former_id"]) for d in definitions} == {
        ("fan_speed", FAN_UUID),
        ("display", DISPLAY_UUID),
        ("display_2", SILENT_UUID),
    }


async def test_a_newer_version_is_not_loaded(hass):
    set_device_state(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        data={CONF_CLIMATE_ENTITY: CLIMATE},
        options={},
        unique_id=CLIMATE,
    )
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
