"""The Climate Profiles integration.

Turns any climate entity - plus the optional number/switch entities many air
conditioners expose - into a set of freely configurable profiles, and tells you
which one is currently active.
"""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import CONF_ADDITIONAL, DOMAIN
from .coordinator import ClimateProfilesConfigEntry, ClimateProfilesCoordinator
from .frontend import async_register_card, async_remove_card
from .models import AdditionalValueSet, EntityMap, ProfileError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SELECT, Platform.SENSOR]

#: This integration is set up from the UI only. Saying so explicitly is what
#: hassfest asks for, and it makes a stray `climate_profiles:` block in
#: configuration.yaml an error rather than something silently ignored.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Register the Lovelace card, even before the first entry exists."""
    await async_register_card(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: ClimateProfilesConfigEntry
) -> bool:
    """Set up one configured device."""
    try:
        coordinator = ClimateProfilesCoordinator(hass, entry)
    except ProfileError as err:
        raise ConfigEntryNotReady(str(err)) from err

    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Reconciled per entry, not once per run: async_setup does not run again
    # when an entry is added after the last one was removed.
    await async_register_card(hass)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ClimateProfilesConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(
    hass: HomeAssistant, entry: ClimateProfilesConfigEntry
) -> None:
    """React to a changed configuration.

    Only the entity map is baked into the coordinator; profiles and the custom
    name are read fresh on every access. So a pure options change just needs a
    recalculation - capturing a profile from the card would otherwise reload
    the entry and make every entity blink.

    The additional values live in the options but are part of that map: a
    different set of entities has to be listened to, which only a reload does.
    So the comparison has to read them from the options too, or every capture
    would reload the entry.
    """
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        await hass.config_entries.async_reload(entry.entry_id)
        return

    try:
        additional = AdditionalValueSet.from_list(entry.options.get(CONF_ADDITIONAL))
    except ProfileError:
        additional = AdditionalValueSet()

    if coordinator.entities == EntityMap.from_config(entry.data, additional):
        await coordinator.async_refresh()
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(
    hass: HomeAssistant, entry: ClimateProfilesConfigEntry
) -> None:
    """Take the Lovelace resource out with the last entry.

    Left behind, it would point at a path nothing serves once the integration
    is uninstalled - and a dead resource looks exactly like a broken card.
    """
    remaining = [
        item
        for item in hass.config_entries.async_entries(DOMAIN)
        if item.entry_id != entry.entry_id
    ]
    if not remaining:
        await async_remove_card(hass)
