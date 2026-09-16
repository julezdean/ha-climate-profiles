"""Sensor entity exposing the active profile - and the integration's services."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_ACTIVE_PROFILE,
    ATTR_ACTIVE_PROFILE_COLOR,
    ATTR_ACTIVE_PROFILE_ID,
    ATTR_APPLYING,
    ATTR_CAPABILITIES,
    ATTR_CHANGED_VALUES,
    ATTR_COLOR,
    ATTR_CURRENT_VALUES,
    ATTR_ENTITIES,
    ATTR_ICON,
    ATTR_LAST_MATCHED_PROFILE_ID,
    ATTR_NAME,
    ATTR_PROFILE,
    ATTR_PROFILES,
    ATTR_VALUES,
    CUSTOM_PROFILE_ID,
    DEFAULT_CUSTOM_COLOR,
    SERVICE_APPLY_PROFILE,
    SERVICE_CAPTURE_PROFILE,
    SERVICE_SAVE_AS_PROFILE,
    SERVICE_SET_VALUE,
    VALUE_DISPLAY,
    VALUE_FAN,
    VALUE_FAN_MODE,
    VALUE_HVAC_MODE,
    VALUE_KEYS,
    VALUE_SILENT,
    VALUE_SWING_MODE,
    VALUE_TEMPERATURE,
)
from .coordinator import ClimateProfilesConfigEntry
from .entity import ClimateProfilesEntity
from .matching import normalise_values

SET_VALUE_SCHEMA = vol.All(
    cv.make_entity_service_schema(
        {
            vol.Optional(VALUE_HVAC_MODE): cv.string,
            vol.Optional(VALUE_TEMPERATURE): vol.Coerce(float),
            vol.Optional(VALUE_SWING_MODE): cv.string,
            vol.Optional(VALUE_FAN_MODE): cv.string,
            vol.Optional(VALUE_FAN): vol.Coerce(float),
            vol.Optional(VALUE_DISPLAY): cv.boolean,
            vol.Optional(VALUE_SILENT): cv.boolean,
        }
    ),
    cv.has_at_least_one_key(*VALUE_KEYS),
)


CAPTURE_PROFILE_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Optional(ATTR_PROFILE): cv.string,
        vol.Optional(ATTR_VALUES): vol.All(cv.ensure_list, [vol.In(VALUE_KEYS)]),
    }
)

SAVE_AS_PROFILE_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_NAME): cv.string,
        vol.Optional(ATTR_COLOR): cv.string,
        vol.Optional(ATTR_ICON): cv.icon,
        vol.Optional(ATTR_VALUES): vol.All(cv.ensure_list, [vol.In(VALUE_KEYS)]),
    }
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClimateProfilesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the profile sensor and register the services."""
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_APPLY_PROFILE,
        {vol.Required(ATTR_PROFILE): cv.string},
        "async_apply_profile_service",
    )
    platform.async_register_entity_service(
        SERVICE_SET_VALUE, SET_VALUE_SCHEMA, "async_set_value_service"
    )
    platform.async_register_entity_service(
        SERVICE_CAPTURE_PROFILE, CAPTURE_PROFILE_SCHEMA, "async_capture_profile_service"
    )
    platform.async_register_entity_service(
        SERVICE_SAVE_AS_PROFILE, SAVE_AS_PROFILE_SCHEMA, "async_save_as_profile_service"
    )

    async_add_entities([ActiveProfileSensor(entry.runtime_data)])


class ActiveProfileSensor(ClimateProfilesEntity, SensorEntity):
    """The name of the profile that currently matches the device's state."""

    _attr_translation_key = "active_profile"
    _attr_icon = "mdi:air-conditioner"

    def __init__(self, coordinator) -> None:
        """Set up the sensor."""
        super().__init__(coordinator, "active_profile")

    @property
    def native_value(self) -> str:
        """Return the display name of the active profile."""
        data = self.coordinator.data
        return self.coordinator.profile_name(data.active if data else None)

    @property
    def icon(self) -> str:
        """Prefer the active profile's own icon, if it has one."""
        data = self.coordinator.data
        if data and data.active and data.active.icon:
            return data.active.icon
        return self._attr_icon

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Everything the card needs, in one place.

        The card is a renderer: it reads this, it does not re-implement any of
        the matching.
        """
        coordinator = self.coordinator
        data = coordinator.data
        profiles = coordinator.profiles
        names = profiles.display_names()

        active = data.active if data else None
        return {
            ATTR_ACTIVE_PROFILE: coordinator.profile_name(active),
            ATTR_ACTIVE_PROFILE_ID: active.id if active else CUSTOM_PROFILE_ID,
            ATTR_ACTIVE_PROFILE_COLOR: coordinator.profile_color(active),
            ATTR_PROFILES: [
                {
                    "id": profile.id,
                    "name": names.get(profile.id, profile.name),
                    "color": profile.color,
                    "icon": profile.icon,
                    "order": order,
                    "protected": profile.protected,
                    "values": dict(profile.values),
                }
                for order, profile in enumerate(profiles)
            ],
            "custom_profile": {
                "id": CUSTOM_PROFILE_ID,
                "name": coordinator.custom_name,
                "color": DEFAULT_CUSTOM_COLOR,
            },
            ATTR_CURRENT_VALUES: normalise_values(data.values) if data else {},
            ATTR_CAPABILITIES: data.capabilities.as_dict() if data else {},
            ATTR_ENTITIES: coordinator.entities.as_dict(),
            ATTR_APPLYING: bool(data and data.applying),
            # What "capture" would write into, and what it would change.
            # Both are empty right after a restart - see ProfileState.
            ATTR_LAST_MATCHED_PROFILE_ID: (
                data.last_matched.id if data and data.last_matched else None
            ),
            ATTR_CHANGED_VALUES: list(data.changed) if data else [],
        }

    # -- services -----------------------------------------------------------

    async def async_apply_profile_service(self, profile: str) -> None:
        """Handle ``climate_profiles.apply_profile``."""
        await self.coordinator.async_apply_profile(profile)

    async def async_set_value_service(self, **values: Any) -> None:
        """Handle ``climate_profiles.set_value``."""
        await self.coordinator.async_set_values(
            {key: value for key, value in values.items() if key in VALUE_KEYS}
        )

    async def async_capture_profile_service(
        self, profile: str | None = None, values: list[str] | None = None
    ) -> None:
        """Handle ``climate_profiles.capture_profile``."""
        await self.coordinator.async_capture_into_profile(profile, keys=values)

    async def async_save_as_profile_service(
        self,
        name: str,
        color: str | None = None,
        icon: str | None = None,
        values: list[str] | None = None,
    ) -> None:
        """Handle ``climate_profiles.save_as_profile``."""
        await self.coordinator.async_save_as_profile(
            name, color=color, icon=icon, keys=values
        )
