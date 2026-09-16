"""Profile matching and profile application - the single source of truth.

Everything in here is a pure function over plain data. The coordinator reads
the states, calls into this module and executes the resulting plan; no matching
rule lives anywhere else (and none of it lives in the frontend).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .const import (
    BOOLEAN_KEYS,
    FLOAT_EPSILON,
    KEY_REQUIRES_ENTITY,
    NUMERIC_KEYS,
    STRING_KEYS,
    VALUE_DISPLAY,
    VALUE_FAN,
    VALUE_FAN_MODE,
    VALUE_HVAC_MODE,
    VALUE_KEYS,
    VALUE_SILENT,
    VALUE_SWING_MODE,
    VALUE_TEMPERATURE,
)
from .models import Capabilities, ClimateProfile, EntityMap, ProfileSet

_LOGGER = logging.getLogger(__name__)

#: States that mean "no value at all".
_EMPTY_STATES = frozenset({"", "unknown", "unavailable", "none", "null"})
_TRUE_STATES = frozenset({"on", "true", "yes", "1", "open", "home"})
_FALSE_STATES = frozenset({"off", "false", "no", "0", "closed", "not_home"})


# ---------------------------------------------------------------------------
# normalisation
# ---------------------------------------------------------------------------


def normalise_value(key: str, raw: Any) -> Any | None:
    """Return ``raw`` in the canonical form used for comparison.

    ``None`` means "no usable value" - an unavailable entity, an empty string
    or garbage. A profile that defines such a key can never match.
    """
    if raw is None:
        return None

    if key in BOOLEAN_KEYS:
        return _to_bool(raw)
    if key in NUMERIC_KEYS:
        return _to_float(raw)
    if key in STRING_KEYS:
        return _to_str(raw)
    return None


def _to_bool(raw: Any) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return bool(raw)
    text = str(raw).strip().casefold()
    if text in _TRUE_STATES:
        return True
    if text in _FALSE_STATES:
        return False
    return None


def _to_float(raw: Any) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(",", ".")
    if text.casefold() in _EMPTY_STATES:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_str(raw: Any) -> str | None:
    # YAML turns a bare ``off``/``on`` into a bool - an easy way to write
    # ``hvac_mode: off`` by accident, so map it back instead of failing.
    if isinstance(raw, bool):
        return "on" if raw else "off"
    text = str(raw).strip().casefold()
    return None if text in _EMPTY_STATES else text


def normalise_values(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise a whole mapping, dropping keys without a usable value."""
    result: dict[str, Any] = {}
    for key in VALUE_KEYS:
        if key not in raw:
            continue
        value = normalise_value(key, raw[key])
        if value is not None:
            result[key] = value
    return result


def canonical_option(value: str, options: Sequence[str]) -> str | None:
    """Return the device's own spelling of ``value``.

    Comparison is case insensitive (the reference YAML lower-cased fan modes),
    but the service call has to use the exact string the device advertises.
    Returns ``None`` when the device does not support the value at all.
    """
    wanted = _to_str(value)
    if wanted is None:
        return None
    if not options:
        # The device does not advertise a list - pass the value through and
        # let the device decide.
        return str(value)
    return next((option for option in options if _to_str(option) == wanted), None)


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------


def values_equal(
    key: str, left: Any, right: Any, caps: Capabilities | None = None
) -> bool:
    """Compare two *normalised* values of ``key``.

    Floats are compared with half the device's step width as tolerance, so a
    device reporting ``23.999`` still matches a profile asking for ``24``.
    """
    if left is None or right is None:
        return False
    if key in NUMERIC_KEYS:
        step = (caps or Capabilities()).step_for(key)
        tolerance = max(abs(step) / 2.0, FLOAT_EPSILON)
        return abs(float(left) - float(right)) <= tolerance
    return left == right


def profile_matches(
    profile: ClimateProfile,
    current_values: Mapping[str, Any],
    caps: Capabilities | None = None,
) -> bool:
    """Return whether every value defined by ``profile`` is currently set.

    Keys the profile does not define are ignored - a profile is a partial
    description of a state, not a full one. A profile without any value never
    matches; it would otherwise match everything.
    """
    wanted = normalise_values(profile.values)
    if not wanted:
        return False

    current = normalise_values(current_values)
    return all(
        values_equal(key, value, current.get(key), caps)
        for key, value in wanted.items()
    )


