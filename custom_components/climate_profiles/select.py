"""Select entity to pick a profile - the native way to expose presets.

Having a select makes profiles usable from automations, scripts, voice
assistants and the default dashboard without the custom card.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import KIND_OPTION
from .coordinator import ClimateProfilesConfigEntry
from .entity import ClimateProfilesEntity
from .matching import canonical_option
from .profile_values import ProfileValueEntity, async_track_profile_values


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClimateProfilesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the profile select, and one per option valued profile value."""
    async_add_entities([ProfileSelect(entry.runtime_data)])
    async_track_profile_values(
        entry, async_add_entities, Platform.SELECT, KIND_OPTION, ProfileOptionSelect
    )


class ProfileSelect(ClimateProfilesEntity, SelectEntity):
    """Selects a profile; shows "custom" when the state matches none.

    In automatic mode there is no custom: the profile automatic mode holds is
    the active one, and before it holds any the state is unknown.
    """

    _attr_translation_key = "profile"
    _attr_icon = "mdi:playlist-check"

    def __init__(self, coordinator) -> None:
        """Set up the select."""
        super().__init__(coordinator, "profile")

    @property
    def options(self) -> list[str]:
        """Return the stored profiles plus the virtual custom entry."""
        names = [profile.name for profile in self.coordinator.profiles]
        if self.coordinator.automatic_on:
            return names
        return [*names, self.coordinator.custom_name]

    @property
    def current_option(self) -> str | None:
        """Return the active profile's name."""
        data = self.coordinator.data
        if data is not None and data.unknown:
            return None
        return self.coordinator.profile_name(data.active if data else None)

    async def async_select_option(self, option: str) -> None:
        """Apply the chosen profile.

        Choosing "custom" is a no-op on purpose: it is a status, not a preset,
        and must never write values back to the device.
        """
        await self.coordinator.async_apply_profile(option)


class ProfileOptionSelect(ProfileValueEntity, SelectEntity):
    """An option one profile sets - a mode, or an option valued value."""

    @property
    def options(self) -> list[str]:
        """Return what the device offers right now."""
        spec = self._spec
        return list(spec.options) if spec is not None else []

    @property
    def current_option(self) -> str | None:
        """Return the stored option in the device's spelling.

        ``None`` - unknown - when the device does not offer it: an option it
        dropped is not something to pick, and the select would refuse it.
        """
        stored = self._stored
        options = self.options
        if stored is None or not options:
            return None
        return canonical_option(str(stored), options)

    async def async_select_option(self, option: str) -> None:
        """Store the option in the profile."""
        await self._async_write(option)
