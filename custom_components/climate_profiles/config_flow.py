"""Config and options flow.

Setup is one form. Afterwards there are two lists: the additional values and
the profiles. Each is an object selector with ``multiple``, which Home
Assistant renders as a sortable list - one row per entry, with a drag handle,
a pencil and a bin - so adding, editing, ordering and deleting happen in one
place instead of in four menu entries each. What a row carries is defined in
:meth:`ClimateProfilesOptionsFlow._profile_fields` and ``_value_fields``; the
id travels with the row, read only, because everything a profile stored hangs
off it.
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
from homeassistant.const import CONF_NAME, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    ColorRGBSelector,
    EntitySelector,
    EntitySelectorConfig,
    IconSelector,
    ObjectSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    ADDITIONAL_DOMAINS,
    CAPTURE_ASK,
    CAPTURE_MODES,
    CONF_ADDITIONAL,
    CONF_ADDITIONAL_ENTITY,
    CONF_ADDITIONAL_ICON,
    CONF_ADDITIONAL_ID,
    CONF_ADDITIONAL_NAME,
    CONF_CLIMATE_ENTITY,
    CONF_CUSTOM_COLOR,
    CONF_CUSTOM_ICON,
    CONF_CUSTOM_NAME,
    CONF_PROFILE_CAPTURE,
    CONF_PROFILE_COLOR,
    CONF_PROFILE_DETECT,
    CONF_PROFILE_ICON,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_PROFILES,
    CONF_VALUE_ORDER,
    DEFAULT_CUSTOM_COLOR,
    DEFAULT_CUSTOM_NAME,
    DOMAIN,
    KIND_NUMBER,
    KIND_OPTION,
    VALUE_FAN_MODE,
    VALUE_HVAC_MODE,
    VALUE_SWING_MODE,
    VALUE_TEMPERATURE,
)
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

CONF_ORDER = "order"
CONF_SELECTED = "selected"

ON_OFF_OPTIONS = ["on", "off"]


# ---------------------------------------------------------------------------
# reading the devices
# ---------------------------------------------------------------------------


#: What the fields of a row are called, and the climate keys with them. These
#: are labels inside a selector, not form fields, so they cannot come from the
#: translation files: a row mixes them with the user's own value names, which
#: are literals by nature.
_ROW_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "name": "Name",
        "entity": "Entity",
        "icon": "Icon",
        "color": "Colour",
        "detect": "Recognise this profile automatically",
        "capture": "Changes by hand",
        VALUE_HVAC_MODE: "Mode",
        VALUE_TEMPERATURE: "Temperature",
        VALUE_SWING_MODE: "Swing",
        VALUE_FAN_MODE: "Fan mode",
    },
    "de": {
        "name": "Name",
        "entity": "Entität",
        "icon": "Symbol",
        "color": "Farbe",
        "detect": "Dieses Profil automatisch erkennen",
        "capture": "Änderungen von Hand",
        VALUE_HVAC_MODE: "Modus",
        VALUE_TEMPERATURE: "Temperatur",
        VALUE_SWING_MODE: "Swing",
        VALUE_FAN_MODE: "Lüftermodus",
    },
}


class RowSelector(ObjectSelector):
    """A sortable list of rows that carry an id the user never sees.

    The stock validator refuses every key that is not a field, and the id is
    deliberately not one: a field marked ``read_only`` is accepted by the
    backend and ignored by the frontend's text selector, which drew the id as
    an ordinary editable box. Left out of the fields it is invisible, and it
    still survives every edit - the frontend hands the whole row to the edit
    dialog, merges the fields back into it, and moves rows as whole objects.
    So the id is taken off the rows before they are validated and put back
    afterwards. Only a row added with the + button arrives without one.
    """

    def __init__(self, config: dict[str, Any], id_key: str) -> None:
        """Remember which key of a row is the id."""
        super().__init__(config)
        self._id_key = id_key

    def __call__(self, data: Any) -> Any:
        """Validate the rows, ignoring the id each one carries."""
        if not isinstance(data, list):
            return super().__call__(data)

        super().__call__(
            [
                {key: value for key, value in row.items() if key != self._id_key}
                if isinstance(row, dict)
                else row
                for row in data
            ]
        )
        return data


def _value_row(value: AdditionalValue) -> dict[str, Any]:
    """Return one additional value as a row of the list.

    The id is in the row but in no field, so there is nothing to edit and
    nothing to mistype. It survives all the same: the frontend hands the whole
    row to the edit dialog and merges the fields back into it, moves rows as
    whole objects, and only a row added with the button arrives without one.
    (A field marked ``read_only`` would not do - the backend takes the option
    and the frontend's text selector ignores it, so the id showed up as an
    ordinary editable box.)

    A field that is not set is left out rather than sent as ``None``: the
    selectors validate what they are given, and ``None`` is not a string.
    """
    row = {
        CONF_ADDITIONAL_NAME: value.name,
        CONF_ADDITIONAL_ENTITY: value.entity,
        CONF_ADDITIONAL_ICON: value.icon,
        CONF_ADDITIONAL_ID: value.id,
    }
    return {key: item for key, item in row.items() if item is not None}


def _profile_row(profile: ClimateProfile, vocab: Vocabulary) -> dict[str, Any]:
    """Return one profile as a row of the list.

    Only the values the entry still knows about are put back into the row: a
    deleted additional value leaves its stored value alone, but there is no
    field to show it in any more.
    """
    row: dict[str, Any] = {
        key: value
        for key, value in (
            (CONF_PROFILE_NAME, profile.name),
            (CONF_PROFILE_COLOR, color_to_rgb(profile.color)),
            (CONF_PROFILE_ICON, profile.icon),
            (CONF_PROFILE_DETECT, profile.detect),
            (CONF_PROFILE_CAPTURE, profile.capture),
            (CONF_PROFILE_ID, profile.id),
        )
        if value is not None
    }
    for spec in vocab:
        if spec.key in profile.values:
            row[spec.key] = profile.values[spec.key]
    return row


def _log_catch_alls(profiles: ProfileSet) -> None:
    """Say which profiles are catch-alls for others.

    A profile whose values are contained in another one matches whenever that
    other one does. The more specific one wins the display, so the broader is
    only ever shown when nothing narrower fits. That is deliberate - a profile
    saying "heating" should lose against one that also names the temperature -
    but it is worth knowing when you wonder why a profile rarely shows up.
    """
    for broad in profiles:
        covered = [
            narrow.name
            for narrow in profiles
            if narrow.id != broad.id
            and len(narrow.values) > len(broad.values)
            and all(
                key in narrow.values and narrow.values[key] == value
                for key, value in broad.values.items()
            )
        ]
        if covered:
            _LOGGER.warning(
                "Profile %s is a catch-all for %s: it matches whenever they do, "
                "so it is only shown when none of them fits",
                broad.name,
                ", ".join(covered),
            )


def device_candidates(
    hass: HomeAssistant, entities: EntityMap
) -> list[SelectOptionDict]:
    """Return the siblings of the climate entity that could carry a value.

    Everything that sits on the same Home Assistant device, in the domains
    whose state is a single value, minus what is already configured. Diagnostic
    entities are left out - a battery level or a link quality is not something
    a profile sets - while configuration entities stay: a calibration offset is
    a plausible thing to put into one.

    Nothing is added automatically from this. A device that gains three
    entities with a firmware update must not quietly gain three profile values.
    """
    registry = er.async_get(hass)
    climate = registry.async_get(entities.climate)
    if climate is None or climate.device_id is None:
        return []

    taken = set(entities.additional.entity_ids())
    options: list[SelectOptionDict] = []
    for entry in er.async_entries_for_device(registry, climate.device_id):
        if entry.entity_id in taken or entry.disabled or entry.hidden:
            continue
        if entry.domain not in ADDITIONAL_DOMAINS:
            continue
        if entry.entity_category == EntityCategory.DIAGNOSTIC:
            continue
        state = hass.states.get(entry.entity_id)
        label = (
            (state.attributes.get("friendly_name") if state else None)
            or entry.name
            or entry.original_name
            or entry.entity_id
        )
        options.append(SelectOptionDict(value=entry.entity_id, label=str(label)))
    return sorted(options, key=lambda option: option["label"])


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
        detect=bool(user_input.get(CONF_PROFILE_DETECT, True)),
        capture=str(user_input.get(CONF_PROFILE_CAPTURE) or CAPTURE_ASK),
    )


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
                name = self._data.pop(CONF_NAME)
                # No starter profiles: the blueprint was shaped like an air
                # conditioner, and on a radiator thermostat it produced
                # profiles that had to be fixed before they were any use.
                # Adding one under Configure is a form away.
                return self.async_create_entry(
                    title=name,
                    data=self._data,
                    options={
                        CONF_PROFILES: [],
                        CONF_CUSTOM_NAME: DEFAULT_CUSTOM_NAME,
                    },
                )

        return self.async_show_form(
            step_id="user", data_schema=_device_schema(user_input), errors=errors
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
    """Manage the additional values and the profiles after setup."""

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
        labels = self._labels()
        names = {value.id: value.name for value in self._additional}
        return [
            SelectOptionDict(
                value=spec.key, label=labels.get(spec.key) or names[spec.key]
            )
            for spec in self._vocab()
            if spec.key != VALUE_HVAC_MODE and (spec.key in labels or spec.key in names)
        ]

    # -- the two lists ------------------------------------------------------

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the two things an entry is made of."""
        return self.async_show_menu(step_id="init", menu_options=["values", "profiles"])

    async def async_step_values(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One list of the additional values, plus the order they are written in.

        A row is a value; where it sits in the list is where it sits on the
        card. The id travels with the row, read only, so renaming a value or
        pointing it at a different entity leaves every profile that sets it
        intact - a value added anew would get a new id and lose them.
        """
        candidates = device_candidates(self.hass, self._entities)
        rows = [_value_row(value) for value in self._additional]
        errors: dict[str, str] = {}

        if user_input is not None:
            rows = list(user_input.get(CONF_ADDITIONAL) or [])
            values, errors = self._values_from_rows(rows)
            if values is not None:
                for entity_id in user_input.get(CONF_SELECTED) or []:
                    values = self._appended_from_entity(values, str(entity_id))
                return self.async_create_entry(
                    data={
                        **self.config_entry.options,
                        CONF_ADDITIONAL: values.as_list(),
                        CONF_VALUE_ORDER: self._order_from_input(user_input),
                    }
                )

        fields: dict[Any, Any] = {
            vol.Optional(
                CONF_ADDITIONAL, description={"suggested_value": rows}
            ): RowSelector(
                {
                    "multiple": True,
                    "label_field": CONF_ADDITIONAL_NAME,
                    "description_field": CONF_ADDITIONAL_ENTITY,
                    "fields": self._value_fields(),
                },
                CONF_ADDITIONAL_ID,
            )
        }
        if candidates:
            fields[vol.Optional(CONF_SELECTED, default=[])] = SelectSelector(
                SelectSelectorConfig(
                    options=candidates,
                    mode=SelectSelectorMode.LIST,
                    multiple=True,
                )
            )
        if order := self._order_options():
            fields[
                vol.Optional(CONF_ORDER, default=[option["value"] for option in order])
            ] = SelectSelector(
                SelectSelectorConfig(
                    options=order,
                    mode=SelectSelectorMode.DROPDOWN,
                    multiple=True,
                    sort=False,
                )
            )

        return self.async_show_form(
            step_id="values", data_schema=vol.Schema(fields), errors=errors
        )

    async def async_step_profiles(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """One list of the profiles, and the "custom" entry below it.

        Everything a profile is lives in its row: name, colour, icon, how it
        becomes active, what a change by hand does, and the values it sets.
        The order of the rows is the order they are matched and shown in.
        """
        vocab = self._vocab()
        options = self.config_entry.options
        rows = [_profile_row(profile, vocab) for profile in self._profiles]
        errors: dict[str, str] = {}

        if user_input is not None:
            rows = list(user_input.get(CONF_PROFILES) or [])
            profiles, errors = self._profiles_from_rows(rows, vocab)
            if profiles is not None:
                _log_catch_alls(profiles)
                return self.async_create_entry(
                    data={
                        **options,
                        CONF_PROFILES: profiles.as_list(),
                        CONF_CUSTOM_NAME: str(
                            user_input.get(CONF_CUSTOM_NAME) or DEFAULT_CUSTOM_NAME
                        ).strip(),
                        CONF_CUSTOM_COLOR: normalise_color(
                            user_input.get(CONF_CUSTOM_COLOR), DEFAULT_CUSTOM_COLOR
                        ),
                        CONF_CUSTOM_ICON: user_input.get(CONF_CUSTOM_ICON) or None,
                    }
                )

        return self.async_show_form(
            step_id="profiles",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_PROFILES, description={"suggested_value": rows}
                    ): RowSelector(
                        {
                            "multiple": True,
                            "label_field": CONF_PROFILE_NAME,
                            "fields": self._profile_fields(vocab),
                        },
                        CONF_PROFILE_ID,
                    ),
                    vol.Required(
                        CONF_CUSTOM_NAME,
                        default=options.get(CONF_CUSTOM_NAME, DEFAULT_CUSTOM_NAME),
                    ): TextSelector(),
                    vol.Required(
                        CONF_CUSTOM_COLOR,
                        default=color_to_rgb(
                            normalise_color(
                                options.get(CONF_CUSTOM_COLOR), DEFAULT_CUSTOM_COLOR
                            )
                        ),
                    ): ColorRGBSelector(),
                    vol.Optional(
                        CONF_CUSTOM_ICON,
                        description={"suggested_value": options.get(CONF_CUSTOM_ICON)},
                    ): IconSelector(),
                }
            ),
            errors=errors,
        )

    # -- turning rows back into what is stored -------------------------------

    def _labels(self) -> dict[str, str]:
        """Return the row field labels in Home Assistant's language.

        A selector's fields are labelled here rather than in the translation
        files: the rows mix fixed fields with the user's own value names, and
        those can only be literals.
        """
        language = (self.hass.config.language or "en").split("-")[0]
        return _ROW_LABELS.get(language, _ROW_LABELS["en"])

    def _value_fields(self) -> dict[str, Any]:
        """Return the fields of one additional value's row."""
        labels = self._labels()
        return {
            # Optional: left empty, the name is taken from the entity, which
            # is what the old one-value-at-a-time form did as well.
            CONF_ADDITIONAL_NAME: {
                "required": False,
                "label": labels["name"],
                "selector": {"text": {}},
            },
            CONF_ADDITIONAL_ENTITY: {
                "required": True,
                "label": labels["entity"],
                "selector": {"entity": {"domain": sorted(ADDITIONAL_DOMAINS)}},
            },
            CONF_ADDITIONAL_ICON: {
                "required": False,
                "label": labels["icon"],
                "selector": {"icon": {}},
            },
        }

    def _profile_fields(self, vocab: Vocabulary) -> dict[str, Any]:
        """Return the fields of one profile's row, values included."""
        labels = self._labels()
        names = {value.id: value.name for value in self._additional}
        fields: dict[str, Any] = {
            CONF_PROFILE_NAME: {
                "required": True,
                "label": labels["name"],
                "selector": {"text": {}},
            },
            CONF_PROFILE_COLOR: {
                "required": False,
                "label": labels["color"],
                "selector": {"color_rgb": {}},
            },
            CONF_PROFILE_ICON: {
                "required": False,
                "label": labels["icon"],
                "selector": {"icon": {}},
            },
            CONF_PROFILE_DETECT: {
                "required": False,
                "label": labels["detect"],
                "selector": {"boolean": {}},
            },
            CONF_PROFILE_CAPTURE: {
                "required": False,
                "label": labels["capture"],
                "selector": {
                    "select": {
                        "options": list(CAPTURE_MODES),
                        "mode": "dropdown",
                        "translation_key": "capture",
                    }
                },
            },
        }

        for spec in vocab:
            key = spec.key
            label = labels.get(key) or names.get(key) or key
            if spec.kind == KIND_OPTION:
                if spec.is_climate and not spec.options and key != VALUE_HVAC_MODE:
                    # A value the device does not advertise: offering it would
                    # fill every row with a field that cannot be applied.
                    continue
                selector_config: dict[str, Any] = {
                    "select": {
                        "options": list(spec.options),
                        "mode": "dropdown",
                        "custom_value": spec.is_climate or not spec.options,
                        "sort": False,
                    }
                }
            elif spec.kind == KIND_NUMBER:
                number: dict[str, Any] = {
                    "min": spec.minimum if spec.minimum is not None else 0,
                    "max": spec.maximum if spec.maximum is not None else 100,
                    "step": spec.step or 1,
                    # A box, not a slider: a slider cannot be left empty, and
                    # an empty field is how a profile says "do not touch".
                    "mode": "box",
                }
                if key == VALUE_TEMPERATURE:
                    number["unit_of_measurement"] = "°C"
                selector_config = {"number": number}
            else:
                selector_config = {
                    "select": {
                        "options": list(ON_OFF_OPTIONS),
                        "mode": "dropdown",
                        "translation_key": "on_off",
                    }
                }
            fields[key] = {
                # A profile that does not say what the device should do is
                # rarely what anyone wants; everything else stays optional,
                # and an empty field means "do not touch".
                "required": key == VALUE_HVAC_MODE,
                "label": label,
                "selector": selector_config,
            }

        return fields

    def _values_from_rows(
        self, rows: list[dict[str, Any]]
    ) -> tuple[AdditionalValueSet | None, dict[str, str]]:
        """Return the values the rows describe, or what is wrong with them."""
        values = AdditionalValueSet()
        for index, row in enumerate(rows):
            entity_id = str(row.get(CONF_ADDITIONAL_ENTITY) or "")
            state = self.hass.states.get(entity_id)
            if state is None:
                return None, {CONF_ADDITIONAL: "entity_not_found"}
            if entity_id.partition(".")[0] not in ADDITIONAL_DOMAINS:
                return None, {CONF_ADDITIONAL: "unsupported_domain"}
            name = str(
                row.get(CONF_ADDITIONAL_NAME)
                or state.attributes.get("friendly_name")
                or entity_id
            ).strip()
            values = values.appended(
                AdditionalValue(
                    id=str(row.get(CONF_ADDITIONAL_ID) or "") or new_value_id(),
                    name=values.unique_name(name),
                    entity=entity_id,
                    icon=row.get(CONF_ADDITIONAL_ICON) or None,
                    order=index,
                )
            )
        return values, {}

    def _appended_from_entity(
        self, values: AdditionalValueSet, entity_id: str
    ) -> AdditionalValueSet:
        """Add one of the device's own entities to the end of the list."""
        state = self.hass.states.get(entity_id)
        name = str(
            (state.attributes.get("friendly_name") if state else None) or entity_id
        ).strip()
        return values.appended(
            AdditionalValue(
                id=new_value_id(),
                name=values.unique_name(name),
                entity=entity_id,
                order=values.next_order(),
            )
        )

    def _profiles_from_rows(
        self, rows: list[dict[str, Any]], vocab: Vocabulary
    ) -> tuple[ProfileSet | None, dict[str, str]]:
        """Return the profiles the rows describe, or what is wrong with them."""
        profiles: list[ClimateProfile] = []
        for row in rows:
            try:
                profiles.append(
                    profile_from_input(
                        row,
                        vocab,
                        profile_id=str(row.get(CONF_PROFILE_ID) or "") or None,
                    )
                )
            except (ProfileError, ValueError, KeyError) as err:
                _LOGGER.debug("Invalid profile row: %s", err)
                return None, {CONF_PROFILES: "invalid_profile"}
        return ProfileSet(tuple(profiles)), {}

    def _order_from_input(self, user_input: dict[str, Any]) -> list[str]:
        """Return the apply order, keeping what the form did not mention."""
        current = [option["value"] for option in self._order_options()]
        wanted = [
            key
            for key in dict.fromkeys(user_input.get(CONF_ORDER) or [])
            if key in current
        ]
        return wanted + [key for key in current if key not in wanted]
