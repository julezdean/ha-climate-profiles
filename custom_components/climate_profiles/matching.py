"""Profile matching and profile application - the single source of truth.

Everything in here is a pure function over plain data. The coordinator reads
the states, calls into this module and executes the resulting plan; no matching
rule lives anywhere else (and none of it lives in the frontend).

What a value *is* - number, boolean or option, with which range and which
options - is not decided here. It arrives as a :class:`Vocabulary`, because
with entities the user picks it is runtime knowledge. That keeps this module
free of Home Assistant imports and testable on its own.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .const import (
    FLOAT_EPSILON,
    KIND_BOOLEAN,
    KIND_NUMBER,
    KIND_OPTION,
    VALUE_HVAC_MODE,
    VALUE_SWING_MODE,
    VALUE_TEMPERATURE,
)
from .models import ClimateProfile, ProfileSet, ValueSpec, Vocabulary

_LOGGER = logging.getLogger(__name__)

#: States that mean "no value at all".
_EMPTY_STATES = frozenset({"", "unknown", "unavailable", "none", "null"})
_TRUE_STATES = frozenset({"on", "true", "yes", "1", "open", "home"})
_FALSE_STATES = frozenset({"off", "false", "no", "0", "closed", "not_home"})

#: The service that writes each climate key. These four are Home Assistant's,
#: not ours; everything else follows from the domain of its entity.
_CLIMATE_SERVICES: dict[str, tuple[str, str]] = {
    VALUE_HVAC_MODE: ("set_hvac_mode", "hvac_mode"),
    VALUE_TEMPERATURE: ("set_temperature", "temperature"),
    VALUE_SWING_MODE: ("set_swing_mode", "swing_mode"),
    "fan_mode": ("set_fan_mode", "fan_mode"),
}


# ---------------------------------------------------------------------------
# normalisation
# ---------------------------------------------------------------------------


def normalise_value(spec: ValueSpec | None, raw: Any) -> Any | None:
    """Return ``raw`` in the canonical form used for comparison.

    ``None`` means "no usable value" - an unavailable entity, an empty string
    or garbage, or a key this entry does not know. A profile that defines such
    a key can never match.
    """
    if spec is None or raw is None:
        return None

    if spec.kind == KIND_BOOLEAN:
        return _to_bool(raw)
    if spec.kind == KIND_NUMBER:
        return _to_float(raw)
    if spec.kind == KIND_OPTION:
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


def normalise_values(vocab: Vocabulary, raw: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise a whole mapping, dropping keys without a usable value.

    Keys the vocabulary does not know are dropped too: an additional value that
    was deleted leaves its values behind in every profile that set it, and they
    have to stay harmless rather than make the profile unmatchable.
    """
    result: dict[str, Any] = {}
    for spec in vocab:
        if spec.key not in raw:
            continue
        value = normalise_value(spec, raw[spec.key])
        if value is not None:
            result[spec.key] = value
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


def values_equal(spec: ValueSpec | None, left: Any, right: Any) -> bool:
    """Compare two *normalised* values of one key.

    Floats are compared with half the entity's step width as tolerance, so a
    device reporting ``23.999`` still matches a profile asking for ``24``.
    """
    if spec is None or left is None or right is None:
        return False
    if spec.kind == KIND_NUMBER:
        tolerance = max(abs(spec.step) / 2.0, FLOAT_EPSILON)
        return abs(float(left) - float(right)) <= tolerance
    return left == right


def profile_matches(
    profile: ClimateProfile,
    current_values: Mapping[str, Any],
    vocab: Vocabulary,
) -> bool:
    """Return whether every value defined by ``profile`` is currently set.

    Keys the profile does not define are ignored - a profile is a partial
    description of a state, not a full one. A profile without any usable value
    never matches; it would otherwise match everything.
    """
    wanted = normalise_values(vocab, profile.values)
    if not wanted:
        return False

    current = normalise_values(vocab, current_values)
    return all(
        values_equal(vocab.get(key), value, current.get(key))
        for key, value in wanted.items()
    )


def resolve_active_profile(
    profiles: ProfileSet,
    current_values: Mapping[str, Any],
    vocab: Vocabulary,
) -> ClimateProfile | None:
    """Return the first matching profile, or ``None`` for "custom".

    ``None`` is the virtual custom profile: it has no stored values and never
    writes anything back, it is purely a statement about the current state.
    """
    for profile in profiles:
        if profile_matches(profile, current_values, vocab):
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
    #: Keys that cannot be applied at all (unknown key, unsupported value).
    unsupported: tuple[str, ...] = ()
    #: Keys that are applied but look wrong (e.g. outside the entity's range).
    warnings: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        """Return whether the plan does anything at all."""
        return bool(self.calls)


