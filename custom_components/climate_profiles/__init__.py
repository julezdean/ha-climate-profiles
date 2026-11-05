"""The Climate Profiles integration.

Turns any climate entity - plus the optional number/switch entities many air
conditioners expose - into a set of freely configurable profiles, and tells you
which one is currently active.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ADDITIONAL,
    CONF_CUSTOM_NAME,
    CONF_PROFILE_NAME,
    CONF_PROFILE_SENSOR,
    CONF_PROFILE_VALUES,
    CONF_PROFILES,
    CONF_VALUE_ORDER,
    DEFAULT_CUSTOM_NAME,
    DOMAIN,
)
from .coordinator import ClimateProfilesConfigEntry, ClimateProfilesCoordinator
from .frontend import async_register_card, async_remove_card
from .keys import value_key
from .models import (
    AdditionalValueSet,
    EntityMap,
    ProfileError,
    ProfileSet,
    reserved_profile_names,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SELECT, Platform.SENSOR, Platform.SWITCH]

#: This integration is set up from the UI only. Saying so explicitly is what
#: hassfest asks for, and it makes a stray `climate_profiles:` block in
#: configuration.yaml an error rather than something silently ignored.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Register the Lovelace card, even before the first entry exists."""
    await async_register_card(hass)
    return True


async def async_migrate_entry(
    hass: HomeAssistant, entry: ClimateProfilesConfigEntry
) -> bool:
    """Give the additional values readable keys - version 1 to 2.

    Their uuids are replaced in the three places that hold them: the
    definitions, the values of every profile and the apply order. Each value
    keeps its uuid as ``former_id``, because the dashboards hiding it by that
    id are not the integration's to rewrite.
    """
    if entry.version > 2:
        # Written by a newer version: nothing here knows how to read it.
        return False
    if entry.version == 1:
        options = _with_readable_keys(hass, dict(entry.options))
        hass.config_entries.async_update_entry(entry, options=options, version=2)
        _LOGGER.debug("%s: additional values have readable keys", entry.title)
    return True


def _with_readable_keys(hass: HomeAssistant, options: dict[str, Any]) -> dict[str, Any]:
    """Return ``options`` with every additional value's uuid replaced by a key."""
    try:
        values = AdditionalValueSet.from_list(options.get(CONF_ADDITIONAL))
    except ProfileError as err:
        # Left as it is: the coordinator reports it, and a set that cannot be
        # read cannot be migrated either.
        _LOGGER.error("Additional values cannot be migrated: %s", err)
        return options

    renamed: dict[str, str] = {}
    migrated = AdditionalValueSet()
    for value in values:
        key = value_key(hass, value.entity, value.name, migrated.keys())
        renamed[value.id] = key
        migrated = migrated.appended(
            replace(value, id=key, former_id=value.former_id or value.id)
        )

    def rekeyed(stored: dict[str, Any]) -> dict[str, Any]:
        return {renamed.get(key, key): item for key, item in stored.items()}

    profiles = [
        {**raw, CONF_PROFILE_VALUES: rekeyed(raw.get(CONF_PROFILE_VALUES) or {})}
        if isinstance(raw, dict)
        else raw
        for raw in options.get(CONF_PROFILES) or []
    ]
    return {
        **options,
        CONF_ADDITIONAL: migrated.as_list(),
        CONF_PROFILES: profiles,
        CONF_VALUE_ORDER: [
            renamed.get(key, key) for key in options.get(CONF_VALUE_ORDER) or []
        ],
    }


async def async_setup_entry(
    hass: HomeAssistant, entry: ClimateProfilesConfigEntry
) -> bool:
    """Set up one configured device."""
    _store_unique_names(hass, entry)
    _remove_value_entities(hass, entry)
    try:
        coordinator = ClimateProfilesCoordinator(hass, entry)
    except ProfileError as err:
        raise ConfigEntryNotReady(str(err)) from err

    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    # After a restart this writes only if the sensor names another profile
    # than the one applied before it.
    entry.async_create_background_task(
        hass, coordinator.async_follow_sensor(), "climate_profiles follow sensor"
    )

    # Reconciled per entry, not once per run: async_setup does not run again
    # when an entry is added after the last one was removed.
    await async_register_card(hass)
    return True


def _remove_value_entities(
    hass: HomeAssistant, entry: ClimateProfilesConfigEntry
) -> None:
    """Take out the entities 3.0.0-beta.1 made for every profile value.

    They were replaced by the card's edit mode before 3.0 was released. Left
    in the registry they would stay forever as entities nothing provides.
    """
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_value_"
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        if item.unique_id.startswith(prefix):
            registry.async_remove(item.entity_id)


def _store_unique_names(hass: HomeAssistant, entry: ClimateProfilesConfigEntry) -> None:
    """Rename profiles stored before names had to be unique, once.

    Loading repairs duplicates too, but only in memory: which of two
    "Komfort" gets the counter depends on the order, and a name that changes
    when the order does is no name to rely on. Stored, it stays put. Done
    before the update listener is attached, so no listener reacts to it.
    """
    raw = entry.options.get(CONF_PROFILES)
    try:
        stored = ProfileSet.from_list(raw)
    except ProfileError:
        return  # the coordinator reports it
    custom_name = str(entry.options.get(CONF_CUSTOM_NAME) or "").strip()
    unique = stored.with_unique_names(
        reserved_profile_names(custom_name or DEFAULT_CUSTOM_NAME)
    )
    renamed = [
        (before, after.name)
        for before, after in zip(
            (str(item[CONF_PROFILE_NAME]).strip() for item in raw or []),
            unique,
            strict=True,
        )
        if before != after.name
    ]
    if not renamed:
        return
    for before, after in renamed:
        _LOGGER.warning(
            "%s: profile %r renamed to %r - profile names have to be unique",
            entry.title,
            before,
            after,
        )
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_PROFILES: unique.as_list()}
    )


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
    would reload the entry. The profile sensor is the same case.
    """
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is None:
        await hass.config_entries.async_reload(entry.entry_id)
        return

    try:
        additional = AdditionalValueSet.from_list(entry.options.get(CONF_ADDITIONAL))
    except ProfileError:
        additional = AdditionalValueSet()

    sensor = entry.options.get(CONF_PROFILE_SENSOR) or None
    if (
        coordinator.entities == EntityMap.from_config(entry.data, additional)
        and coordinator.profile_sensor == sensor
    ):
        await coordinator.async_refresh()
        # A renamed profile may be the one the sensor has been naming.
        await coordinator.async_follow_sensor()
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
