"""Shared base class for the entities of a config entry."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ClimateProfilesCoordinator


class ClimateProfilesEntity(CoordinatorEntity[ClimateProfilesCoordinator]):
    """Base entity for the integration.

    Each config entry gets its own device, so several air conditioners never
    share anything.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: ClimateProfilesCoordinator, key: str) -> None:
        """Bind the entity to its coordinator."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Climate Profiles",
            model="Climate profile controller",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        """Report unavailable while the climate entity is."""
        return super().available and bool(
            self.coordinator.data and self.coordinator.data.available
        )
