"""Tests for writing the current state back into a profile."""

from __future__ import annotations

from custom_components.climate_profiles.matching import (
    capture_values,
    changed_keys,
    storage_value,
)

from .conftest import profile

KOMFORT = {
    "hvac_mode": "cool",
    "temperature": 24,
    "swing_mode": "off",
    "fan_mode": "auto",
    "display": "off",
    "silent": "off",
}


# --- storage form ----------------------------------------------------------


def test_values_are_stored_the_way_the_options_flow_shows_them(caps):
    assert storage_value("display", True) == "on"
    assert storage_value("silent", False) == "off"
    assert storage_value("temperature", 24.0) == 24
    assert storage_value("temperature", 21.5) == 21.5
    # The device's own spelling survives, not the lower cased comparison form.
    assert storage_value("fan_mode", "auto", caps) == "auto"


# --- what counts as changed ------------------------------------------------


def test_changed_keys_needs_a_baseline(komfort_state, caps):
    assert changed_keys(None, komfort_state, caps) == ()


def test_changed_keys_finds_exactly_what_moved(komfort_state, caps):
    now = komfort_state | {"temperature": 23, "fan_mode": "high"}
    assert changed_keys(komfort_state, now, caps) == ("temperature", "fan_mode")


# --- capturing -------------------------------------------------------------


def test_defined_values_are_updated(entities, caps, komfort_state):
    now = komfort_state | {"temperature": 23}
    captured = capture_values(KOMFORT, now, entities, baseline=komfort_state, caps=caps)
    assert captured["temperature"] == 23
    assert captured["hvac_mode"] == "cool"


def test_a_partial_profile_grows_by_what_was_adjusted(entities, caps, komfort_state):
    """A profile that says nothing about the fan - until you change the fan."""
    partial = {"hvac_mode": "cool", "temperature": 24}
    now = komfort_state | {"fan_mode": "high"}

    captured = capture_values(partial, now, entities, baseline=komfort_state, caps=caps)
    assert captured == {"hvac_mode": "cool", "temperature": 24, "fan_mode": "high"}


def test_untouched_values_do_not_sneak_in(entities, caps, komfort_state):
    """Capturing must not turn every partial profile into a full one."""
    partial = {"hvac_mode": "cool", "temperature": 24}
    now = komfort_state | {"temperature": 22}

    captured = capture_values(partial, now, entities, baseline=komfort_state, caps=caps)
    assert set(captured) == {"hvac_mode", "temperature"}
    assert captured["temperature"] == 22


def test_without_a_baseline_only_known_values_are_updated(
    entities, caps, komfort_state
):
    """After a restart there is no point of reference, so nothing is added."""
    partial = {"hvac_mode": "cool", "temperature": 24}
    now = komfort_state | {"temperature": 22, "fan_mode": "high"}

    captured = capture_values(partial, now, entities, baseline=None, caps=caps)
    assert set(captured) == {"hvac_mode", "temperature"}
    assert captured["temperature"] == 22


def test_explicit_keys_win_over_everything(entities, caps, komfort_state):
    partial = {"hvac_mode": "cool"}
    now = komfort_state | {"temperature": 22, "fan_mode": "high"}

    captured = capture_values(
        partial, now, entities, baseline=komfort_state, keys=["fan_mode"], caps=caps
    )
    # hvac_mode is kept because it was already there, fan_mode is added,
    # temperature is not - it was not asked for.
    assert captured == {"hvac_mode": "cool", "fan_mode": "high"}


def test_unreadable_values_are_not_written(entities, caps, komfort_state):
    now = komfort_state | {"silent": "unavailable"}
    captured = capture_values(KOMFORT, now, entities, baseline=komfort_state, caps=caps)
    # The stored value survives instead of being wiped.
    assert captured["silent"] == "off"


def test_values_without_an_entity_are_never_captured(
    bare_entities, caps, komfort_state
):
    captured = capture_values(
        {"hvac_mode": "cool"},
        komfort_state | {"display": "on"},
        bare_entities,
        baseline=komfort_state,
        caps=caps,
    )
    assert "display" not in captured
    assert "fan" not in captured


def test_booleans_land_in_the_profile_as_on_and_off(entities, caps, komfort_state):
    now = komfort_state | {"display": "on"}
    captured = capture_values(KOMFORT, now, entities, baseline=komfort_state, caps=caps)
    assert captured["display"] == "on"


def test_capturing_an_unchanged_state_changes_nothing(entities, caps, komfort_state):
    captured = capture_values(
        KOMFORT, komfort_state, entities, baseline=komfort_state, caps=caps
    )
    assert captured == KOMFORT


def test_a_protected_profile_is_just_data_here():
    """Protection is enforced by the coordinator, not by the pure function."""
    assert profile("X", {"hvac_mode": "cool"}).protected is False
