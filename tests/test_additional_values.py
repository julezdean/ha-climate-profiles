"""The whole way of an additional value: added, stored in a profile, applied.

The other tests use speaking ids so their data stays readable. This one goes
through the options flow, so the id is the uuid production hands out - which is
the point: nothing here is left over from the three fixed entities.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.climate_profiles.const import (
    CONF_ADDITIONAL,
    CONF_CLIMATE_ENTITY,
    CONF_PROFILE_NAME,
    CONF_PROFILES,
    DOMAIN,
)

from .conftest import CLIMATE, FAN, open_step, set_device_state, settle
from .test_integration import setup_entry


def _rows(result) -> list[dict]:
    """Return the rows a list form hands out."""
    for key in result["data_schema"].schema:
        if key in (CONF_ADDITIONAL, CONF_PROFILES):
            return list(key.description["suggested_value"])
    raise AssertionError("no list in this form")


async def _add_value(hass: HomeAssistant, entry, entity_id: str) -> dict:
    """Add one additional value through the value list and return it."""
    result = await open_step(hass, entry, "values")
    await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ADDITIONAL: [*_rows(result), {"entity": entity_id}]}
    )
    await hass.async_block_till_done()
    return entry.options[CONF_ADDITIONAL][-1]


async def _add_profile(hass: HomeAssistant, entry, row: dict) -> None:
    """Add one profile through the profile list."""
    result = await open_step(hass, entry, "profiles")
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_PROFILES: [*_rows(result), row],
            "custom_profile_name": "Custom",
            "custom_profile_color": [120, 144, 156],
        },
    )
    await hass.async_block_till_done()


async def test_a_value_is_stored_in_a_profile_under_its_id(hass: HomeAssistant):
    set_device_state(hass)
    entry = await setup_entry(
        hass, {CONF_CLIMATE_ENTITY: CLIMATE}, profiles=[], options={CONF_ADDITIONAL: []}
    )

    value = await _add_value(hass, entry, FAN)
    # A real id, not the name and not the entity id.
    assert len(value["id"]) == 32
    assert value["entity"] == FAN

    await _add_profile(
        hass,
        entry,
        {
            CONF_PROFILE_NAME: "Breezy",
            "color": [34, 197, 94],
            "capture": "ask",
            "hvac_mode": "cool",
            value["id"]: 80,
        },
    )

    stored = entry.options[CONF_PROFILES][0]["values"]
    assert stored == {"hvac_mode": "cool", value["id"]: 80}


async def test_applying_that_profile_writes_to_the_entity_behind_it(
    hass: HomeAssistant,
):
    set_device_state(hass)
    entry = await setup_entry(
        hass, {CONF_CLIMATE_ENTITY: CLIMATE}, profiles=[], options={CONF_ADDITIONAL: []}
    )
    value = await _add_value(hass, entry, FAN)

    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            CONF_PROFILES: [
                {
                    "id": "breezy",
                    "name": "Breezy",
                    "color": "#22c55e",
                    "values": {"hvac_mode": "cool", value["id"]: 80},
                }
            ],
        },
    )
    await settle(hass)

    calls = async_mock_service(hass, "number", "set_value")
    await hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": "sensor.living_room_climate_profile", "profile": "Breezy"},
        blocking=True,
    )
    await settle(hass)

    # The service follows from the entity's domain, the target from the value.
    assert [call.data["value"] for call in calls] == [80]
    assert calls[0].data["entity_id"] == FAN


# --- the order --------------------------------------------------------------


async def test_values_can_be_moved_before_the_climate_ones(hass: HomeAssistant):
    """A silent mode that sets its own fan speed wins or loses by its place."""
    set_device_state(hass)
    entry = await setup_entry(
        hass, {CONF_CLIMATE_ENTITY: CLIMATE}, profiles=[], options={CONF_ADDITIONAL: []}
    )
    value = await _add_value(hass, entry, FAN)

    result = await open_step(hass, entry, "values")
    offered = [
        option["value"]
        for option in result["data_schema"].schema["order"].config["options"]
    ]
    # The mode is never offered - it always goes first.
    assert "hvac_mode" not in offered
    assert offered == ["temperature", "swing_mode", "fan_mode", value["id"]]

    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_ADDITIONAL: _rows(result), "order": [value["id"], "temperature"]},
    )
    await hass.async_block_till_done()

    # Picked first, the rest keeps its place behind.
    assert entry.options["value_order"] == [
        value["id"],
        "temperature",
        "swing_mode",
        "fan_mode",
    ]


async def test_the_order_decides_the_calls(hass: HomeAssistant):
    """hvac_mode first whatever the list says, then exactly the given order."""
    set_device_state(hass, hvac_mode="off")
    entry = await setup_entry(
        hass, {CONF_CLIMATE_ENTITY: CLIMATE}, profiles=[], options={CONF_ADDITIONAL: []}
    )
    value = await _add_value(hass, entry, FAN)
    hass.config_entries.async_update_entry(
        entry,
        options={
            **entry.options,
            "value_order": [value["id"], "hvac_mode", "fan_mode"],
            CONF_PROFILES: [
                {
                    "id": "p",
                    "name": "P",
                    "color": "#22c55e",
                    "values": {
                        "fan_mode": "high",
                        "hvac_mode": "cool",
                        value["id"]: 80,
                    },
                }
            ],
        },
    )
    await settle(hass)

    order: list[str] = []
    for domain, service in (
        ("climate", "set_hvac_mode"),
        ("climate", "set_fan_mode"),
        ("number", "set_value"),
    ):
        hass.services.async_register(
            domain,
            service,
            lambda call, name=f"{domain}.{service}": order.append(name),
        )

    await hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": "sensor.living_room_climate_profile", "profile": "P"},
        blocking=True,
    )

    assert order == [
        "climate.set_hvac_mode",
        "number.set_value",
        "climate.set_fan_mode",
    ]


async def test_a_catch_all_profile_is_pointed_out(hass: HomeAssistant, caplog):
    """Why does my narrow profile never show? Because a broader one covers it."""
    set_device_state(hass)
    entry = await setup_entry(
        hass, {CONF_CLIMATE_ENTITY: CLIMATE}, profiles=[], options={CONF_ADDITIONAL: []}
    )

    await _add_profile(
        hass,
        entry,
        {
            CONF_PROFILE_NAME: "Cooling",
            "color": [1, 2, 3],
            "capture": "ask",
            "hvac_mode": "cool",
        },
    )
    await _add_profile(
        hass,
        entry,
        {
            CONF_PROFILE_NAME: "Comfort",
            "color": [1, 2, 3],
            "capture": "ask",
            "hvac_mode": "cool",
            "temperature": 24,
        },
    )

    assert "Profile Cooling is a catch-all for Comfort" in caplog.text


# --- the shortcut over the device -------------------------------------------


async def _device_with_siblings(hass: HomeAssistant):
    """Register a climate entity and its siblings on one device.

    Returns ``{name: entity_id}`` - the registry makes the ids itself, so they
    have to be read back rather than guessed.
    """
    from homeassistant.const import EntityCategory
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    host = MockConfigEntry(domain="demo")
    host.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=host.entry_id,
        identifiers={("demo", "portasplit")},
        name="PortaSplit",
    )
    registry = er.async_get(hass)
    ids: dict[str, str] = {}
    for domain, object_id, name, category in (
        ("climate", "portasplit", "PortaSplit", None),
        ("number", "portasplit_fan", "Fan speed", None),
        ("switch", "portasplit_display", "Display", None),
        ("select", "portasplit_preset", "Preset", None),
        ("number", "portasplit_calibration", "Calibration", EntityCategory.CONFIG),
        ("sensor", "portasplit_battery", "Battery", EntityCategory.DIAGNOSTIC),
        ("sensor", "portasplit_rssi", "Link quality", EntityCategory.DIAGNOSTIC),
        ("number", "portasplit_hidden", "Hidden one", EntityCategory.DIAGNOSTIC),
    ):
        entry = registry.async_get_or_create(
            domain, "demo", object_id, device_id=device.id, original_name=name
        )
        if category is not None:
            registry.async_update_entity(entry.entity_id, entity_category=category)
        hass.states.async_set(entry.entity_id, "off", {"friendly_name": name})
        ids[name] = entry.entity_id
    return ids


async def test_the_device_offers_its_siblings(hass: HomeAssistant):
    """Three clicks instead of three searches - and nothing that cannot work."""
    ids = await _device_with_siblings(hass)
    entry = await setup_entry(
        hass,
        {CONF_CLIMATE_ENTITY: ids["PortaSplit"]},
        profiles=[],
        options={CONF_ADDITIONAL: []},
    )

    result = await open_step(hass, entry, "values")
    offered = {
        option["label"]
        for option in result["data_schema"].schema["selected"].config["options"]
    }

    # The climate entity itself is not a value, a sensor cannot be set, and a
    # diagnostic entity is not something a profile holds.
    assert offered == {"Fan speed", "Display", "Preset", "Calibration"}

    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_ADDITIONAL: _rows(result),
            "selected": [ids["Fan speed"], ids["Display"]],
        },
    )
    await hass.async_block_till_done()

    added = entry.options[CONF_ADDITIONAL]
    assert [value["name"] for value in added] == ["Fan speed", "Display"]
    assert all(len(value["id"]) == 32 for value in added)


async def test_what_is_already_configured_is_not_offered_again(hass: HomeAssistant):
    ids = await _device_with_siblings(hass)
    entry = await setup_entry(
        hass,
        {CONF_CLIMATE_ENTITY: ids["PortaSplit"]},
        profiles=[],
        options={
            CONF_ADDITIONAL: [
                {"id": "f", "name": "Fan speed", "entity": ids["Fan speed"], "order": 0}
            ]
        },
    )

    result = await open_step(hass, entry, "values")
    offered = {
        option["label"]
        for option in result["data_schema"].schema["selected"].config["options"]
    }

    assert "Fan speed" not in offered


async def test_a_climate_entity_without_a_device_does_not_offer_the_step(
    hass: HomeAssistant,
):
    """Template and helper entities have no device - the menu stays honest."""
    set_device_state(hass)
    entry = await setup_entry(
        hass, {CONF_CLIMATE_ENTITY: CLIMATE}, profiles=[], options={CONF_ADDITIONAL: []}
    )

    result = await open_step(hass, entry, "values")

    assert "selected" not in result["data_schema"].schema
