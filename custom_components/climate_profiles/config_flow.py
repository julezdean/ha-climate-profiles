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
    ADDITIONAL_DOMAINS,
    CONF_ADDITIONAL,
    CONF_ADDITIONAL_ENTITY,
    CONF_ADDITIONAL_ICON,
    CONF_ADDITIONAL_ID,
    CONF_ADDITIONAL_NAME,
    CONF_CLIMATE_ENTITY,
    CONF_CUSTOM_NAME,
    CONF_PROFILE_COLOR,
    CONF_PROFILE_ICON,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_PROFILE_PROTECTED,
    CONF_PROFILES,
    CONF_VALUE_ORDER,
    DEFAULT_CUSTOM_NAME,
    DEFAULT_PROFILE_COLOR,
    DOMAIN,
    KIND_BOOLEAN,
    KIND_NUMBER,
    KIND_OPTION,
    VALUE_FAN_MODE,
    VALUE_HVAC_MODE,
    VALUE_SWING_MODE,
    VALUE_TEMPERATURE,
)
from .matching import canonical_option
from .models import (
    AdditionalValue,
    AdditionalValueSet,
    Capabilities,
    ClimateProfile,
    EntityMap,
    ProfileError,
    ProfileSet,
    Vocabulary,
    color_to_rgb,
    new_profile_id,
    new_value_id,
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


#: How the climate keys are called in the reorder list, which mixes them with
#: the user's own names for the additional values.
_CLIMATE_LABELS: dict[str, dict[str, str]] = {
    "en": {
        VALUE_TEMPERATURE: "Temperature",
        VALUE_SWING_MODE: "Swing",
        VALUE_FAN_MODE: "Fan mode",
    },
    "de": {
        VALUE_TEMPERATURE: "Temperatur",
        VALUE_SWING_MODE: "Swing",
        VALUE_FAN_MODE: "Lüftermodus",
    },
}


def _float(raw: Any) -> float | None:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def read_capabilities(hass: HomeAssistant, entities: EntityMap) -> Capabilities:
    """Read the supported values straight from the climate entity."""
    attrs: dict[str, Any] = {}
    if (climate := hass.states.get(entities.climate)) is not None:
        attrs = dict(climate.attributes)

    return Capabilities(
        hvac_modes=tuple(str(m) for m in attrs.get("hvac_modes") or ()),
        fan_modes=tuple(str(m) for m in attrs.get("fan_modes") or ()),
        swing_modes=tuple(str(m) for m in attrs.get("swing_modes") or ()),
        min_temp=_float(attrs.get("min_temp")),
        max_temp=_float(attrs.get("max_temp")),
        temp_step=_float(attrs.get("target_temp_step")) or 0.5,
    )


def read_vocabulary(
    hass: HomeAssistant,
    entities: EntityMap,
    order: list[str] | None = None,
) -> Vocabulary:
    """Read what an entry knows about, straight from its entities.

    The limits of an additional value belong to its entity, not to us: a
    number carries ``min``/``max``/``step``, a select carries ``options``.
    """
    specs: dict[str, dict[str, Any]] = {}
    for value in entities.additional:
        if (state := hass.states.get(value.entity)) is None:
            continue
        attrs = state.attributes
        specs[value.id] = {
            "min": _float(attrs.get("min")),
            "max": _float(attrs.get("max")),
            "step": _float(attrs.get("step")) or 1.0,
            "options": tuple(str(o) for o in attrs.get("options") or ()),
        }
    return Vocabulary.build(
        entities,
        read_capabilities(hass, entities),
        additional_specs=specs,
        order=order,
    )


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


def _additional_value_schema(
    value: AdditionalValue | None = None,
) -> vol.Schema:
    """Return the form for one additional value.

    Only domains whose state is a single value are offered. A ``light`` would
    force an answer to what "equal" means - brightness? colour? - and every
    matching rule would have to carry it.
    """
    return vol.Schema(
        {
            vol.Required(
                CONF_ADDITIONAL_ENTITY,
                description={"suggested_value": value.entity if value else None},
            ): EntitySelector(EntitySelectorConfig(domain=sorted(ADDITIONAL_DOMAINS))),
            vol.Optional(
                CONF_ADDITIONAL_NAME,
                description={"suggested_value": value.name if value else None},
            ): TextSelector(),
            vol.Optional(
                CONF_ADDITIONAL_ICON,
                description={"suggested_value": value.icon if value else None},
            ): IconSelector(),
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
    vocab: Vocabulary,
    profile: ClimateProfile | None = None,
) -> vol.Schema:
    """Build the form for one profile.

    Every value field is optional and clearable: leaving it empty means "this
    profile does not care about that value", which is what makes partial
    profiles work. ``hvac_mode`` is the one required value, as a profile that
    does not say what the device should do is rarely what anyone wants.

    The fields come from the vocabulary, so an additional value the user added
    shows up here without this function knowing anything about it.
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
    }

    for spec in vocab:
        key = spec.key
        if key == VALUE_HVAC_MODE:
            fields[vol.Required(key, description=suggest(key))] = _string_selector(
                spec.options
            )
            continue
        # A value the device does not advertise is only offered when a profile
        # already carries it - otherwise the form fills up with fields that
        # cannot be applied.
        if (
            spec.is_climate
            and spec.kind == KIND_OPTION
            and not spec.options
            and key not in values
        ):
            continue
        if spec.kind == KIND_OPTION:
            if spec.is_climate:
                fields[vol.Optional(key, description=suggest(key))] = _string_selector(
                    spec.options
                )
            else:
                fields[vol.Optional(key, description=suggest(key))] = SelectSelector(
                    SelectSelectorConfig(
                        options=list(spec.options),
                        mode=SelectSelectorMode.DROPDOWN,
                        custom_value=not spec.options,
                    )
                )
        elif spec.kind == KIND_NUMBER:
            fields[vol.Optional(key, description=suggest(key))] = _number_selector(
                spec.minimum,
                spec.maximum,
                spec.step,
                "°C" if key == VALUE_TEMPERATURE else "",
            )
        elif spec.kind == KIND_BOOLEAN:
            fields[vol.Optional(key, description=suggest(key))] = SelectSelector(
                SelectSelectorConfig(
                    options=ON_OFF_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                    translation_key="on_off",
                )
            )

    return vol.Schema(fields)


def profile_from_input(
    user_input: dict[str, Any],
    vocab: Vocabulary,
    profile_id: str | None = None,
) -> ClimateProfile:
    """Turn a submitted profile form into a profile."""
    values = {
        spec.key: user_input[spec.key]
        for spec in vocab
        if spec.key in user_input and user_input[spec.key] not in (None, "")
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


def build_default_profiles(caps: Capabilities) -> list[ClimateProfile]:
    """Build a starter set from what the device actually supports.

    Anything the device does not advertise is left out instead of guessed, so
    the generated profiles can really be matched and applied.
    """
    blueprint: list[tuple[str, str, dict[str, Any]]] = [
        ("Off", "#64748b", {VALUE_HVAC_MODE: "off"}),
        (
            "Away",
            "#3b82f6",
            {
                VALUE_HVAC_MODE: "cool",
                VALUE_TEMPERATURE: 26,
                VALUE_SWING_MODE: "off",
                VALUE_FAN_MODE: "auto",
            },
        ),
        (
            "Comfort",
            "#22c55e",
            {
                VALUE_HVAC_MODE: "cool",
                VALUE_TEMPERATURE: 24,
                VALUE_SWING_MODE: "off",
                VALUE_FAN_MODE: "auto",
            },
        ),
        (
            "Night",
            "#8b5cf6",
            {
                VALUE_HVAC_MODE: "cool",
                VALUE_TEMPERATURE: 26,
                VALUE_SWING_MODE: "off",
            },
        ),
        (
            "Max",
            "#ef4444",
            {
                VALUE_HVAC_MODE: "cool",
                VALUE_TEMPERATURE: 16,
                VALUE_SWING_MODE: "vertical",
            },
        ),
    ]

    profiles: list[ClimateProfile] = []
    for name, color, raw_values in blueprint:
        values: dict[str, Any] = {}
        for key, value in raw_values.items():
            if key in (VALUE_HVAC_MODE, VALUE_FAN_MODE, VALUE_SWING_MODE):
                option = canonical_option(str(value), caps.options_for(key))
                if option is None:
                    continue
                values[key] = option
            elif key == VALUE_TEMPERATURE:
                values[key] = _clamp(float(value), caps.min_temp, caps.max_temp)
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
                return await self.async_step_profiles()

        return self.async_show_form(
            step_id="user", data_schema=_device_schema(user_input), errors=errors
        )

    async def async_step_profiles(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: optionally seed a starter set of profiles.

        Only climate values are seeded - additional values are added after
        setup, so at this point there are none to put into a profile.
        """
        if user_input is not None:
            entities = EntityMap.from_config(self._data)
            profiles: list[ClimateProfile] = []
            if user_input.get(CONF_CREATE_DEFAULTS, True):
                caps = read_capabilities(self.hass, entities)
                profiles = build_default_profiles(caps)

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
    def _additional(self) -> AdditionalValueSet:
        try:
            return AdditionalValueSet.from_list(
                self.config_entry.options.get(CONF_ADDITIONAL)
            )
        except ProfileError as err:  # pragma: no cover - defensive
            _LOGGER.error("Stored additional values are invalid: %s", err)
            return AdditionalValueSet()

    @property
    def _entities(self) -> EntityMap:
        return EntityMap.from_config(self.config_entry.data, self._additional)

    def _vocab(self) -> Vocabulary:
        return read_vocabulary(
            self.hass,
            self._entities,
            list(self.config_entry.options.get(CONF_VALUE_ORDER) or []),
        )

    def _order_options(self) -> list[SelectOptionDict]:
        """Every value that can be moved, labelled - ``hvac_mode`` excluded.

        Climate keys are labelled here rather than through the translation
        files: the list mixes them with the user's own names, and a selector
        translates either all of its options or none.
        """
        labels = _CLIMATE_LABELS.get(
            (self.hass.config.language or "en").split("-")[0], _CLIMATE_LABELS["en"]
        )
        names = {value.id: value.name for value in self._additional}
        return [
            SelectOptionDict(
                value=spec.key, label=labels.get(spec.key) or names[spec.key]
            )
            for spec in self._vocab()
            if spec.key != VALUE_HVAC_MODE and (spec.key in labels or spec.key in names)
        ]

    def _value_options(self) -> list[SelectOptionDict]:
        return [
            SelectOptionDict(value=value.id, label=value.name)
            for value in self._additional
        ]

    def _save_additional(self, values: AdditionalValueSet) -> ConfigFlowResult:
        """Persist the additional values in the config entry's options."""
        return self.async_create_entry(
            data={
                **self.config_entry.options,
                CONF_ADDITIONAL: values.as_list(),
            }
        )

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
        options = ["add_value"]
        if self._additional:
            options += ["edit_value", "reorder_values", "delete_value"]
        options.append("add_profile")
        if self._profiles:
            options += ["edit_profile", "reorder", "delete_profile"]
        options.append("custom_name")
        return self.async_show_menu(step_id="init", menu_options=options)

    # -- additional values ---------------------------------------------------

    async def async_step_add_value(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add one additional value.

        The name is pre-filled from the entity and kept unique here: it arrives
        on its own, so two switches both called "Silent" would otherwise only
        show up as an ambiguity in an automation, at runtime.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            entity_id = str(user_input[CONF_ADDITIONAL_ENTITY])
            state = self.hass.states.get(entity_id)
            if state is None:
                errors[CONF_ADDITIONAL_ENTITY] = "entity_not_found"
            elif entity_id.partition(".")[0] not in ADDITIONAL_DOMAINS:
                errors[CONF_ADDITIONAL_ENTITY] = "unsupported_domain"
            else:
                values = self._additional
                name = str(
                    user_input.get(CONF_ADDITIONAL_NAME)
                    or state.attributes.get("friendly_name")
                    or entity_id
                ).strip()
                value = AdditionalValue(
                    id=new_value_id(),
                    name=values.unique_name(name),
                    entity=entity_id,
                    icon=user_input.get(CONF_ADDITIONAL_ICON) or None,
                    order=values.next_order(),
                )
                return self._save_additional(values.appended(value))

        return self.async_show_form(
            step_id="add_value",
            data_schema=_additional_value_schema(),
            errors=errors,
        )

    async def async_step_edit_value(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick an additional value to edit."""
        if user_input is not None:
            self._editing = user_input[CONF_ADDITIONAL_ID]
            return await self.async_step_edit_value_form()

        return self.async_show_form(
            step_id="edit_value",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDITIONAL_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=self._value_options(),
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_edit_value_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change an additional value's entity, name or icon."""
        values = self._additional
        current = values.get(self._editing or "")
        if current is None:  # pragma: no cover - defensive
            return await self.async_step_init()

        errors: dict[str, str] = {}
        if user_input is not None:
            entity_id = str(user_input[CONF_ADDITIONAL_ENTITY])
            if self.hass.states.get(entity_id) is None:
                errors[CONF_ADDITIONAL_ENTITY] = "entity_not_found"
            elif entity_id.partition(".")[0] not in ADDITIONAL_DOMAINS:
                errors[CONF_ADDITIONAL_ENTITY] = "unsupported_domain"
            else:
                name = str(user_input.get(CONF_ADDITIONAL_NAME) or current.name).strip()
                updated = AdditionalValue(
                    id=current.id,
                    name=values.unique_name(name, ignoring=current.id),
                    entity=entity_id,
                    icon=user_input.get(CONF_ADDITIONAL_ICON) or None,
                    order=current.order,
                )
                return self._save_additional(values.replaced(updated))

        return self.async_show_form(
            step_id="edit_value_form",
            data_schema=_additional_value_schema(current),
            errors=errors,
            description_placeholders={"value": current.name},
        )

    async def async_step_reorder_values(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the order in which values are applied.

        Values can contradict each other on a device - a silent mode that sets
        its own fan speed wins or loses depending on whether it is written
        before or after the fan mode. The order decides which. It is also the
        order the card shows the additional values in.

        ``hvac_mode`` is not offered: it always goes first, because most
        devices ignore everything else while they are off. Picked one after
        another, like the profile order; anything left out keeps its relative
        place at the end.
        """
        current = [option["value"] for option in self._order_options()]
        if user_input is not None:
            wanted = [
                key
                for key in dict.fromkeys(user_input.get(CONF_ORDER, []))
                if key in current
            ]
            order = wanted + [key for key in current if key not in wanted]
            return self.async_create_entry(
                data={**self.config_entry.options, CONF_VALUE_ORDER: order}
            )

        return self.async_show_form(
            step_id="reorder_values",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ORDER, default=current): SelectSelector(
                        SelectSelectorConfig(
                            options=self._order_options(),
                            mode=SelectSelectorMode.DROPDOWN,
                            multiple=True,
                            sort=False,
                        )
                    )
                }
            ),
        )

    async def async_step_delete_value(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove additional values.

        The values stored in profiles are left alone: they are harmless and
        skipped from then on. They do not come back to life when the entity is
        added again - that creates a new value with a new id. Swapping the
        entity behind a value is what editing it is for.
        """
        if user_input is not None:
            chosen = set(user_input.get(CONF_ADDITIONAL_ID) or ())
            return self._save_additional(self._additional.without(chosen))

        return self.async_show_form(
            step_id="delete_value",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDITIONAL_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=self._value_options(),
                            mode=SelectSelectorMode.LIST,
                            multiple=True,
                        )
                    )
                }
            ),
        )

    # -- profiles -----------------------------------------------------------

    async def async_step_add_profile(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a new profile."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                profile = profile_from_input(user_input, self._vocab())
            except (ProfileError, ValueError) as err:
                _LOGGER.debug("Invalid profile input: %s", err)
                errors["base"] = "invalid_profile"
            else:
                return self._save(ProfileSet((*self._profiles.profiles, profile)))

        return self.async_show_form(
            step_id="add_profile",
            data_schema=profile_schema(self._vocab()),
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
            updated = profile_from_input(
                user_input, self._vocab(), profile_id=current.id
            )
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
            data_schema=profile_schema(self._vocab(), current),
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
