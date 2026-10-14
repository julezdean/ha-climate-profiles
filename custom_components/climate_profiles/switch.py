"""One switch per profile: whether it is write protected - and automatic mode.

Write protection is the one profile setting that is switched in daily use - a
profile held for the winter, one locked before guests come - so it is an
entity, usable from automations and dashboards. Recognition and hiding are
decided once when a profile is set up and stay in the options.

Automatic mode is a switch for the same reason, and exists only while a
profile sensor is configured: without one there is nothing it could follow.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import ClimateProfilesConfigEntry, ClimateProfilesCoordinator
from .entity import ClimateProfilesEntity
from .models import ClimateProfile

#: Prefix of the key each switch is registered under, followed by the id of
#: its profile - so renaming the profile keeps the entity, and its entity id.
_KEY_PREFIX = "protected_"
_AUTOMATIC_KEY = "automatic"


def _unique_id(entry: ClimateProfilesConfigEntry, profile_id: str) -> str:
    """Return the unique id of the switch of ``profile_id``."""
    return f"{entry.entry_id}_{_KEY_PREFIX}{profile_id}"


def protection_entity_id(
    registry: er.EntityRegistry, entry: ClimateProfilesConfigEntry, profile_id: str
) -> str | None:
    """Return the entity id of the switch of ``profile_id``, if it exists yet."""
    return registry.async_get_entity_id(
        Platform.SWITCH, DOMAIN, _unique_id(entry, profile_id)
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClimateProfilesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a switch per profile, and follow profiles as they come and go.

    Profiles are added and deleted in the options without a reload - a reload
    would make every entity blink - so the switches have to follow on their
    own: one added for a new profile, one taken out of the registry for a
    deleted one.
    """
    coordinator = entry.runtime_data
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_{_KEY_PREFIX}"
    known: set[str] = set()

    @callback
    def _sync() -> None:
        profiles = coordinator.profiles
        wanted = [profile.id for profile in profiles]
        new = [profile_id for profile_id in wanted if profile_id not in known]
        if new:
            known.update(new)
            async_add_entities(
                ProtectedSwitch(coordinator, profile_id) for profile_id in new
            )

        # Read from the registry rather than from what this run added: a
        # profile deleted while the entry was not loaded left its switch
        # behind there, and nothing else would ever remove it.
        for item in er.async_entries_for_config_entry(registry, entry.entry_id):
            if item.domain != Platform.SWITCH or not item.unique_id.startswith(prefix):
                continue
            profile_id = item.unique_id.removeprefix(prefix)
            if profile_id not in wanted:
                known.discard(profile_id)
                registry.async_remove(item.entity_id)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))

    # The sensor is baked into the coordinator, so its switch is decided once
    # per setup; one left from a removed sensor is taken out of the registry.
    if coordinator.profile_sensor is not None:
        async_add_entities([AutomaticSwitch(coordinator)])
    elif stale := registry.async_get_entity_id(
        Platform.SWITCH, DOMAIN, f"{entry.entry_id}_{_AUTOMATIC_KEY}"
    ):
        registry.async_remove(stale)


class ProtectedSwitch(ClimateProfilesEntity, SwitchEntity):
    """Whether one profile keeps manual changes out."""

    _attr_translation_key = "protected"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: ClimateProfilesCoordinator, profile_id: str
    ) -> None:
        """Bind the switch to its profile."""
        super().__init__(coordinator, f"{_KEY_PREFIX}{profile_id}")
        self._profile_id = profile_id

    @property
    def _profile(self) -> ClimateProfile | None:
        """Return the profile, or ``None`` once it has been deleted."""
        return self.coordinator.profiles.get(self._profile_id)

    @property
    def translation_placeholders(self) -> Mapping[str, str]:
        """Name the profile in the switch's name - read anew, it can be renamed."""
        profile = self._profile
        return {"profile": profile.name if profile else self._profile_id}

    @property
    def name(self) -> Any:
        """Return the name, following a renamed profile.

        Home Assistant caches an entity's name for good; this one is built
        from the profile's, which changes in the options without a reload.
        """
        translations = (
            self.platform_data.platform_translations if self.platform_data else {}
        )
        return self._name_internal(None, translations)

    @property
    def available(self) -> bool:
        """Report available while the profile exists.

        Unlike the other entities this one does not follow the climate entity:
        whether a profile is protected is a setting, and can be changed while
        the device is away.
        """
        return self.coordinator.last_update_success and self._profile is not None

    @property
    def is_on(self) -> bool:
        """Return whether the profile is write protected."""
        profile = self._profile
        return bool(profile and profile.protected)

    @property
    def icon(self) -> str:
        """Show a closed lock while protected, an open one otherwise."""
        return "mdi:lock" if self.is_on else "mdi:lock-open-variant-outline"

    async def async_added_to_hass(self) -> None:
        """Let the sensor name this switch, now that it has an entity id.

        The sensor hands the card each profile's switch. A new profile's
        switch is registered only after the update that brought the profile,
        so without another one the card would not see it until something else
        changed.
        """
        await super().async_added_to_hass()
        self.coordinator.async_update_listeners()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Write protect the profile."""
        await self.coordinator.async_set_protected(self._profile_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Lift the protection."""
        await self.coordinator.async_set_protected(self._profile_id, False)


class AutomaticSwitch(ClimateProfilesEntity, SwitchEntity):
    """Whether the profile sensor decides which profile is active."""

    _attr_translation_key = _AUTOMATIC_KEY
    _attr_icon = "mdi:auto-mode"

    def __init__(self, coordinator: ClimateProfilesCoordinator) -> None:
        """Set up the switch."""
        super().__init__(coordinator, _AUTOMATIC_KEY)

    @property
    def is_on(self) -> bool:
        """Return whether automatic mode is on.

        On means on, also while the sensor has nothing to follow: that is what
        was chosen, and the sensor's ``automatic`` attribute says it waits.
        """
        return self.coordinator.automatic_on

    @property
    def available(self) -> bool:
        """Report available while the device is not.

        Switching automatic mode is a decision about the future; the profile
        is applied once the device is back and the sensor names it again.
        """
        return self.coordinator.last_update_success

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Let the profile sensor decide."""
        await self.coordinator.async_set_automatic(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Give the choice back."""
        await self.coordinator.async_set_automatic(False)
