"""Data model of the Climate Profiles integration.

Pure data, no Home Assistant imports - see ``matching`` for the behaviour that
operates on these objects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import uuid4

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_DISPLAY_ENTITY,
    CONF_FAN_ENTITY,
    CONF_PROFILE_COLOR,
    CONF_PROFILE_ICON,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_PROFILE_PROTECTED,
    CONF_PROFILE_VALUES,
    CONF_SILENT_ENTITY,
    DEFAULT_PROFILE_COLOR,
    KEY_REQUIRES_ENTITY,
    VALUE_FAN,
    VALUE_KEYS,
    VALUE_TEMPERATURE,
)

_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class ProfileError(ValueError):
    """Raised when a profile definition is not usable."""


def normalise_color(raw: Any, default: str = DEFAULT_PROFILE_COLOR) -> str:
    """Return ``raw`` as a ``#rrggbb`` string, falling back to ``default``.

    Accepts ``#abc``, ``#aabbcc`` and the ``[r, g, b]`` list that Home
    Assistant's colour selector hands back.
    """
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        try:
            r, g, b = (max(0, min(255, int(channel))) for channel in raw)
        except (TypeError, ValueError):
            return default
        return f"#{r:02x}{g:02x}{b:02x}"

    if isinstance(raw, str):
        value = raw.strip()
        if _HEX_COLOR.match(value):
            if len(value) == 4:  # #abc -> #aabbcc
                return "#" + "".join(channel * 2 for channel in value[1:]).lower()
            return value.lower()

    return default


def color_to_rgb(color: str) -> list[int]:
    """Return ``color`` as an ``[r, g, b]`` list for Home Assistant selectors."""
    value = normalise_color(color)
    return [int(value[i : i + 2], 16) for i in (1, 3, 5)]


@dataclass(frozen=True, slots=True)
class ClimateProfile:
    """A stored profile.

    ``values`` only contains the keys the user actually defined - a missing key
    means "do not touch", both when matching and when applying.

    The position inside :class:`ProfileSet` is the single source of truth for
    the ordering; ``order`` is derived from it rather than stored, so the two
    can never disagree after an edit.
    """

    id: str
    name: str
    color: str = DEFAULT_PROFILE_COLOR
    values: dict[str, Any] = field(default_factory=dict)
    icon: str | None = None
    #: Protected profiles refuse to be overwritten by "capture". They can
    #: still be edited deliberately in the options flow - otherwise a
    #: protected profile would be frozen forever.
    protected: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ClimateProfile:
        """Build a profile from its stored representation."""
        if not isinstance(raw, dict):
            raise ProfileError(f"profile must be a mapping, got {type(raw).__name__}")

        name = str(raw.get(CONF_PROFILE_NAME, "") or "").strip()
        if not name:
            raise ProfileError("profile needs a name")

        raw_values = raw.get(CONF_PROFILE_VALUES) or {}
        if not isinstance(raw_values, dict):
            raise ProfileError(f"values of profile {name!r} must be a mapping")

        values = {key: raw_values[key] for key in VALUE_KEYS if key in raw_values}
        unknown = set(raw_values) - set(VALUE_KEYS)
        if unknown:
            raise ProfileError(
                f"profile {name!r} has unsupported keys: {', '.join(sorted(unknown))}"
            )

        icon = raw.get(CONF_PROFILE_ICON) or None
        return cls(
            id=str(raw.get(CONF_PROFILE_ID) or new_profile_id()),
            name=name,
            color=normalise_color(raw.get(CONF_PROFILE_COLOR)),
            values=values,
            icon=str(icon) if icon else None,
            protected=bool(raw.get(CONF_PROFILE_PROTECTED, False)),
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the storage representation."""
        data: dict[str, Any] = {
            CONF_PROFILE_ID: self.id,
            CONF_PROFILE_NAME: self.name,
            CONF_PROFILE_COLOR: self.color,
            CONF_PROFILE_VALUES: dict(self.values),
        }
        if self.icon:
            data[CONF_PROFILE_ICON] = self.icon
        if self.protected:
            data[CONF_PROFILE_PROTECTED] = True
        return data

    def with_values(self, values: dict[str, Any]) -> ClimateProfile:
        """Return a copy carrying ``values``, everything else unchanged."""
        return replace(self, values=dict(values))


def new_profile_id() -> str:
    """Return a fresh, stable profile id."""
    return uuid4().hex


