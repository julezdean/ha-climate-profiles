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
    ADDITIONAL_DOMAINS,
    CLIMATE_KEYS,
    CLIMATE_KINDS,
    CONF_ADDITIONAL_ENTITY,
    CONF_ADDITIONAL_ICON,
    CONF_ADDITIONAL_ID,
    CONF_ADDITIONAL_NAME,
    CONF_ADDITIONAL_ORDER,
    CONF_CLIMATE_ENTITY,
    CONF_PROFILE_COLOR,
    CONF_PROFILE_ICON,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_PROFILE_PROTECTED,
    CONF_PROFILE_VALUES,
    DEFAULT_PROFILE_COLOR,
    KIND_NUMBER,
    KIND_OPTION,
    VALUE_HVAC_MODE,
    VALUE_SWING_MODE,
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

        # Keys are not validated here. Four of them are the climate ones; the
        # rest are ids of additional values, which this class has no way of
        # knowing about - and a value whose additional value was deleted has to
        # survive in storage rather than make the whole profile unreadable.
        # ``Vocabulary`` decides at runtime what is usable.
        values = {str(key): value for key, value in raw_values.items()}

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
class AdditionalValue:
    """One user defined value, backed by an entity of their choosing.

    The three optional entities this replaced - a fan speed number and two
    switches - were the vocabulary of one air conditioner. Everything here is
    the user's: which entity, what it is called, which icon it carries.
    """

    #: Stable and meaningless, like a profile's. Profiles store their values
    #: under it, so renaming the value or pointing it at a different entity
    #: leaves every profile intact.
    id: str
    name: str
    entity: str
    icon: str | None = None
    order: int = 0

    @property
    def domain(self) -> str:
        """Return the domain of the entity behind this value."""
        return self.entity.partition(".")[0]

    @property
    def kind(self) -> str | None:
        """Return how this value is compared and written, or ``None``.

        ``None`` means the entity is of a domain whose state is not a single
        value, which the config flow does not offer in the first place.
        """
        return ADDITIONAL_DOMAINS.get(self.domain)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AdditionalValue:
        """Build an additional value from its stored representation."""
        if not isinstance(raw, dict):
            raise ProfileError(
                f"additional value must be a mapping, got {type(raw).__name__}"
            )
        name = str(raw.get(CONF_ADDITIONAL_NAME, "") or "").strip()
        if not name:
            raise ProfileError("additional value needs a name")
        entity = str(raw.get(CONF_ADDITIONAL_ENTITY, "") or "").strip()
        if not entity:
            raise ProfileError(f"additional value {name!r} needs an entity")

        icon = raw.get(CONF_ADDITIONAL_ICON) or None
        try:
            order = int(raw.get(CONF_ADDITIONAL_ORDER, 0) or 0)
        except (TypeError, ValueError):
            order = 0
        return cls(
            id=str(raw.get(CONF_ADDITIONAL_ID) or new_value_id()),
            name=name,
            entity=entity,
            icon=str(icon) if icon else None,
            order=order,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the storage representation."""
        data: dict[str, Any] = {
            CONF_ADDITIONAL_ID: self.id,
            CONF_ADDITIONAL_NAME: self.name,
            CONF_ADDITIONAL_ENTITY: self.entity,
            CONF_ADDITIONAL_ORDER: self.order,
        }
        if self.icon:
            data[CONF_ADDITIONAL_ICON] = self.icon
        return data


def new_value_id() -> str:
    """Return a fresh, stable id for an additional value."""
    return uuid4().hex


@dataclass(frozen=True, slots=True)
class AdditionalValueSet:
    """The additional values of one config entry, in their configured order."""

    values: tuple[AdditionalValue, ...] = ()

    @classmethod
    def from_list(cls, raw: Any) -> AdditionalValueSet:
        """Build the set from its stored representation."""
        if not raw:
            return cls()
        if not isinstance(raw, list):
            raise ProfileError("additional values must be a list")
        built = tuple(AdditionalValue.from_dict(item) for item in raw)
        return cls(tuple(sorted(built, key=lambda value: value.order)))

    def as_list(self) -> list[dict[str, Any]]:
        """Return the storage representation."""
        return [value.as_dict() for value in self.values]

    def get(self, value_id: str) -> AdditionalValue | None:
        """Return the value with that id, if there is one."""
        return next((v for v in self.values if v.id == value_id), None)

    def resolve(self, reference: str) -> AdditionalValue | None:
        """Return the value an id or a name refers to.

        Ids win over names, so a value literally named like another one's id
        cannot shadow it - the same rule profiles follow.
        """
        if not reference:
            return None
        if (by_id := self.get(reference)) is not None:
            return by_id
        wanted = reference.strip().casefold()
        return next((v for v in self.values if v.name.casefold() == wanted), None)

    def unique_name(self, name: str, *, ignoring: str | None = None) -> str:
        """Return ``name``, with a counter appended if it is already taken.

        Names are kept unique here rather than disambiguated on the way out,
        because a name is pre-filled from the entity: two device switches are
        both called "Silent" without anybody deciding that, and the collision
        would otherwise surface in an automation at runtime.
        """
        taken = {
            v.name.casefold()
            for v in self.values
            if ignoring is None or v.id != ignoring
        }
        wanted = name.strip() or "Value"
        if wanted.casefold() not in taken:
            return wanted
        count = 2
        while f"{wanted} ({count})".casefold() in taken:
            count += 1
        return f"{wanted} ({count})"

    def next_order(self) -> int:
        """Return the order a newly added value should get."""
        return max((v.order for v in self.values), default=-1) + 1

    def replaced(self, value: AdditionalValue) -> AdditionalValueSet:
        """Return a copy with ``value`` in place of the one with its id."""
        return AdditionalValueSet(
            tuple(value if v.id == value.id else v for v in self.values)
        )

    def appended(self, value: AdditionalValue) -> AdditionalValueSet:
        """Return a copy with ``value`` added at the end."""
        return AdditionalValueSet((*self.values, value))

    def without(self, value_ids: set[str]) -> AdditionalValueSet:
        """Return a copy without the values carrying those ids."""
        return AdditionalValueSet(
            tuple(v for v in self.values if v.id not in value_ids)
        )

    def entity_ids(self) -> tuple[str, ...]:
        """Return every entity behind these values."""
        return tuple(v.entity for v in self.values)

    def as_frontend(self, vocab: Vocabulary | None = None) -> list[dict[str, Any]]:
        """Return the definitions the card needs to label and draw them.

        With a vocabulary the limits come along - a slider needs its range and
        a dropdown its options, and both belong to the entity behind the value
        rather than to its definition.
        """
        entries: list[dict[str, Any]] = []
        for value in self.values:
            entry: dict[str, Any] = {
                "id": value.id,
                "name": value.name,
                "entity": value.entity,
                "icon": value.icon,
                "order": value.order,
                "kind": value.kind,
            }
            if vocab is not None and (spec := vocab.get(value.id)) is not None:
                entry |= {
                    "min": spec.minimum,
                    "max": spec.maximum,
                    "step": spec.step,
                    "options": list(spec.options),
                }
            entries.append(entry)
        return entries

    def __iter__(self):
        """Iterate over the values in order."""
        return iter(self.values)

    def __len__(self) -> int:
        """Return how many values are configured."""
        return len(self.values)


@dataclass(frozen=True, slots=True)
class EntityMap:
    """The entities a config entry drives.

    The climate entity is identity - it is what the entry is about and cannot
    be changed. The additional ones hang off their own definitions, so this
    class only carries what they add up to.
    """

    climate: str
    additional: AdditionalValueSet = field(default_factory=AdditionalValueSet)

    @classmethod
    def from_config(
        cls, data: dict[str, Any], additional: AdditionalValueSet | None = None
    ) -> EntityMap:
        """Build the entity map from a config entry's data and options."""
        climate = data.get(CONF_CLIMATE_ENTITY)
        if not climate:
            raise ProfileError("a climate entity is required")
        return cls(
            climate=str(climate),
            additional=additional or AdditionalValueSet(),
        )

    def entity_for(self, key: str) -> str | None:
        """Return the entity that carries the profile value ``key``."""
        if key in CLIMATE_KINDS:
            return self.climate
        value = self.additional.get(key)
        return value.entity if value else None

    def all_entities(self) -> tuple[str, ...]:
        """Return every configured entity id."""
        return (self.climate, *self.additional.entity_ids())

    def as_dict(self) -> dict[str, Any]:
        """Return a representation for the frontend."""
        return {
            "climate": self.climate,
            "additional": {v.id: v.entity for v in self.additional},
        }


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What the climate entity supports, read from its state.

    Nothing here is hard coded - the values come from the entity's
    ``hvac_modes``/``fan_modes``/``swing_modes``/``min_temp``/``max_temp``/
    ``target_temp_step`` attributes. What an additional value supports is read
    from its own entity and lives in its :class:`ValueSpec`.
    """

    hvac_modes: tuple[str, ...] = ()
    fan_modes: tuple[str, ...] = ()
    swing_modes: tuple[str, ...] = ()
    min_temp: float | None = None
    max_temp: float | None = None
    temp_step: float = 0.5

    def options_for(self, key: str) -> tuple[str, ...]:
        """Return the supported options of an option valued climate key."""
        return {
            VALUE_HVAC_MODE: self.hvac_modes,
            "fan_mode": self.fan_modes,
            VALUE_SWING_MODE: self.swing_modes,
        }.get(key, ())

    def as_dict(self) -> dict[str, Any]:
        """Return a representation for the frontend."""
        return {
            "hvac_modes": list(self.hvac_modes),
            "fan_modes": list(self.fan_modes),
            "swing_modes": list(self.swing_modes),
            "min_temp": self.min_temp,
            "max_temp": self.max_temp,
            "target_temp_step": self.temp_step,
        }


@dataclass(frozen=True, slots=True)
class ValueSpec:
    """Everything the matching rules need to know about one value.

    This is what replaced the constants: ``matching`` used to look up whether a
    key was boolean, numeric or a string in a frozenset, and its range in
    ``Capabilities``. With entities the user picks, all of that is runtime
    knowledge - so it is handed in as data, and ``matching`` keeps its promise
    of importing nothing from Home Assistant.
    """

    key: str
    kind: str
    entity: str
    #: Empty for the four climate keys: they are labelled by the card itself.
    name: str = ""
    options: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    step: float = 1.0

    @property
    def domain(self) -> str:
        """Return the domain of the entity behind this value."""
        return self.entity.partition(".")[0]

    @property
    def is_climate(self) -> bool:
        """Return whether this value lives on the climate entity itself."""
        return self.key in CLIMATE_KINDS


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """The values one config entry knows about, in the order they are applied.

    The four climate keys come first - ``hvac_mode`` before everything else,
    because most devices ignore the rest while they are off - then the
    additional values in their configured order.
    """

    specs: tuple[ValueSpec, ...] = ()

    @classmethod
    def build(
        cls,
        entities: EntityMap,
        caps: Capabilities | None = None,
        *,
        additional_specs: dict[str, dict[str, Any]] | None = None,
    ) -> Vocabulary:
        """Assemble the vocabulary of a config entry.

        ``additional_specs`` carries what each additional value's entity says
        about itself - ``options`` for the select domains, ``min``/``max``/
        ``step`` for the number ones. The coordinator reads it from the states;
        leaving it out yields specs without limits, which compare fine and only
        lose the range check when applying.
        """
        caps = caps or Capabilities()
        limits = additional_specs or {}
        specs: list[ValueSpec] = [
            ValueSpec(
                key=key,
                kind=CLIMATE_KINDS[key],
                entity=entities.climate,
                options=caps.options_for(key),
                minimum=caps.min_temp if key == VALUE_TEMPERATURE else None,
                maximum=caps.max_temp if key == VALUE_TEMPERATURE else None,
                step=caps.temp_step if key == VALUE_TEMPERATURE else 1.0,
            )
            for key in CLIMATE_KEYS
        ]
        for value in entities.additional:
            if (kind := value.kind) is None:
                # A domain that is not offered any more, or was hand edited
                # into the options. Not usable, so not part of the vocabulary.
                continue
            limit = limits.get(value.id, {})
            specs.append(
                ValueSpec(
                    key=value.id,
                    kind=kind,
                    entity=value.entity,
                    name=value.name,
                    options=tuple(limit.get("options") or ()),
                    minimum=limit.get("min"),
                    maximum=limit.get("max"),
                    step=float(limit.get("step") or 1.0),
                )
            )
        return cls(tuple(specs))

    def get(self, key: str) -> ValueSpec | None:
        """Return the spec of ``key``, or ``None`` when it is not usable."""
        return next((spec for spec in self.specs if spec.key == key), None)

    def keys(self) -> tuple[str, ...]:
        """Return every usable key, in apply order."""
        return tuple(spec.key for spec in self.specs)

    def numeric_keys(self) -> tuple[str, ...]:
        """Return the keys compared as numbers."""
        return tuple(s.key for s in self.specs if s.kind == KIND_NUMBER)

    def option_keys(self) -> tuple[str, ...]:
        """Return the keys compared as options."""
        return tuple(s.key for s in self.specs if s.kind == KIND_OPTION)

    def __contains__(self, key: object) -> bool:
        """Return whether ``key`` is usable in this entry."""
        return any(spec.key == key for spec in self.specs)

    def __iter__(self):
        """Iterate over the specs in apply order."""
        return iter(self.specs)

    def __len__(self) -> int:
        """Return how many values are usable."""
        return len(self.specs)