def resolve_active_profile(
    profiles: ProfileSet,
    current_values: Mapping[str, Any],
    caps: Capabilities | None = None,
) -> ClimateProfile | None:
    """Return the first matching profile, or ``None`` for "custom".

    ``None`` is the virtual custom profile: it has no stored values and never
    writes anything back, it is purely a statement about the current state.
    """
    for profile in profiles:
        if profile_matches(profile, current_values, caps):
            return profile
    return None


# ---------------------------------------------------------------------------
# applying
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileServiceCall:
    """One service call produced by :func:`build_apply_plan`."""

    domain: str
    service: str
    entity_id: str
    data: dict[str, Any] = field(default_factory=dict)
    key: str = ""

    def as_tuple(self) -> tuple[str, str, str, tuple[tuple[str, Any], ...]]:
        """Return a hashable representation of the call."""
        return (
            self.domain,
            self.service,
            self.entity_id,
            tuple(sorted(self.data.items())),
        )


@dataclass(frozen=True, slots=True)
class ApplyPlan:
    """What applying a profile would do."""

    calls: tuple[ProfileServiceCall, ...] = ()
    #: Keys that cannot be applied at all (missing entity, unsupported value).
    unsupported: tuple[str, ...] = ()
    #: Keys that are applied but look wrong (e.g. outside the device's range).
    warnings: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        """Return whether the plan does anything at all."""
        return bool(self.calls)


def build_apply_plan(
    values: Mapping[str, Any],
    current_values: Mapping[str, Any],
    entities: EntityMap,
    caps: Capabilities | None = None,
    *,
    force: bool = False,
) -> ApplyPlan:
    """Turn a (partial) set of values into the service calls needed for it.

    Rules, in order of importance:

    * only keys present in ``values`` are touched - everything else keeps its
      current value, exactly like the original script's ``choose`` blocks;
    * a value that already matches produces no service call;
    * but when the hvac mode changes, every other defined value is re-sent:
      many devices reset their attributes on a mode change, so the state we
      compared against is about to become stale.
    """
    caps = caps or Capabilities()
    current = normalise_values(current_values)

    wanted: dict[str, Any] = {}
    unsupported: list[str] = []
    warnings: list[str] = []

    for key in VALUE_KEYS:
        if key not in values:
            continue
        if key in KEY_REQUIRES_ENTITY and not entities.supports(key):
            unsupported.append(key)
            continue
        value = normalise_value(key, values[key])
        if value is None:
            unsupported.append(key)
            continue
        if key in STRING_KEYS:
            option = canonical_option(value, caps.options_for(key))
            if option is None:
                unsupported.append(key)
                continue
            wanted[key] = option
            continue
        if key in NUMERIC_KEYS:
            low, high = caps.range_for(key)
            if (low is not None and value < low - FLOAT_EPSILON) or (
                high is not None and value > high + FLOAT_EPSILON
            ):
                # Ranges can depend on the hvac mode, so this is not fatal -
                # send it anyway and let the user know it looks off.
                warnings.append(key)
        wanted[key] = value

    mode_changes = VALUE_HVAC_MODE in wanted and not values_equal(
        VALUE_HVAC_MODE,
        normalise_value(VALUE_HVAC_MODE, wanted[VALUE_HVAC_MODE]),
        current.get(VALUE_HVAC_MODE),
        caps,
    )
    resend_everything = force or mode_changes

    calls: list[ProfileServiceCall] = []
    for key in VALUE_KEYS:  # VALUE_KEYS carries the apply order
        if key not in wanted:
            continue
        value = wanted[key]
        compare = normalise_value(key, value)
        if not resend_everything and values_equal(key, compare, current.get(key), caps):
            continue
        call = _build_call(key, value, entities)
        if call is None:
            unsupported.append(key)
            continue
        calls.append(call)

    return ApplyPlan(tuple(calls), tuple(unsupported), tuple(warnings))


