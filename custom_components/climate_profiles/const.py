"""Constants for the Climate Profiles integration.

This module deliberately does not import Home Assistant so that the pure
profile logic (``models``/``matching``) stays unit-testable without a running
Home Assistant instance.
"""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "climate_profiles"

# --- config entry data -----------------------------------------------------

CONF_CLIMATE_ENTITY: Final = "climate_entity"

#: The additional values a config entry drives, each backed by an entity of the
#: user's choosing. Lives in the entry's options, not its data: unlike the
#: climate entity it is preference rather than identity.
CONF_ADDITIONAL: Final = "additional_values"

CONF_ADDITIONAL_ID: Final = "id"
CONF_ADDITIONAL_NAME: Final = "name"
CONF_ADDITIONAL_ENTITY: Final = "entity"
CONF_ADDITIONAL_ICON: Final = "icon"
CONF_ADDITIONAL_ORDER: Final = "order"

#: The order in which values are applied - and in which the card shows the
#: additional ones. One list over one key space: the climate keys and the ids of
#: the additional values, mixed. ``hvac_mode`` is not in it: it always goes
#: first, because most devices ignore everything else while they are off.
CONF_VALUE_ORDER: Final = "value_order"

# --- config entry options --------------------------------------------------

CONF_PROFILES: Final = "profiles"
CONF_CUSTOM_NAME: Final = "custom_profile_name"

CONF_PROFILE_ID: Final = "id"
CONF_PROFILE_NAME: Final = "name"
CONF_PROFILE_COLOR: Final = "color"
CONF_PROFILE_ICON: Final = "icon"
CONF_PROFILE_VALUES: Final = "values"
CONF_PROFILE_PROTECTED: Final = "protected"

# --- profile value keys ----------------------------------------------------

VALUE_HVAC_MODE: Final = "hvac_mode"
VALUE_TEMPERATURE: Final = "temperature"
VALUE_SWING_MODE: Final = "swing_mode"
VALUE_FAN_MODE: Final = "fan_mode"

#: The keys that live on the climate entity itself, in the order in which they
#: are applied. ``hvac_mode`` goes first because most devices ignore everything
#: else while they are off - this mirrors the original YAML script. Additional
#: values are applied after these, in their configured order.
CLIMATE_KEYS: Final[tuple[str, ...]] = (
    VALUE_HVAC_MODE,
    VALUE_TEMPERATURE,
    VALUE_SWING_MODE,
    VALUE_FAN_MODE,
)

# --- what a value is -------------------------------------------------------

#: How a value is compared, stored and written. Derived from the domain of the
#: entity behind it, never hard coded per key.
KIND_NUMBER: Final = "number"
KIND_BOOLEAN: Final = "boolean"
KIND_OPTION: Final = "option"

#: The domains an additional value may point at: those whose state is a single
#: value. A ``light`` would have to answer what "equal" means - brightness?
#: colour? - and every rule in ``matching`` would have to carry that answer.
ADDITIONAL_DOMAINS: Final[dict[str, str]] = {
    "number": KIND_NUMBER,
    "input_number": KIND_NUMBER,
    "switch": KIND_BOOLEAN,
    "input_boolean": KIND_BOOLEAN,
    "select": KIND_OPTION,
    "input_select": KIND_OPTION,
}

#: The kind of each climate key. These four are given by Home Assistant.
CLIMATE_KINDS: Final[dict[str, str]] = {
    VALUE_HVAC_MODE: KIND_OPTION,
    VALUE_TEMPERATURE: KIND_NUMBER,
    VALUE_SWING_MODE: KIND_OPTION,
    VALUE_FAN_MODE: KIND_OPTION,
}

# --- the virtual "custom" profile -----------------------------------------

#: Stable, language independent id of the virtual profile. Automations should
#: match on the ``active_profile_id`` attribute, never on the localised state.
CUSTOM_PROFILE_ID: Final = "__custom__"
DEFAULT_CUSTOM_NAME: Final = "Custom"
DEFAULT_CUSTOM_COLOR: Final = "#78909c"
DEFAULT_PROFILE_COLOR: Final = "#03a9f4"

# --- attributes ------------------------------------------------------------

ATTR_ACTIVE_PROFILE: Final = "active_profile"

#: A profile that was applied but did not take: which one, and which of its
#: values the device did not keep.
ATTR_UNREACHED: Final = "unreached"

#: The definitions of the additional values, so the card can label and draw
#: what it otherwise only sees as ids.
ATTR_ADDITIONAL: Final = "additional_values"
ATTR_ACTIVE_PROFILE_ID: Final = "active_profile_id"
ATTR_ACTIVE_PROFILE_COLOR: Final = "active_profile_color"
ATTR_PROFILES: Final = "profiles"
ATTR_CURRENT_VALUES: Final = "current_values"
ATTR_CAPABILITIES: Final = "capabilities"
ATTR_ENTITIES: Final = "entities"
ATTR_APPLYING: Final = "applying"
ATTR_PROFILE: Final = "profile"
ATTR_VALUES: Final = "values"
ATTR_NAME: Final = "name"
ATTR_COLOR: Final = "color"
ATTR_ICON: Final = "icon"
ATTR_PROTECTED: Final = "protected"
ATTR_LAST_MATCHED_PROFILE_ID: Final = "last_matched_profile_id"
ATTR_CHANGED_VALUES: Final = "changed_values"

# --- services --------------------------------------------------------------

SERVICE_APPLY_PROFILE: Final = "apply_profile"
SERVICE_SET_VALUE: Final = "set_value"
SERVICE_CAPTURE_PROFILE: Final = "capture_profile"
SERVICE_SAVE_AS_PROFILE: Final = "save_as_profile"

# --- tuning ----------------------------------------------------------------

#: States of a climate device trickle in one attribute at a time. Debouncing
#: the recalculation keeps the sensor from flickering through half-applied
#: intermediate states.
RECALC_DEBOUNCE_SECONDS: Final = 0.4

#: Smallest difference that still counts as "a different value" for floats.
FLOAT_EPSILON: Final = 0.05

# --- did the profile take? -------------------------------------------------

#: After a profile is applied, the device is given this long without any state
#: change before the result is judged. PROVISIONAL: set from measurements on a
#: real device, see the debug log of the coordinator.
REACH_QUIET_SECONDS: Final = 3.0
#: ... but never longer than this after the last call, so a device that keeps
#: reporting does not postpone the verdict forever. PROVISIONAL as well.
REACH_MAX_SECONDS: Final = 30.0
