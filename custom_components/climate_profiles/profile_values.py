"""One entity per value a profile sets - shared by number, select and switch.

Seeing what a profile sets used to mean opening it in the options, and so did
changing one number. These entities put every value of every profile on the
device page, under Configuration, and let it be changed there, from a
dashboard or from an automation.

Only values a profile actually sets get one: "not set" is no state an entity
could show, and what is visible is then exactly what each profile does. A
value put into a profile in the options brings its entity, one taken out
takes it along - without a reload, which would make every entity blink.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CLIMATE_KINDS, VALUE_FAN_MODE, VALUE_HVAC_MODE, VALUE_SWING_MODE
from .coordinator import ClimateProfilesConfigEntry, ClimateProfilesCoordinator
from .entity import ClimateProfilesEntity
from .models import ClimateProfile, ValueSpec

#: Prefix of the key each entity is registered under, followed by the id of
#: its profile and the value's key - so renaming the profile renames the
#: entity but keeps its entity id.
_KEY_PREFIX = "value_"

_ICONS: dict[str, str] = {
    "temperature": "mdi:thermometer",
    VALUE_HVAC_MODE: "mdi:thermostat",
    VALUE_FAN_MODE: "mdi:fan",
    VALUE_SWING_MODE: "mdi:arrow-oscillating",
}


def _key(profile_id: str, value_key: str) -> str:
    return f"{_KEY_PREFIX}{profile_id}_{value_key}"


@callback
def async_track_profile_values(
    entry: ClimateProfilesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    domain: str,
    kind: str,
    factory: Callable[[ClimateProfilesCoordinator, str, str], ProfileValueEntity],
) -> None:
    """Keep one entity per profile and value of ``kind`` in this platform.

    Called by each of the three platforms with its own kind. The registry is
    read for what to remove rather than what this run added: a value taken out
    while the entry was not loaded left its entity behind there, and nothing
    else would ever remove it.
    """
    coordinator = entry.runtime_data
    registry = er.async_get(coordinator.hass)
    prefix = f"{entry.entry_id}_{_KEY_PREFIX}"
    known: set[str] = set()

    @callback
    def _sync() -> None:
        state = coordinator.data
        if state is None:
            return
        wanted = {
            f"{entry.entry_id}_{_key(profile.id, key)}": (profile.id, key)
            for profile, key in _profile_values(coordinator.profiles)
            if (spec := state.vocabulary.get(key)) is not None and spec.kind == kind
        }
        new = [unique_id for unique_id in wanted if unique_id not in known]
        if new:
            known.update(new)
            async_add_entities(factory(coordinator, *wanted[uid]) for uid in new)

        for item in er.async_entries_for_config_entry(registry, entry.entry_id):
            if item.domain != domain or not item.unique_id.startswith(prefix):
                continue
            if item.unique_id not in wanted:
                known.discard(item.unique_id)
                registry.async_remove(item.entity_id)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


def _profile_values(
    profiles: Iterable[ClimateProfile],
) -> Iterable[tuple[ClimateProfile, str]]:
    """Return every (profile, key) a profile sets."""
    for profile in profiles:
        for key in profile.values:
            yield profile, key


class ProfileValueEntity(ClimateProfilesEntity):
    """One value one profile sets."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: ClimateProfilesCoordinator, profile_id: str, key: str
    ) -> None:
        """Bind the entity to its profile and value."""
        super().__init__(coordinator, _key(profile_id, key))
        self._profile_id = profile_id
        self._value_key = key
        # The four climate values have names of their own, in Home
        # Assistant's language; an additional value brings its own.
        self._attr_translation_key = (
            f"profile_{key}" if key in CLIMATE_KINDS else "profile_value"
        )

    @property
    def _profile(self) -> ClimateProfile | None:
        """Return the profile, or ``None`` once it has been deleted."""
        return self.coordinator.profiles.get(self._profile_id)

    @property
    def _spec(self) -> ValueSpec | None:
        """Return what the entry knows about the value right now."""
        state = self.coordinator.data
        return state.vocabulary.get(self._value_key) if state else None

    @property
    def _stored(self) -> Any:
        """Return the value as the profile stores it, ``None`` if it is gone."""
        profile = self._profile
        return profile.values.get(self._value_key) if profile else None

    @property
    def translation_placeholders(self) -> Mapping[str, str]:
        """Name the profile and the value - read anew, both can be renamed."""
        profile = self._profile
        value = self.coordinator.additional.get(self._value_key)
        return {
            "profile": profile.name if profile else self._profile_id,
            "value": value.name if value else self._value_key,
        }

    @property
    def name(self) -> Any:
        """Return the name, following a renamed profile or value.

        Home Assistant caches an entity's name for good; this one is built
        from the profile's, which changes in the options without a reload.
        """
        translations = (
            self.platform_data.platform_translations if self.platform_data else {}
        )
        return self._name_internal(None, translations)

    @property
    def icon(self) -> str | None:
        """Return the additional value's icon, or one for the climate value."""
        if value := self.coordinator.additional.get(self._value_key):
            return value.icon
        return _ICONS.get(self._value_key)

    @property
    def available(self) -> bool:
        """Report available while the profile still sets the value.

        Not tied to the device: what a profile sets is a setting, and can be
        changed while the device is away.
        """
        return (
            self.coordinator.last_update_success
            and self._profile is not None
            and self._value_key in (self._profile.values or {})
        )

    async def _async_write(self, value: Any) -> None:
        """Store the value in the profile - and apply it if that is active."""
        await self.coordinator.async_set_profile_value(
            self._profile_id, self._value_key, value
        )
