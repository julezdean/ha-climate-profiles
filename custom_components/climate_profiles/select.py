"""Select entity to pick a profile - the native way to expose presets.

Having a select makes profiles usable from automations, scripts, voice
assistants and the default dashboard without the custom card.
"""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ClimateProfilesConfigEntry
from .entity import ClimateProfilesEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClimateProfilesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the profile select."""
    async_add_entities([ProfileSelect(entry.runtime_data)])


class ProfileSelect(ClimateProfilesEntity, SelectEntity):
    """Selects a profile; shows "custom" when the state matches none."""

    _attr_translation_key = "profile"
    _attr_icon = "mdi:playlist-check"

    def __init__(self, coordinator) -> None:
        """Set up the select."""
        super().__init__(coordinator, "profile")

    @property
    def options(self) -> list[str]:
        """Return the stored profiles plus the virtual custom entry."""
        names = self.coordinator.profiles.display_names()
        return [*names.values(), self.coordinator.custom_name]

    @property
    def current_option(self) -> str:
        """Return the active profile's name."""
        data = self.coordinator.data
        return self.coordinator.profile_name(data.active if data else None)

    async def async_select_option(self, option: str) -> None:
        """Apply the chosen profile.

        Choosing "custom" is a no-op on purpose: it is a status, not a preset,
        and must never write values back to the device.
        """
        await self.coordinator.async_apply_profile(option)
