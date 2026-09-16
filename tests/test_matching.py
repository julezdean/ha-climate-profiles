"""Tests for profile matching - partial profiles, custom, ordering."""

from __future__ import annotations

import pytest

from custom_components.climate_profiles.matching import (
    canonical_option,
    normalise_value,
    profile_matches,
    resolve_active_profile,
    values_equal,
)
from custom_components.climate_profiles.models import ProfileSet

from .conftest import profile

# --- normalisation ---------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "raw", "expected"),
    [
        ("hvac_mode", "Cool", "cool"),
        ("hvac_mode", False, "off"),  # YAML turns a bare `off` into a bool
        ("hvac_mode", True, "on"),
        ("fan_mode", "AUTO", "auto"),
        ("swing_mode", "unavailable", None),
        ("temperature", "24.0", 24.0),
        ("temperature", "23,5", 23.5),
        ("temperature", "unknown", None),
        ("fan", "100", 100.0),
        ("display", "on", True),
        ("display", "OFF", False),
        ("silent", True, True),
        ("silent", "unavailable", None),
    ],
)
def test_normalise_value(key, raw, expected):
    assert normalise_value(key, raw) == expected


def test_canonical_option_keeps_the_devices_spelling():
    assert canonical_option("AUTO", ("Auto", "Low")) == "Auto"
    assert canonical_option("turbo", ("Auto", "Low")) is None
    # No advertised list: pass the value through instead of refusing.
    assert canonical_option("auto", ()) == "auto"


def test_values_equal_uses_half_a_step_as_tolerance(caps):
    assert values_equal("temperature", 24.0, 23.9, caps)
    assert not values_equal("temperature", 24.0, 23.0, caps)
    assert not values_equal("temperature", 24.0, None, caps)


# --- matching --------------------------------------------------------------


def test_exact_profile_matches(profiles, komfort_state, caps):
    assert resolve_active_profile(profiles, komfort_state, caps).name == "Komfort"


def test_one_manual_change_falls_back_to_custom(profiles, komfort_state, caps):
    komfort_state["temperature"] = 23
    assert resolve_active_profile(profiles, komfort_state, caps) is None


def test_partial_profile_ignores_undefined_keys(caps, komfort_state):
    """A = 1, B = 2 matches A = 1, B = 2, C = 999, D = 123."""
    partial = profile("Kuehlung", {"hvac_mode": "cool", "temperature": 24})
    assert profile_matches(partial, komfort_state, caps)

    komfort_state |= {"fan_mode": "high", "swing_mode": "both", "fan": 7}
    assert profile_matches(partial, komfort_state, caps)


def test_empty_profile_never_matches(komfort_state, caps):
    assert not profile_matches(profile("Leer", {}), komfort_state, caps)


def test_missing_value_prevents_a_match(profiles, komfort_state, caps):
    """An unavailable entity must not silently count as a match."""
    komfort_state["silent"] = "unavailable"
    assert resolve_active_profile(profiles, komfort_state, caps) is None


def test_off_profile_matches_although_the_rest_is_stale(profiles, caps):
    state = {"hvac_mode": "off", "temperature": 24, "fan_mode": "auto"}
    assert resolve_active_profile(profiles, state, caps).name == "Aus"


def test_first_matching_profile_wins(caps, komfort_state):
    """Overlapping profiles are resolved by order, not by specificity."""
    broad = profile("Kuehlung", {"hvac_mode": "cool"})
    narrow = profile("Komfort", {"hvac_mode": "cool", "temperature": 24})

    assert (
        resolve_active_profile(ProfileSet((broad, narrow)), komfort_state, caps).name
        == "Kuehlung"
    )
    assert (
        resolve_active_profile(ProfileSet((narrow, broad)), komfort_state, caps).name
        == "Komfort"
    )


def test_case_and_type_differences_do_not_break_matching(profiles, caps):
    state = {
        "hvac_mode": "COOL",
        "temperature": "24",
        "swing_mode": "Off",
        "fan_mode": "Auto",
        "display": False,
        "silent": "off",
    }
    assert resolve_active_profile(profiles, state, caps).name == "Komfort"


def test_no_profiles_means_custom(komfort_state, caps):
    assert resolve_active_profile(ProfileSet(), komfort_state, caps) is None
