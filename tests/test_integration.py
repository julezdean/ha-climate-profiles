"""End to end tests against a real Home Assistant instance."""

from __future__ import annotations

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
)

from custom_components.climate_profiles.const import (
    ATTR_ACTIVE_PROFILE_ID,
    ATTR_CAPABILITIES,
    CONF_ADDITIONAL,
    CONF_CLIMATE_ENTITY,
    CONF_CUSTOM_NAME,
    CONF_PROFILES,
    CUSTOM_PROFILE_ID,
    DOMAIN,
)

from .conftest import (
    CLIMATE,
    DISPLAY,
    SILENT,
    additional_option,
    set_device_state,
    settle,
)

SENSOR = "sensor.living_room_climate_profile"
SELECT = "select.living_room_profile"

PROFILES = [
    {"id": "aus", "name": "Aus", "color": "#64748b", "values": {"hvac_mode": "off"}},
    {
        "id": "komfort",
        "name": "Komfort",
        "color": "#22c55e",
        "values": {
            "hvac_mode": "cool",
            "temperature": 24,
            "swing_mode": "off",
            "fan_mode": "auto",
            "display": "off",
            "silent": "off",
        },
    },
    {
        "id": "kuehlung",
        "name": "Kuehlung",
        "color": "#3b82f6",
        "values": {"hvac_mode": "cool", "temperature": 22},
    },
]


