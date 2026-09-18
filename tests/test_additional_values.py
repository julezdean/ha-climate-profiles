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

from .conftest import CLIMATE, FAN, set_device_state, settle
from .test_integration import setup_entry


async def _add_value(hass: HomeAssistant, entry, entity_id: str) -> dict:
    """Add one additional value through the options flow and return it."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_value"}
    )
    await hass.config_entries.options.async_configure(
        result["flow_id"], {"entity": entity_id}
    )
    await hass.async_block_till_done()
    return entry.options[CONF_ADDITIONAL][-1]


async def test_a_value_is_stored_in_a_profile_under_its_id(hass: HomeAssistant):
    set_device_state(hass)
    entry = await setup_entry(
        hass, {CONF_CLIMATE_ENTITY: CLIMATE}, profiles=[], options={CONF_ADDITIONAL: []}
    )

    value = await _add_value(hass, entry, FAN)
    # A real id, not the name and not the entity id.
    assert len(value["id"]) == 32
    assert value["entity"] == FAN

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "add_profile"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_PROFILE_NAME: "Breezy",
            "color": [34, 197, 94],
            "hvac_mode": "cool",
            value["id"]: 80,
        },
    )
    await hass.async_block_till_done()

    stored = result["data"][CONF_PROFILES][0]["values"]
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

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "reorder_values"}
    )
    offered = [
        option["value"]
        for option in result["data_schema"].schema["order"].config["options"]
    ]
    # The mode is never offered - it always goes first.
    assert "hvac_mode" not in offered
    assert offered == ["temperature", "swing_mode", "fan_mode", value["id"]]

    await hass.config_entries.options.async_configure(
        result["flow_id"], {"order": [value["id"], "temperature"]}
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
