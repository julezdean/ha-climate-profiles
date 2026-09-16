"""The Climate Profiles integration.

Turns any climate entity - plus the optional number/switch entities many air
conditioners expose - into a set of freely configurable profiles, and tells you
which one is currently active.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .coordinator import ClimateProfilesConfigEntry, ClimateProfilesCoordinator
from .models import EntityMap, ProfileError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SELECT, Platform.SENSOR]

FRONTEND_URL_BASE = f"/{DOMAIN}/frontend"
CARD_FILENAME = "climate-profile-card.js"
_FRONTEND_REGISTERED = f"{DOMAIN}_frontend_registered"


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Register the Lovelace card once, even before the first entry exists."""
    await _async_register_frontend(hass)
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
    """
    coordinator = getattr(entry, "runtime_data", None)
    if coordinator is not None and coordinator.entities == EntityMap.from_config(
        entry.data
    ):
        await coordinator.async_refresh()
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the Lovelace card and load it automatically.

    Users do not have to add a Lovelace resource by hand; the version query
    string busts the browser cache after an update.
    """
    if hass.data.get(_FRONTEND_REGISTERED):
        return
    hass.data[_FRONTEND_REGISTERED] = True

    card_path = Path(__file__).parent / "frontend" / CARD_FILENAME
    if not card_path.is_file():  # pragma: no cover - broken installation
        _LOGGER.error("Lovelace card is missing at %s", card_path)
        return

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"{FRONTEND_URL_BASE}/{CARD_FILENAME}", str(card_path), False
            )
        ]
    )

    integration = await async_get_integration(hass, DOMAIN)
    url = f"{FRONTEND_URL_BASE}/{CARD_FILENAME}?v={integration.version}"

    # The integration is fully usable without a frontend (entities, services,
    # automations), so a missing frontend is a note, not a failure.
    if "frontend" in hass.config.components:
        frontend.add_extra_js_url(hass, url)
        _LOGGER.debug("Registered %s at %s", CARD_FILENAME, url)
    else:
        _LOGGER.info(
            "Frontend not loaded - add %s as a Lovelace resource manually if "
            "you want the card",
            url,
        )