def build_apply_plan(
    values: Mapping[str, Any],
    current_values: Mapping[str, Any],
    vocab: Vocabulary,
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
    current = normalise_values(vocab, current_values)

    wanted: dict[str, Any] = {}
    unsupported: list[str] = []
    warnings: list[str] = []

    for key in values:
        spec = vocab.get(key)
        if spec is None:
            # Either an additional value that is gone, or one whose entity is
            # of a domain that carries no single value.
            unsupported.append(key)
            continue
        value = normalise_value(spec, values[key])
        if value is None:
            unsupported.append(key)
            continue
        if spec.kind == KIND_OPTION:
            option = canonical_option(value, spec.options)
            if option is None:
                unsupported.append(key)
                continue
            wanted[key] = option
            continue
        if spec.kind == KIND_NUMBER:
            low, high = spec.minimum, spec.maximum
            if (low is not None and value < low - FLOAT_EPSILON) or (
                high is not None and value > high + FLOAT_EPSILON
            ):
                # Ranges can depend on the hvac mode, so this is not fatal -
                # send it anyway and let the user know it looks off.
                warnings.append(key)
        wanted[key] = value

    mode_spec = vocab.get(VALUE_HVAC_MODE)
    mode_changes = VALUE_HVAC_MODE in wanted and not values_equal(
        mode_spec,
        normalise_value(mode_spec, wanted[VALUE_HVAC_MODE]),
        current.get(VALUE_HVAC_MODE),
    )
    resend_everything = force or mode_changes

    calls: list[ProfileServiceCall] = []
    for spec in vocab:  # the vocabulary carries the apply order
        if spec.key not in wanted:
            continue
        value = wanted[spec.key]
        compare = normalise_value(spec, value)
        if not resend_everything and values_equal(spec, compare, current.get(spec.key)):
            continue
        call = _build_call(spec, value)
        if call is None:
            unsupported.append(spec.key)
            continue
        calls.append(call)

    return ApplyPlan(tuple(calls), tuple(unsupported), tuple(warnings))


def _build_call(spec: ValueSpec, value: Any) -> ProfileServiceCall | None:
    """Return the service call that writes ``value`` to the right entity.

    The four climate keys name their service explicitly - they are Home
    Assistant's and do not follow a pattern. Everything else follows from the
    domain of the entity behind it, which is the whole point of the design:
    adding a value means picking an entity, not teaching this function a new
    special case.
    """
    if spec.is_climate:
        if (service := _CLIMATE_SERVICES.get(spec.key)) is None:
            return None
        name, field_name = service
        return ProfileServiceCall(
            "climate", name, spec.entity, {field_name: value}, spec.key
        )

    if spec.kind == KIND_NUMBER:
        return ProfileServiceCall(
            spec.domain, "set_value", spec.entity, {"value": value}, spec.key
        )
    if spec.kind == KIND_BOOLEAN:
        return ProfileServiceCall(
            spec.domain,
            "turn_on" if value else "turn_off",
            spec.entity,
            {},
            spec.key,
        )
    if spec.kind == KIND_OPTION:
        return ProfileServiceCall(
            spec.domain, "select_option", spec.entity, {"option": value}, spec.key
        )
    return None


# ---------------------------------------------------------------------------
# capturing - writing the current state back into a profile
# ---------------------------------------------------------------------------


def storage_value(spec: ValueSpec | None, value: Any) -> Any:
    """Return a normalised value in the form profiles are stored in.

    Booleans become ``"on"``/``"off"`` so the options flow can show them in its
    dropdown, whole numbers lose their ``.0``, and options keep the entity's
    own spelling.
    """
    if spec is None or value is None:
        return None
    if spec.kind == KIND_BOOLEAN:
        return "on" if value else "off"
    if spec.kind == KIND_NUMBER:
        number = round(float(value), 2)
        return int(number) if float(number).is_integer() else number
    if spec.kind == KIND_OPTION:
        return canonical_option(str(value), spec.options) or value
    return value


def changed_keys(
    baseline: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    vocab: Vocabulary,
) -> tuple[str, ...]:
    """Return the keys whose value differs from ``baseline``.

    Without a baseline nothing counts as changed - after a restart there is no
    point of reference, and guessing would be worse than saying so.
    """
    if baseline is None:
        return ()
    before = normalise_values(vocab, baseline)
    now = normalise_values(vocab, current)
    return tuple(
        spec.key
        for spec in vocab
        if spec.key in now
        and not values_equal(spec, now[spec.key], before.get(spec.key))
    )


def capture_values(
    profile_values: Mapping[str, Any],
    current_values: Mapping[str, Any],
    vocab: Vocabulary,
    *,
    baseline: Mapping[str, Any] | None = None,
    keys: Sequence[str] | None = None,
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
    current = normalise_values(vocab, current_values)
    changed = changed_keys(baseline, current_values, vocab)
    wanted: list[str] = (
        list(keys)
        if keys is not None
        else [
            spec.key
            for spec in vocab
            if spec.key in profile_values or spec.key in changed
        ]
    )

    captured = dict(profile_values)
    for spec in vocab:
        if spec.key not in wanted:
            continue
        value = storage_value(spec, current.get(spec.key))
        if value is None:
            continue
        captured[spec.key] = value
    return captured


def usable_values(values: Mapping[str, Any], vocab: Vocabulary) -> dict[str, Any]:
    """Drop values whose key this entry does not know (any more)."""
    return {key: value for key, value in values.items() if key in vocab}
