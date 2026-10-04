"""Tests for the profile data model and its storage representation."""

from __future__ import annotations

import pytest

from custom_components.climate_profiles.models import (
    ClimateProfile,
    EntityMap,
    ProfileError,
    ProfileSet,
    color_to_rgb,
    normalise_color,
)

from .conftest import profile


def test_round_trip_through_storage(profiles):
    restored = ProfileSet.from_list(profiles.as_list())
    assert restored.as_list() == profiles.as_list()


def test_ids_stay_stable_when_a_profile_is_renamed():
    original = ClimateProfile(id="abc", name="Komfort", values={"hvac_mode": "cool"})
    renamed = ClimateProfile(
        id=original.id, name="Wohlfuehlen", values=original.values, color=original.color
    )
    assert ProfileSet((renamed,)).get("abc").name == "Wohlfuehlen"


def test_duplicate_ids_are_repaired_on_load():
    raw = [
        {"id": "same", "name": "A", "values": {"hvac_mode": "off"}},
        {"id": "same", "name": "B", "values": {"hvac_mode": "cool"}},
    ]
    loaded = ProfileSet.from_list(raw)
    assert len({p.id for p in loaded}) == 2


def test_duplicate_names_get_distinct_display_names():
    duplicated = ProfileSet(
        (profile("Komfort", {"hvac_mode": "cool"}, "a"), profile("Komfort", {}, "b"))
    )
    assert list(duplicated.display_names().values()) == ["Komfort", "Komfort (2)"]


def test_resolve_by_id_and_by_name(profiles):
    assert profiles.resolve("Komfort").name == "Komfort"
    assert profiles.resolve("komfort").name == "Komfort"
    assert profiles.resolve(profiles.profiles[0].id).name == "Aus"
    assert profiles.resolve("gibt es nicht") is None
    assert profiles.resolve("") is None


def test_unknown_value_keys_survive_storage():
    """A value whose additional value was deleted must not break the profile.

    Keys cannot be checked here any more: four are the climate ones, the rest
    are ids this class knows nothing about. The vocabulary drops what is not
    usable, at the point where it knows.
    """
    profile = ClimateProfile.from_dict({"name": "X", "values": {"7f3a": True}})
    assert profile.values == {"7f3a": True}


def test_nameless_profile_is_rejected():
    with pytest.raises(ProfileError):
        ClimateProfile.from_dict({"values": {"hvac_mode": "off"}})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("#3B82F6", "#3b82f6"),
        ("#abc", "#aabbcc"),
        ([59, 130, 246], "#3b82f6"),
        ("nonsense", "#03a9f4"),
        (None, "#03a9f4"),
    ],
)
def test_color_normalisation(raw, expected):
    assert normalise_color(raw) == expected


def test_color_round_trip():
    assert color_to_rgb("#3b82f6") == [59, 130, 246]


def test_entity_map_reports_its_entities(entities, bare_entities):
    assert entities.entity_for("hvac_mode") == "climate.living_room"
    assert entities.entity_for("fan") == "number.living_room_fan_speed"
    assert entities.entity_for("nothing like it") is None
    assert len(entities.all_entities()) == 4

    assert bare_entities.all_entities() == ("climate.living_room",)
    assert bare_entities.entity_for("fan") is None


def test_entity_map_requires_a_climate_entity():
    with pytest.raises(ProfileError):
        EntityMap.from_config({})
