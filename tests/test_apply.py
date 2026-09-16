"""Tests for turning a profile into service calls."""

from __future__ import annotations

from custom_components.climate_profiles.matching import build_apply_plan

from .conftest import CLIMATE, DISPLAY, FAN, SILENT


def calls_by_key(plan):
    return {call.key: call for call in plan.calls}


def test_partial_profile_only_touches_defined_keys(entities, caps, komfort_state):
    komfort_state |= {"hvac_mode": "cool", "temperature": 26}
    plan = build_apply_plan(
        {"hvac_mode": "cool", "temperature": 24}, komfort_state, entities, caps
    )
    assert [call.key for call in plan.calls] == ["temperature"]
    assert plan.calls[0].domain == "climate"
    assert plan.calls[0].service == "set_temperature"
    assert plan.calls[0].data == {"temperature": 24.0}


def test_values_that_already_match_produce_no_call(entities, caps, komfort_state):
    plan = build_apply_plan(
        {"hvac_mode": "cool", "temperature": 24, "fan_mode": "auto"},
        komfort_state,
        entities,
        caps,
    )
    assert plan.calls == ()


def test_a_mode_change_re_sends_every_defined_value(entities, caps):
    """The device resets its attributes on a mode change, so do not trust them."""
    current = {"hvac_mode": "off", "temperature": 24, "fan_mode": "auto"}
    plan = build_apply_plan(
        {"hvac_mode": "cool", "temperature": 24, "fan_mode": "auto"},
        current,
        entities,
        caps,
    )
    assert [call.key for call in plan.calls] == ["hvac_mode", "temperature", "fan_mode"]


def test_apply_order_matches_the_original_script(entities, caps):
    plan = build_apply_plan(
        {
            "silent": "off",
            "display": "off",
            "fan": 100,
            "fan_mode": "auto",
            "swing_mode": "vertical",
            "temperature": 16,
            "hvac_mode": "cool",
        },
        {"hvac_mode": "off"},
        entities,
        caps,
    )
    assert [call.key for call in plan.calls] == [
        "hvac_mode",
        "temperature",
        "swing_mode",
        "fan_mode",
        "fan",
        "display",
        "silent",
    ]


def test_each_value_goes_to_its_own_entity(entities, caps):
    plan = calls_by_key(
        build_apply_plan(
            {"fan": 100, "display": "on", "silent": "off", "temperature": 20},
            {},
            entities,
            caps,
        )
    )
    assert plan["fan"].entity_id == FAN
    assert plan["fan"].data == {"value": 100.0}
    assert (plan["display"].entity_id, plan["display"].service) == (DISPLAY, "turn_on")
    assert (plan["silent"].entity_id, plan["silent"].service) == (SILENT, "turn_off")
    assert plan["temperature"].entity_id == CLIMATE


def test_optional_entities_are_reported_not_crashed(bare_entities, caps):
    plan = build_apply_plan(
        {"hvac_mode": "cool", "fan": 100, "display": "on", "silent": "on"},
        {},
        bare_entities,
        caps,
    )
    assert [call.key for call in plan.calls] == ["hvac_mode"]
    assert set(plan.unsupported) == {"fan", "display", "silent"}


def test_unsupported_mode_is_rejected_instead_of_sent(entities, caps):
    plan = build_apply_plan({"hvac_mode": "heat_cool"}, {}, entities, caps)
    assert plan.calls == ()
    assert plan.unsupported == ("hvac_mode",)


def test_service_call_uses_the_devices_own_spelling(entities, caps):
    plan = build_apply_plan({"fan_mode": "AUTO"}, {}, entities, caps)
    assert plan.calls[0].data == {"fan_mode": "auto"}


def test_out_of_range_temperature_is_applied_but_flagged(entities, caps):
    """min/max depend on the hvac mode, so refusing outright would be wrong."""
    plan = build_apply_plan({"temperature": 5}, {}, entities, caps)
    assert plan.calls[0].data == {"temperature": 5.0}
    assert plan.warnings == ("temperature",)


def test_force_re_sends_everything(entities, caps, komfort_state):
    plan = build_apply_plan(
        {"hvac_mode": "cool", "temperature": 24},
        komfort_state,
        entities,
        caps,
        force=True,
    )
    assert [call.key for call in plan.calls] == ["hvac_mode", "temperature"]


def test_empty_profile_does_nothing(entities, caps, komfort_state):
    assert build_apply_plan({}, komfort_state, entities, caps).calls == ()