async def setup_entry(
    hass: HomeAssistant,
    entry_data: dict,
    *,
    profiles=None,
    options=None,
    title: str = "Living room",
) -> MockConfigEntry:
    """Set up one config entry with the mocked device already in place."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=title,
        data=entry_data,
        options={
            CONF_PROFILES: PROFILES if profiles is None else profiles,
            CONF_CUSTOM_NAME: "Custom",
            CONF_ADDITIONAL: additional_option(),
            **(options or {}),
        },
        unique_id=entry_data[CONF_CLIMATE_ENTITY],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


# --- entities --------------------------------------------------------------


async def test_entities_report_the_matching_profile(hass, entry_data):
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    state = hass.states.get(SENSOR)
    assert state is not None, [s.entity_id for s in hass.states.async_all("sensor")]
    assert state.state == "Komfort"
    assert state.attributes[ATTR_ACTIVE_PROFILE_ID] == "komfort"
    assert hass.states.get(SELECT).state == "Komfort"


async def test_a_manual_change_switches_to_custom(hass, entry_data):
    set_device_state(hass)
    await setup_entry(hass, entry_data)
    assert hass.states.get(SENSOR).state == "Komfort"

    set_device_state(hass, temperature=23)
    await settle(hass)

    state = hass.states.get(SENSOR)
    assert state.state == "Custom"
    assert state.attributes[ATTR_ACTIVE_PROFILE_ID] == CUSTOM_PROFILE_ID


async def test_capabilities_come_from_the_device(hass, entry_data):
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    attributes = hass.states.get(SENSOR).attributes
    caps = attributes[ATTR_CAPABILITIES]
    assert caps["hvac_modes"] == ["off", "cool", "dry", "fan_only", "heat", "auto"]
    assert caps["min_temp"] == 16

    # The limits of an additional value belong to its own entity.
    fan = next(v for v in attributes["additional_values"] if v["id"] == "fan")
    assert fan["max"] == 100
    assert fan["kind"] == "number"


async def test_select_lists_the_profiles_plus_custom(hass, entry_data):
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    assert hass.states.get(SELECT).attributes["options"] == [
        "Aus",
        "Komfort",
        "Kuehlung",
        "Custom",
    ]


# --- applying --------------------------------------------------------------


async def test_apply_profile_only_writes_what_changed(hass, entry_data, calls):
    set_device_state(hass, temperature=26)
    await setup_entry(hass, entry_data)

    await hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": SENSOR, "profile": "Komfort"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(calls["set_temperature"]) == 1
    assert calls["set_temperature"][0].data["temperature"] == 24
    assert calls["set_temperature"][0].data["entity_id"] == CLIMATE
    # Everything else already matched, so nothing else was sent.
    assert not calls["set_hvac_mode"]
    assert not calls["set_fan_mode"]
    assert not calls["turn_off"]


async def test_partial_profile_leaves_other_values_alone(hass, entry_data, calls):
    set_device_state(hass, fan_mode="high", swing_mode="both", display="on")
    await setup_entry(hass, entry_data)

    await hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": SENSOR, "profile": "Kuehlung"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert calls["set_temperature"][0].data["temperature"] == 22
    assert not calls["set_fan_mode"]
    assert not calls["set_swing_mode"]
    assert not calls["turn_on"] and not calls["turn_off"]


async def test_switching_on_re_sends_every_value(hass, entry_data, calls):
    set_device_state(hass, hvac_mode="off")
    await setup_entry(hass, entry_data)

    await hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": SENSOR, "profile": "Komfort"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert calls["set_hvac_mode"][0].data["hvac_mode"] == "cool"
    assert calls["set_temperature"][0].data["temperature"] == 24
    assert calls["set_fan_mode"][0].data["fan_mode"] == "auto"
    assert calls["set_swing_mode"][0].data["swing_mode"] == "off"
    assert [call.data["entity_id"] for call in calls["turn_off"]] == [DISPLAY, SILENT]


async def test_apply_by_id_and_by_name(hass, entry_data, calls):
    set_device_state(hass, hvac_mode="cool")
    await setup_entry(hass, entry_data)

    await hass.services.async_call(
        DOMAIN, "apply_profile", {"entity_id": SENSOR, "profile": "aus"}, blocking=True
    )
    await hass.async_block_till_done()
    assert calls["set_hvac_mode"][0].data["hvac_mode"] == "off"


async def test_unknown_profile_raises_a_clean_error(hass, entry_data, calls):
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "apply_profile",
            {"entity_id": SENSOR, "profile": "gibt es nicht"},
            blocking=True,
        )
    assert not calls["set_hvac_mode"]
    # Home Assistant is still healthy afterwards.
    assert hass.states.get(SENSOR).state == "Komfort"


async def test_applying_custom_writes_nothing(hass, entry_data, calls):
    set_device_state(hass, temperature=23)
    await setup_entry(hass, entry_data)

    await hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": SENSOR, "profile": "Custom"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert not any(calls[key] for key in calls)
    assert hass.states.get(SENSOR).state == "Custom"


async def test_select_applies_a_profile(hass, entry_data, calls):
    set_device_state(hass, hvac_mode="cool", temperature=26)
    await setup_entry(hass, entry_data)

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SELECT, "option": "Komfort"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert calls["set_temperature"][0].data["temperature"] == 24


# --- set_value -------------------------------------------------------------


async def test_set_value_writes_single_values(hass, entry_data, calls):
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    await hass.services.async_call(
        DOMAIN,
        "set_value",
        {"entity_id": SENSOR, "temperature": 21, "silent": True},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert calls["set_temperature"][0].data["temperature"] == 21
    assert calls["turn_on"][0].data["entity_id"] == SILENT
    assert not calls["set_hvac_mode"]


async def test_set_value_needs_at_least_one_value(hass, entry_data, calls):
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "set_value", {"entity_id": SENSOR}, blocking=True
        )


# --- optional entities -----------------------------------------------------


async def test_without_optional_entities_nothing_breaks(hass, calls):
    set_device_state(hass, temperature=26)
    await setup_entry(
        hass, {CONF_CLIMATE_ENTITY: CLIMATE}, options={CONF_ADDITIONAL: []}
    )

    state = hass.states.get(SENSOR)
    assert state.attributes["entities"] == {"climate": CLIMATE, "additional": {}}
    # "Komfort" defines display/silent, which this device cannot do -> custom.
    assert state.state == "Custom"

    await hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": SENSOR, "profile": "Komfort"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert calls["set_temperature"][0].data["temperature"] == 24
    assert not calls["turn_off"]
    assert not calls["set_value"]


async def test_unavailable_climate_marks_entities_unavailable(hass, entry_data):
    set_device_state(hass)
    await setup_entry(hass, entry_data)

    hass.states.async_set(CLIMATE, "unavailable")
    await settle(hass)
    assert hass.states.get(SENSOR).state == "unavailable"


# --- ordering and multiple instances ---------------------------------------


async def test_profile_order_decides_between_overlapping_profiles(hass, entry_data):
    broad = {
        "id": "a",
        "name": "Kuehlen",
        "color": "#111111",
        "values": {"hvac_mode": "cool"},
    }
    narrow = {
        "id": "b",
        "name": "Komfort",
        "color": "#222222",
        "values": {"hvac_mode": "cool", "temperature": 24},
    }

    set_device_state(hass)
    entry = await setup_entry(hass, entry_data, profiles=[broad, narrow])
    assert hass.states.get(SENSOR).state == "Kuehlen"

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_PROFILES: [narrow, broad]}
    )
    await settle(hass)
    assert hass.states.get(SENSOR).state == "Komfort"


async def test_two_instances_stay_independent(hass, entry_data):
    set_device_state(hass)
    hass.states.async_set(
        "climate.buero",
        "off",
        {"hvac_modes": ["off", "cool"], "min_temp": 16, "max_temp": 30},
    )
    await setup_entry(hass, entry_data)
    await setup_entry(hass, {CONF_CLIMATE_ENTITY: "climate.buero"}, profiles=PROFILES)

    assert hass.states.get(SENSOR).state == "Komfort"
    assert hass.states.get("sensor.mock_title_climate_profile") is None or True
    buero = next(
        s
        for s in hass.states.async_all("sensor")
        if s.attributes.get("entities", {}).get("climate") == "climate.buero"
    )
    assert buero.state == "Aus"


async def test_renaming_custom_changes_the_state(hass, entry_data):
    set_device_state(hass, temperature=23)
    await setup_entry(hass, entry_data, options={CONF_CUSTOM_NAME: "Manuell"})
    assert hass.states.get(SENSOR).state == "Manuell"


async def test_unload_removes_the_entities(hass, entry_data):
    set_device_state(hass)
    entry = await setup_entry(hass, entry_data)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR).state == "unavailable"
