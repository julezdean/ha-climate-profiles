"""Config and options flow.

Home Assistant's config flows render one form at a time and have no widget for
"a sortable list of nested objects", so profile management is modelled as a
menu: pick what you want to do, fill in one form, come back. Ordering is done
by re-picking the profiles in the wanted order (see ``async_step_reorder``),
which is the closest native equivalent to drag & drop.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    ColorRGBSelector,
    EntitySelector,
    EntitySelectorConfig,
    IconSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_CUSTOM_NAME,
    CONF_DISPLAY_ENTITY,
    CONF_FAN_ENTITY,
    CONF_PROFILE_COLOR,
    CONF_PROFILE_ICON,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_PROFILE_PROTECTED,
    CONF_PROFILES,
    CONF_SILENT_ENTITY,
    DEFAULT_CUSTOM_NAME,
    DEFAULT_PROFILE_COLOR,
    DOMAIN,
    VALUE_DISPLAY,
    VALUE_FAN,
    VALUE_FAN_MODE,
    VALUE_HVAC_MODE,
    VALUE_KEYS,
    VALUE_SILENT,
    VALUE_SWING_MODE,
    VALUE_TEMPERATURE,
)
from .matching import canonical_option
from .models import (
    Capabilities,
    ClimateProfile,
    EntityMap,
    ProfileError,
    ProfileSet,
    color_to_rgb,
    new_profile_id,
    normalise_color,
)

_LOGGER = logging.getLogger(__name__)

CONF_CREATE_DEFAULTS = "create_default_profiles"
CONF_ORDER = "order"
CONF_CONFIRM = "confirm"
CONF_SELECTED = "selected"

ON_OFF_OPTIONS = ["on", "off"]


# ---------------------------------------------------------------------------
# reading the devices
# ---------------------------------------------------------------------------


def read_capabilities(hass: HomeAssistant, entities: EntityMap) -> Capabilities:
    """Read the supported values straight from the configured entities."""
    attrs: dict[str, Any] = {}
    if (climate := hass.states.get(entities.climate)) is not None:
        attrs = dict(climate.attributes)

    fan_min = fan_max = None
    fan_step = 1.0
    if entities.fan and (number := hass.states.get(entities.fan)) is not None:
        fan_min = _float(number.attributes.get("min"))
        fan_max = _float(number.attributes.get("max"))
        fan_step = _float(number.attributes.get("step")) or 1.0

    return Capabilities(
        hvac_modes=tuple(str(m) for m in attrs.get("hvac_modes") or ()),
        fan_modes=tuple(str(m) for m in attrs.get("fan_modes") or ()),
        swing_modes=tuple(str(m) for m in attrs.get("swing_modes") or ()),
        min_temp=_float(attrs.get("min_temp")),
        max_temp=_float(attrs.get("max_temp")),
        temp_step=_float(attrs.get("target_temp_step")) or 0.5,
        fan_min=fan_min,
        fan_max=fan_max,
        fan_step=fan_step,
    )


def _float(raw: Any) -> float | None:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# schema building
# ---------------------------------------------------------------------------


def _device_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return the schema for the climate entity and its name."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_NAME, default=defaults.get(CONF_NAME, vol.UNDEFINED)
            ): TextSelector(),
            vol.Required(
                CONF_CLIMATE_ENTITY,
                default=defaults.get(CONF_CLIMATE_ENTITY, vol.UNDEFINED),
            ): EntitySelector(EntitySelectorConfig(domain="climate")),
        }
    )


def _optional_entities_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Return the schema for the optional helper entities.

    All three are optional: a device without a fan number entity simply never
    shows a fan slider, and profiles cannot define a ``fan`` value for it.
    """
    defaults = defaults or {}

    def suggest(key: str) -> dict[str, Any]:
        value = defaults.get(key)
        return {"suggested_value": value} if value else {}

    return vol.Schema(
        {
            vol.Optional(
                CONF_FAN_ENTITY, description=suggest(CONF_FAN_ENTITY)
            ): EntitySelector(EntitySelectorConfig(domain="number")),
            vol.Optional(
                CONF_DISPLAY_ENTITY, description=suggest(CONF_DISPLAY_ENTITY)
            ): EntitySelector(EntitySelectorConfig(domain="switch")),
            vol.Optional(
                CONF_SILENT_ENTITY, description=suggest(CONF_SILENT_ENTITY)
            ): EntitySelector(EntitySelectorConfig(domain="switch")),
        }
    )


def _string_selector(options: tuple[str, ...]) -> Any:
    """Return a dropdown of the device's own options, or free text if it has none."""
    if not options:
        return TextSelector()
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=option, label=option) for option in options
            ],
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=True,
            sort=False,
        )
    )


