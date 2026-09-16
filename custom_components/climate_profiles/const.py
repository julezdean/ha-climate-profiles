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
CONF_FAN_ENTITY: Final = "fan_entity"
CONF_DISPLAY_ENTITY: Final = "display_entity"
CONF_SILENT_ENTITY: Final = "silent_entity"

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
VALUE_FAN: Final = "fan"
VALUE_DISPLAY: Final = "display"
VALUE_SILENT: Final = "silent"

#: Every supported key, in the order in which the values are applied.
#: ``hvac_mode`` goes first because most devices ignore everything else while
#: they are off - this mirrors the behaviour of the original YAML script.
VALUE_KEYS: Final[tuple[str, ...]] = (
    VALUE_HVAC_MODE,
    VALUE_TEMPERATURE,
    VALUE_SWING_MODE,
    VALUE_FAN_MODE,
    VALUE_FAN,
    VALUE_DISPLAY,
    VALUE_SILENT,
)

#: Keys that are only usable when the matching optional entity is configured.
KEY_REQUIRES_ENTITY: Final[dict[str, str]] = {
    VALUE_FAN: CONF_FAN_ENTITY,
    VALUE_DISPLAY: CONF_DISPLAY_ENTITY,
    VALUE_SILENT: CONF_SILENT_ENTITY,
}

BOOLEAN_KEYS: Final[frozenset[str]] = frozenset({VALUE_DISPLAY, VALUE_SILENT})
NUMERIC_KEYS: Final[frozenset[str]] = frozenset({VALUE_TEMPERATURE, VALUE_FAN})
STRING_KEYS: Final[frozenset[str]] = frozenset(
    {VALUE_HVAC_MODE, VALUE_SWING_MODE, VALUE_FAN_MODE}
)

# --- the virtual "custom" profile -----------------------------------------

#: Stable, language independent id of the virtual profile. Automations should
#: match on the ``active_profile_id`` attribute, never on the localised state.
CUSTOM_PROFILE_ID: Final = "__custom__"
DEFAULT_CUSTOM_NAME: Final = "Custom"
DEFAULT_CUSTOM_COLOR: Final = "#78909c"
DEFAULT_PROFILE_COLOR: Final = "#03a9f4"

# --- attributes ------------------------------------------------------------

ATTR_ACTIVE_PROFILE: Final = "active_profile"
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