@dataclass(frozen=True, slots=True)
class ProfileSet:
    """An ordered collection of profiles with unique ids."""

    profiles: tuple[ClimateProfile, ...] = ()

    @classmethod
    def from_list(cls, raw: Any) -> ProfileSet:
        """Build a profile set from the stored list, skipping nothing silently."""
        if raw is None:
            return cls()
        if not isinstance(raw, (list, tuple)):
            raise ProfileError("profiles must be a list")

        profiles: list[ClimateProfile] = []
        seen: set[str] = set()
        for item in raw:
            profile = ClimateProfile.from_dict(item)
            if profile.id in seen:
                # Duplicate ids would make "edit profile" ambiguous; a fresh id
                # is always safe because ids are opaque.
                profile = replace(profile, id=new_profile_id())
            seen.add(profile.id)
            profiles.append(profile)
        return cls(tuple(profiles))

    def as_list(self) -> list[dict[str, Any]]:
        """Return the storage representation."""
        return [profile.as_dict() for profile in self.profiles]

    def replaced(self, profile: ClimateProfile) -> ProfileSet:
        """Return a set with ``profile`` in place of the one with its id."""
        return ProfileSet(
            tuple(profile if p.id == profile.id else p for p in self.profiles)
        )

    def appended(self, profile: ClimateProfile) -> ProfileSet:
        """Return a set with ``profile`` added at the end."""
        return ProfileSet((*self.profiles, profile))

    def without(self, profile_ids: set[str]) -> ProfileSet:
        """Return a set without the given profiles."""
        return ProfileSet(tuple(p for p in self.profiles if p.id not in profile_ids))

    def get(self, profile_id: str) -> ClimateProfile | None:
        """Return the profile with ``profile_id``, or ``None``."""
        return next((p for p in self.profiles if p.id == profile_id), None)

    def resolve(self, reference: str) -> ClimateProfile | None:
        """Resolve a profile by id or (case insensitive) by name.

        Services take whatever the user typed; ids win over names so a profile
        literally named like another one's id cannot shadow it.
        """
        if not reference:
            return None
        if (by_id := self.get(reference)) is not None:
            return by_id
        wanted = reference.strip().casefold()
        return next(
            (p for p in self.profiles if p.name.casefold() == wanted),
            None,
        )

    def display_names(self) -> dict[str, str]:
        """Return ``{profile_id: unique display name}``.

        Names are free text and may collide; a ``select`` entity needs distinct
        options, so duplicates get a numeric suffix.
        """
        used: dict[str, int] = {}
        names: dict[str, str] = {}
        for profile in self.profiles:
            count = used.get(profile.name.casefold(), 0) + 1
            used[profile.name.casefold()] = count
            names[profile.id] = (
                profile.name if count == 1 else f"{profile.name} ({count})"
            )
        return names

    def __iter__(self):
        """Iterate over the profiles in order."""
        return iter(self.profiles)

    def __len__(self) -> int:
        """Return how many profiles are stored."""
        return len(self.profiles)

    def __bool__(self) -> bool:
        """Return whether any profile is stored."""
        return bool(self.profiles)


@dataclass(frozen=True, slots=True)
class EntityMap:
    """The entities a config entry drives. Everything but climate is optional."""

    climate: str
    fan: str | None = None
    display: str | None = None
    silent: str | None = None

    @classmethod
    def from_config(cls, data: dict[str, Any]) -> EntityMap:
        """Build the entity map from a config entry's data."""
        climate = data.get(CONF_CLIMATE_ENTITY)
        if not climate:
            raise ProfileError("a climate entity is required")
        return cls(
            climate=str(climate),
            fan=data.get(CONF_FAN_ENTITY) or None,
            display=data.get(CONF_DISPLAY_ENTITY) or None,
            silent=data.get(CONF_SILENT_ENTITY) or None,
        )

    def entity_for(self, key: str) -> str | None:
        """Return the entity that carries the profile value ``key``."""
        if key in (CONF_FAN_ENTITY, VALUE_FAN):
            return self.fan
        if key in (CONF_DISPLAY_ENTITY, "display"):
            return self.display
        if key in (CONF_SILENT_ENTITY, "silent"):
            return self.silent
        return self.climate

    def supports(self, key: str) -> bool:
        """Return whether the value ``key`` can be used at all."""
        if (conf_key := KEY_REQUIRES_ENTITY.get(key)) is None:
            return True
        return self.entity_for(conf_key) is not None

    def all_entities(self) -> tuple[str, ...]:
        """Return every configured entity id."""
        return tuple(
            entity
            for entity in (self.climate, self.fan, self.display, self.silent)
            if entity
        )

    def as_dict(self) -> dict[str, str | None]:
        """Return a representation for the frontend."""
        return {
            "climate": self.climate,
            "fan": self.fan,
            "display": self.display,
            "silent": self.silent,
        }


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What the configured devices actually support, read from their states.

    Nothing here is hard coded - the values come from the climate entity's
    ``hvac_modes``/``fan_modes``/``swing_modes``/``min_temp``/``max_temp``/
    ``target_temp_step`` attributes and from the number entity's ``min``/
    ``max``/``step``.
    """

    hvac_modes: tuple[str, ...] = ()
    fan_modes: tuple[str, ...] = ()
    swing_modes: tuple[str, ...] = ()
    min_temp: float | None = None
    max_temp: float | None = None
    temp_step: float = 0.5
    fan_min: float | None = None
    fan_max: float | None = None
    fan_step: float = 1.0

    def options_for(self, key: str) -> tuple[str, ...]:
        """Return the supported options of a string valued key."""
        return {
            "hvac_mode": self.hvac_modes,
            "fan_mode": self.fan_modes,
            "swing_mode": self.swing_modes,
        }.get(key, ())

    def step_for(self, key: str) -> float:
        """Return the step width used to compare a numeric key."""
        return self.fan_step if key == VALUE_FAN else self.temp_step

    def range_for(self, key: str) -> tuple[float | None, float | None]:
        """Return ``(min, max)`` of a numeric key."""
        if key == VALUE_TEMPERATURE:
            return self.min_temp, self.max_temp
        if key == VALUE_FAN:
            return self.fan_min, self.fan_max
        return None, None

    def as_dict(self) -> dict[str, Any]:
        """Return a representation for the frontend."""
        return {
            "hvac_modes": list(self.hvac_modes),
            "fan_modes": list(self.fan_modes),
            "swing_modes": list(self.swing_modes),
            "min_temp": self.min_temp,
            "max_temp": self.max_temp,
            "target_temp_step": self.temp_step,
            "fan_min": self.fan_min,
            "fan_max": self.fan_max,
            "fan_step": self.fan_step,
        }