def _number_selector(
    low: float | None, high: float | None, step: float, unit: str | None = None
) -> NumberSelector:
    """Return a number box (not a slider) so the field stays clearable."""
    return NumberSelector(
        NumberSelectorConfig(
            min=low if low is not None else 0,
            max=high if high is not None else 100,
            step=step or 1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


def profile_schema(
    caps: Capabilities,
    entities: EntityMap,
    profile: ClimateProfile | None = None,
) -> vol.Schema:
    """Build the form for one profile.

    Every value field is optional and clearable: leaving it empty means "this
    profile does not care about that value", which is what makes partial
    profiles work. ``hvac_mode`` is the one required value, as a profile that
    does not say what the device should do is rarely what anyone wants.
    """
    values = dict(profile.values) if profile else {}

    def suggest(key: str) -> dict[str, Any]:
        return {"suggested_value": values[key]} if key in values else {}

    fields: dict[Any, Any] = {
        vol.Required(
            CONF_PROFILE_NAME,
            description={"suggested_value": profile.name if profile else None},
        ): TextSelector(),
        vol.Required(
            CONF_PROFILE_COLOR,
            default=color_to_rgb(profile.color if profile else DEFAULT_PROFILE_COLOR),
        ): ColorRGBSelector(),
        vol.Optional(
            CONF_PROFILE_ICON,
            description={"suggested_value": profile.icon if profile else None},
        ): IconSelector(),
        vol.Required(
            CONF_PROFILE_PROTECTED,
            default=bool(profile.protected) if profile else False,
        ): BooleanSelector(),
        vol.Required(
            VALUE_HVAC_MODE, description=suggest(VALUE_HVAC_MODE)
        ): _string_selector(caps.hvac_modes),
        vol.Optional(
            VALUE_TEMPERATURE, description=suggest(VALUE_TEMPERATURE)
        ): _number_selector(caps.min_temp, caps.max_temp, caps.temp_step, "°C"),
    }

    if caps.fan_modes or VALUE_FAN_MODE in values:
        fields[vol.Optional(VALUE_FAN_MODE, description=suggest(VALUE_FAN_MODE))] = (
            _string_selector(caps.fan_modes)
        )
    if caps.swing_modes or VALUE_SWING_MODE in values:
        fields[
            vol.Optional(VALUE_SWING_MODE, description=suggest(VALUE_SWING_MODE))
        ] = _string_selector(caps.swing_modes)
    if entities.fan:
        fields[vol.Optional(VALUE_FAN, description=suggest(VALUE_FAN))] = (
            _number_selector(caps.fan_min, caps.fan_max, caps.fan_step, "%")
        )
    for key, entity in (
        (VALUE_DISPLAY, entities.display),
        (VALUE_SILENT, entities.silent),
    ):
        if entity:
            fields[vol.Optional(key, description=suggest(key))] = SelectSelector(
                SelectSelectorConfig(
                    options=ON_OFF_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="on_off",
                )
            )

    return vol.Schema(fields)


def profile_from_input(
    user_input: dict[str, Any], profile_id: str | None = None
) -> ClimateProfile:
    """Turn a submitted profile form into a profile."""
    values = {
        key: user_input[key]
        for key in VALUE_KEYS
        if key in user_input and user_input[key] not in (None, "")
    }
    return ClimateProfile(
        id=profile_id or new_profile_id(),
        name=str(user_input[CONF_PROFILE_NAME]).strip(),
        color=normalise_color(user_input.get(CONF_PROFILE_COLOR)),
        values=values,
        icon=user_input.get(CONF_PROFILE_ICON) or None,
        protected=bool(user_input.get(CONF_PROFILE_PROTECTED, False)),
    )


# ---------------------------------------------------------------------------
# default profiles
# ---------------------------------------------------------------------------


def build_default_profiles(
    caps: Capabilities, entities: EntityMap
) -> list[ClimateProfile]:
    """Build a starter set from what the device actually supports.

    Anything the device does not advertise is left out instead of guessed, so
    the generated profiles can really be matched and applied.
    """
    blueprint: list[tuple[str, str, dict[str, Any]]] = [
        ("Aus", "#64748b", {VALUE_HVAC_MODE: "off"}),
        (
            "Away",
            "#3b82f6",
            {
                VALUE_HVAC_MODE: "cool",
                VALUE_TEMPERATURE: 26,
                VALUE_SWING_MODE: "off",
                VALUE_FAN_MODE: "auto",
                VALUE_DISPLAY: "off",
                VALUE_SILENT: "off",
            },
        ),
        (
            "Komfort",
            "#22c55e",
            {
                VALUE_HVAC_MODE: "cool",
                VALUE_TEMPERATURE: 24,
                VALUE_SWING_MODE: "off",
                VALUE_FAN_MODE: "auto",
                VALUE_DISPLAY: "off",
                VALUE_SILENT: "off",
            },
        ),
        (
            "Nacht",
            "#8b5cf6",
            {
                VALUE_HVAC_MODE: "cool",
                VALUE_TEMPERATURE: 26,
                VALUE_SWING_MODE: "off",
                VALUE_DISPLAY: "off",
                VALUE_SILENT: "on",
            },
        ),
        (
            "Max",
            "#ef4444",
            {
                VALUE_HVAC_MODE: "cool",
                VALUE_TEMPERATURE: 16,
                VALUE_SWING_MODE: "vertical",
                VALUE_FAN: 100,
                VALUE_DISPLAY: "off",
                VALUE_SILENT: "off",
            },
        ),
    ]

    profiles: list[ClimateProfile] = []
    for name, color, raw_values in blueprint:
        values: dict[str, Any] = {}
        for key, value in raw_values.items():
            if not entities.supports(key):
                continue
            if key in (VALUE_HVAC_MODE, VALUE_FAN_MODE, VALUE_SWING_MODE):
                option = canonical_option(str(value), caps.options_for(key))
                if option is None:
                    continue
                values[key] = option
            elif key == VALUE_TEMPERATURE:
                values[key] = _clamp(float(value), caps.min_temp, caps.max_temp)
            elif key == VALUE_FAN:
                values[key] = _clamp(float(value), caps.fan_min, caps.fan_max)
            else:
                values[key] = value

        if VALUE_HVAC_MODE not in values:
            continue
        profiles.append(
            ClimateProfile(id=new_profile_id(), name=name, color=color, values=values)
        )
    return profiles


def _clamp(value: float, low: float | None, high: float | None) -> float:
    if low is not None:
        value = max(value, low)
    if high is not None:
        value = min(value, high)
    return value


# ---------------------------------------------------------------------------
# config flow
# ---------------------------------------------------------------------------


class ClimateProfilesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up one air conditioner."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with an empty draft."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: name and climate entity."""
        errors: dict[str, str] = {}
        if user_input is not None:
            entity_id = user_input[CONF_CLIMATE_ENTITY]
            if self.hass.states.get(entity_id) is None:
                errors[CONF_CLIMATE_ENTITY] = "entity_not_found"
            else:
                await self.async_set_unique_id(entity_id)
                self._abort_if_unique_id_configured()
                self._data = dict(user_input)
                return await self.async_step_entities()

        return self.async_show_form(
            step_id="user", data_schema=_device_schema(user_input), errors=errors
        )

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: the optional fan / display / silent entities."""
        if user_input is not None:
            self._data.update(
                {key: value for key, value in user_input.items() if value}
            )
            return await self.async_step_profiles()

        return self.async_show_form(
            step_id="entities", data_schema=_optional_entities_schema()
        )

    async def async_step_profiles(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: optionally seed a starter set of profiles."""
        if user_input is not None:
            entities = EntityMap.from_config(self._data)
            profiles: list[ClimateProfile] = []
            if user_input.get(CONF_CREATE_DEFAULTS, True):
                caps = read_capabilities(self.hass, entities)
                profiles = build_default_profiles(caps, entities)

            name = self._data.pop(CONF_NAME)
            return self.async_create_entry(
                title=name,
                data=self._data,
                options={
                    CONF_PROFILES: [profile.as_dict() for profile in profiles],
                    CONF_CUSTOM_NAME: DEFAULT_CUSTOM_NAME,
                },
            )

        return self.async_show_form(
            step_id="profiles",
            data_schema=vol.Schema(
                {vol.Required(CONF_CREATE_DEFAULTS, default=True): bool}
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> ClimateProfilesOptionsFlow:
        """Return the options flow."""
        return ClimateProfilesOptionsFlow()


# ---------------------------------------------------------------------------
# options flow
# ---------------------------------------------------------------------------


class ClimateProfilesOptionsFlow(OptionsFlow):
    """Manage entities, profiles and their order after setup."""

    def __init__(self) -> None:
        """Start with the stored profiles."""
        self._editing: str | None = None

    # -- helpers ------------------------------------------------------------

    @property
    def _profiles(self) -> ProfileSet:
        try:
            return ProfileSet.from_list(self.config_entry.options.get(CONF_PROFILES))
        except ProfileError as err:  # pragma: no cover - defensive
            _LOGGER.error("Stored profiles are invalid: %s", err)
            return ProfileSet()

    @property
    def _entities(self) -> EntityMap:
        return EntityMap.from_config(self.config_entry.data)

    def _caps(self) -> Capabilities:
        return read_capabilities(self.hass, self._entities)

    def _profile_options(self) -> list[SelectOptionDict]:
        names = self._profiles.display_names()
        return [
            SelectOptionDict(value=profile.id, label=names[profile.id])
            for profile in self._profiles
        ]

    def _save(self, profiles: ProfileSet) -> ConfigFlowResult:
        """Persist the profiles in the config entry's options."""
        return self.async_create_entry(
            data={
                **self.config_entry.options,
                CONF_PROFILES: profiles.as_list(),
            }
        )

    # -- menu ---------------------------------------------------------------

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show what can be changed."""
        options = ["entities", "add_profile"]
        if self._profiles:
            options += ["edit_profile", "reorder", "delete_profile"]
        options.append("custom_name")
        return self.async_show_menu(step_id="init", menu_options=options)

    # -- entities -----------------------------------------------------------

    async def async_step_entities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the optional entities.

        These live in the entry's ``data`` (they are identity, not preference),
        so they are updated separately from the options.
        """
        if user_input is not None:
            # A cleared field is simply absent from user_input, so the optional
            # entities are rebuilt from scratch instead of merged - otherwise
            # clearing one would silently keep the old value.
            data: dict[str, Any] = {
                CONF_CLIMATE_ENTITY: self.config_entry.data[CONF_CLIMATE_ENTITY]
            }
            for key in (CONF_FAN_ENTITY, CONF_DISPLAY_ENTITY, CONF_SILENT_ENTITY):
                if value := user_input.get(key):
                    data[key] = value

            self.hass.config_entries.async_update_entry(self.config_entry, data=data)
            return self.async_create_entry(data=dict(self.config_entry.options))

        return self.async_show_form(
            step_id="entities",
            data_schema=_optional_entities_schema(dict(self.config_entry.data)),
        )

    # -- profiles -----------------------------------------------------------

    async def async_step_add_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a new profile."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                profile = profile_from_input(user_input)
            except (ProfileError, ValueError) as err:
                _LOGGER.debug("Invalid profile input: %s", err)
                errors["base"] = "invalid_profile"
            else:
                return self._save(ProfileSet((*self._profiles.profiles, profile)))

        return self.async_show_form(
            step_id="add_profile",
            data_schema=profile_schema(self._caps(), self._entities),
            errors=errors,
        )

    async def async_step_edit_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the profile to edit."""
        if user_input is not None:
            self._editing = user_input[CONF_PROFILE_ID]
            return await self.async_step_edit_values()

        return self.async_show_form(
            step_id="edit_profile",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROFILE_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=self._profile_options(),
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_edit_values(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit name, colour and values of the chosen profile."""
        profiles = self._profiles
        current = profiles.get(self._editing or "")
        if current is None:  # pragma: no cover - only after a concurrent edit
            return await self.async_step_init()

        if user_input is not None:
            updated = profile_from_input(user_input, profile_id=current.id)
            return self._save(
                ProfileSet(
                    tuple(
                        updated if profile.id == current.id else profile
                        for profile in profiles
                    )
                )
            )

        return self.async_show_form(
            step_id="edit_values",
            data_schema=profile_schema(self._caps(), self._entities, current),
            description_placeholders={"profile": current.name},
        )

    async def async_step_delete_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Delete one or more profiles."""
        if user_input is not None:
            doomed = set(user_input.get(CONF_SELECTED, []))
            return self._save(self._profiles.without(doomed))

        return self.async_show_form(
            step_id="delete_profile",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SELECTED, default=[]): SelectSelector(
                        SelectSelectorConfig(
                            options=self._profile_options(),
                            mode=SelectSelectorMode.LIST,
                            multiple=True,
                        )
                    )
                }
            ),
        )

    async def async_step_reorder(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the order in which profiles are matched and displayed.

        Config flows cannot render a drag & drop list, so the order is entered
        by picking the profiles one after another; anything left out keeps its
        relative position at the end.
        """
        profiles = self._profiles
        if user_input is not None:
            wanted = list(dict.fromkeys(user_input.get(CONF_ORDER, [])))
            ordered = [p for pid in wanted if (p := profiles.get(pid)) is not None]
            ordered += [p for p in profiles if p.id not in wanted]
            return self._save(ProfileSet(tuple(ordered)))

        return self.async_show_form(
            step_id="reorder",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ORDER, default=[p.id for p in profiles]
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=self._profile_options(),
                            mode=SelectSelectorMode.DROPDOWN,
                            multiple=True,
                            sort=False,
                        )
                    )
                }
            ),
        )

    async def async_step_custom_name(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Rename the virtual "custom" profile."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    CONF_CUSTOM_NAME: str(
                        user_input.get(CONF_CUSTOM_NAME) or DEFAULT_CUSTOM_NAME
                    ).strip(),
                }
            )

        return self.async_show_form(
            step_id="custom_name",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CUSTOM_NAME,
                        default=self.config_entry.options.get(
                            CONF_CUSTOM_NAME, DEFAULT_CUSTOM_NAME
                        ),
                    ): TextSelector()
                }
            ),
        )
