"""The number values of every profile - its temperature, and number valued ones.

See ``profile_values`` for why each value a profile sets is an entity.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import KIND_NUMBER, VALUE_TEMPERATURE
from .coordinator import ClimateProfilesConfigEntry
from .matching import normalise_value
from .profile_values import ProfileValueEntity, async_track_profile_values

#: What a temperature entity spans when the climate entity does not say.
_TEMPERATURE_RANGE = (5.0, 35.0)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ClimateProfilesConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a number per profile and number valued value it sets."""
    async_track_profile_values(
        entry, async_add_entities, Platform.NUMBER, KIND_NUMBER, ProfileNumber
    )


class ProfileNumber(ProfileValueEntity, NumberEntity):
    """A number one profile sets."""

    # A box, not a slider: these are settings, typed in rather than dragged.
    _attr_mode = NumberMode.BOX

    @property
    def native_min_value(self) -> float:
        """Return the lowest value the entity behind it takes."""
        spec = self._spec
        if spec is not None and spec.minimum is not None:
            return spec.minimum
        return _TEMPERATURE_RANGE[0] if self._value_key == VALUE_TEMPERATURE else 0.0

    @property
    def native_max_value(self) -> float:
        """Return the highest value the entity behind it takes."""
        spec = self._spec
        if spec is not None and spec.maximum is not None:
            return spec.maximum
        return _TEMPERATURE_RANGE[1] if self._value_key == VALUE_TEMPERATURE else 100.0

    @property
    def native_step(self) -> float:
        """Return the step of the entity behind it."""
        spec = self._spec
        return spec.step if spec is not None and spec.step else 1.0

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of the entity behind it."""
        if self._value_key == VALUE_TEMPERATURE:
            return self.hass.config.units.temperature_unit
        value = self.coordinator.additional.get(self._value_key)
        state = self.hass.states.get(value.entity) if value else None
        return state.attributes.get("unit_of_measurement") if state else None

    @property
    def native_value(self) -> float | None:
        """Return the stored value, ``None`` if the device cannot take it.

        A value outside the device's range is not something to pick: it is
        reported unknown rather than as a number the entity would refuse.
        """
        number = normalise_value(self._spec, self._stored)
        if number is None:
            return None
        spec = self._spec
        if spec is not None and (
            (spec.minimum is not None and number < spec.minimum)
            or (spec.maximum is not None and number > spec.maximum)
        ):
            return None
        return number

    async def async_set_native_value(self, value: float) -> None:
        """Store the value in the profile."""
        await self._async_write(value)