def _build_call(key: str, value: Any, entities: EntityMap) -> ProfileServiceCall | None:
    """Return the service call that writes ``value`` to the right entity."""
    if key == VALUE_HVAC_MODE:
        return ProfileServiceCall(
            "climate", "set_hvac_mode", entities.climate, {"hvac_mode": value}, key
        )
    if key == VALUE_TEMPERATURE:
        return ProfileServiceCall(
            "climate", "set_temperature", entities.climate, {"temperature": value}, key
        )
    if key == VALUE_SWING_MODE:
        return ProfileServiceCall(
            "climate", "set_swing_mode", entities.climate, {"swing_mode": value}, key
        )
    if key == VALUE_FAN_MODE:
        return ProfileServiceCall(
            "climate", "set_fan_mode", entities.climate, {"fan_mode": value}, key
        )
    if key == VALUE_FAN and entities.fan:
        return ProfileServiceCall(
            "number", "set_value", entities.fan, {"value": value}, key
        )
    if key == VALUE_DISPLAY and entities.display:
        return ProfileServiceCall(
            "switch", "turn_on" if value else "turn_off", entities.display, {}, key
        )
    if key == VALUE_SILENT and entities.silent:
        return ProfileServiceCall(
            "switch", "turn_on" if value else "turn_off", entities.silent, {}, key
        )
    return None


# ---------------------------------------------------------------------------
# capturing - writing the current state back into a profile
# ---------------------------------------------------------------------------


def storage_value(key: str, value: Any, caps: Capabilities | None = None) -> Any:
    """Return a normalised value in the form profiles are stored in.

    Booleans become ``"on"``/``"off"`` so the options flow can show them in its
    dropdown, whole numbers lose their ``.0``, and strings keep the device's
    own spelling.
    """
    if value is None:
        return None
    if key in BOOLEAN_KEYS:
        return "on" if value else "off"
    if key in NUMERIC_KEYS:
        number = round(float(value), 2)
        return int(number) if float(number).is_integer() else number
    if key in STRING_KEYS:
        return (
            canonical_option(str(value), (caps or Capabilities()).options_for(key))
            or value
        )
    return value


def changed_keys(
    baseline: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    caps: Capabilities | None = None,
) -> tuple[str, ...]:
    """Return the keys whose value differs from ``baseline``.

    Without a baseline nothing counts as changed - after a restart there is no
    point of reference, and guessing would be worse than saying so.
    """
    if baseline is None:
        return ()
    before = normalise_values(baseline)
    now = normalise_values(current)
    return tuple(
        key
        for key in VALUE_KEYS
        if key in now and not values_equal(key, now[key], before.get(key), caps)
    )


def capture_values(
    profile_values: Mapping[str, Any],
    current_values: Mapping[str, Any],
    entities: EntityMap,
    *,
    baseline: Mapping[str, Any] | None = None,
    keys: Sequence[str] | None = None,
    caps: Capabilities | None = None,
) -> dict[str, Any]:
    """Return what ``profile_values`` should become after capturing the state.

    Three rules, in this order:

    * every key the profile already defines is updated to the current value;
    * a key the profile does not define is added only when it actually changed
      since the profile last matched (``baseline``) - so a partial profile
      grows by what you deliberately adjusted, not by everything the device
      happens to report;
    * ``keys`` overrides both and captures exactly those.

    A value that cannot be read right now is never written. Keys the profile
    already has keep their stored value in that case rather than disappearing.
    """
    current = normalise_values(current_values)
    wanted: list[str] = (
        list(keys)
        if keys is not None
        else [
            key
            for key in VALUE_KEYS
            if key in profile_values
            or key in changed_keys(baseline, current_values, caps)
        ]
    )

    captured = dict(profile_values)
    for key in VALUE_KEYS:
        if key not in wanted or not entities.supports(key):
            continue
        value = storage_value(key, current.get(key), caps)
        if value is None:
            continue
        captured[key] = value
    return captured


def usable_values(values: Mapping[str, Any], entities: EntityMap) -> dict[str, Any]:
    """Drop values whose optional entity is not configured."""
    return {key: value for key, value in values.items() if entities.supports(key)}
