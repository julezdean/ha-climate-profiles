"""Serves the Lovelace card that ships with this integration.

The card lives in ``frontend/climate-profile-card.js`` inside the integration,
so installing the integration is all it takes to get it.

**It arrives as a Lovelace resource**, the same list HACS writes to and the one
under **Settings -> Dashboards -> Resources**. The frontend reads that list over
the websocket API at runtime, which is the part that matters.

``frontend.add_extra_js_url`` is the lighter looking alternative and was what
this integration used first. It puts a ``<script>`` into the Home Assistant
page, and that page is cached by the service worker, per browser and per phone.
A client holding a copy from before the card existed keeps serving it - across
restarts of Home Assistant, past a hard reload, and looking exactly like a card
that is broken rather than one that was never delivered.

The URL carries the integration version, so a browser that cached the previous
build fetches the new one after an update instead of running last week's card
against this week's attributes. The resource is matched by path rather than by
the whole URL: otherwise every release would add a second entry, and a custom
element may only be defined once - a pile of dead entries does not merely look
untidy, it stops the card from working.

Registration is idempotent and runs on every entry setup, not only once per
Home Assistant run. Serving the static path happens once; the resource is
reconciled each time. That way a config entry added after the last one was
removed gets its resource back without a restart.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILENAME = "climate-profile-card.js"
#: Not under ``/local``: that is the user's own ``www`` folder and nothing of
#: ours belongs in it.
URL_BASE = f"/{DOMAIN}/frontend"
CARD_URL = f"{URL_BASE}/{CARD_FILENAME}"

#: Marks the static route as served for this Home Assistant run. The resource
#: itself is reconciled on every call and needs no flag.
_STATIC_SERVED = f"{DOMAIN}_frontend_served"


def _lovelace_resources(hass: HomeAssistant) -> tuple[Any, str | None]:
    """Return the resource collection and the Lovelace mode.

    ``hass.data["lovelace"]`` has been a plain dict and a dataclass in different
    Home Assistant versions, so both are read. The mode field is called
    ``resource_mode`` on the dataclass (2026.2) and was ``mode`` before that;
    reading only one of them silently yields ``None`` and leaves the YAML case
    to be caught by the missing ``async_create_item`` further down.
    """
    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        return None, None
    if isinstance(lovelace, dict):
        mode = lovelace.get("resource_mode") or lovelace.get("mode")
        return lovelace.get("resources"), mode
    mode = getattr(lovelace, "resource_mode", None) or getattr(lovelace, "mode", None)
    return getattr(lovelace, "resources", None), mode


async def _async_writable_resources(hass: HomeAssistant, url: str) -> Any | None:
    """Return the resource collection, or ``None`` with a reason in the log."""
    resources, mode = _lovelace_resources(hass)
    if resources is None:
        _LOGGER.warning(
            "Lovelace is not set up, so the card was not registered. Add %s as "
            "a JavaScript module resource by hand",
            url,
        )
        return None

    if mode == "yaml" or not hasattr(resources, "async_create_item"):
        # In YAML mode the resource list is the user's file, not ours to edit.
        _LOGGER.warning(
            "Lovelace runs in YAML mode, so the card was not registered "
            "automatically. Add this to your Lovelace resources:\n"
            "  - url: %s\n    type: module",
            url,
        )
        return None

    # The storage collection is loaded lazily; at startup it usually is not.
    if getattr(resources, "loaded", True) is False:
        await resources.async_load()
        resources.loaded = True
    return resources


async def _async_reconcile_resource(hass: HomeAssistant, url: str) -> None:
    """Add the card to the Lovelace resources, or bring the entry up to date."""
    resources = await _async_writable_resources(hass, url)
    if resources is None:
        return

    for item in resources.async_items():
        if str(item.get("url", "")).split("?")[0] != CARD_URL:
            continue
        if item["url"] == url:
            _LOGGER.debug("Card resource %s already registered", url)
            return
        # Reuse the entry rather than adding a second one, so an entry left
        # over from an older version does not make the browser load the card
        # twice under two URLs.
        await resources.async_update_item(item["id"], {"url": url})
        _LOGGER.info("Brought the card resource up to date: %s", url)
        return

    await resources.async_create_item({"res_type": "module", "url": url})
    _LOGGER.info("Registered the card as a Lovelace resource: %s", url)


async def async_register_card(hass: HomeAssistant) -> None:
    """Serve the card and make sure it is in the Lovelace resources.

    Every path out of here says which one it took. A card that does not appear
    is diagnosed from the browser, where the only symptom is Home Assistant's
    own "custom element not found" - that cannot tell "never registered" from
    "registered and failed to load", and neither can the person reading it.
    """
    card = Path(__file__).parent / "frontend" / CARD_FILENAME
    if not await hass.async_add_executor_job(card.is_file):  # pragma: no cover
        _LOGGER.error(
            "The Lovelace card is missing at %s, so it is not available. The "
            "rest of the integration works without it",
            card,
        )
        return

    if "frontend" not in hass.config.components:
        # A headless instance has no dashboards and no use for a card. The
        # integration itself - entities, services, automations - works in full.
        _LOGGER.info(
            "The frontend integration is not set up, so the card was not registered"
        )
        return

    if not hass.data.get(_STATIC_SERVED):
        hass.data[_STATIC_SERVED] = True
        try:
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(
                        CARD_URL,
                        str(card),
                        # The version query string busts the cache; a stale card
                        # is worse than an extra request.
                        cache_headers=False,
                    )
                ]
            )
        except Exception:  # pragma: no cover - defensive
            # Leave the flag clear so a later setup can try again rather than
            # never serving the card for the rest of the run.
            hass.data[_STATIC_SERVED] = False
            _LOGGER.exception("Could not serve the Lovelace card from %s", card)
            return

    integration = await async_get_integration(hass, DOMAIN)
    await _async_reconcile_resource(hass, f"{CARD_URL}?v={integration.version}")


async def async_remove_card(hass: HomeAssistant) -> None:
    """Take the card back out of the Lovelace resources.

    Called when the last config entry goes: what setup added, removal takes
    away, so uninstalling does not leave an entry pointing at a path nothing
    serves any more. Adding an entry again registers it again, no restart
    needed.
    """
    resources, _ = _lovelace_resources(hass)
    if resources is None or not hasattr(resources, "async_delete_item"):
        return
    if getattr(resources, "loaded", True) is False:
        await resources.async_load()
        resources.loaded = True
    for item in list(resources.async_items()):
        if str(item.get("url", "")).split("?")[0] == CARD_URL:
            await resources.async_delete_item(item["id"])
            _LOGGER.debug("Removed the Lovelace resource of the card")
