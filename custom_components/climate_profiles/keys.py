"""Forming the readable key of an additional value.

Here rather than in ``models``, because it reads the registries and slugifies
the way Home Assistant does - and ``models`` imports nothing from it.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .models import unique_key


def value_key(
    hass: HomeAssistant, entity_id: str, name: str, taken: set[str] | frozenset[str]
) -> str:
    """Return a key for a value called ``name``, backed by ``entity_id``.

    A name pre-filled from the entity is its friendly name, and that starts
    with the device's: "Better Thermostat Bad Heizung Kindersicherung". The
    key is what a card's ``hide`` takes, so the device part is left out of it -
    the value belongs to this entry's device anyway. A name the user typed
    rarely starts with the device's, and stays whole.
    """
    return unique_key(slugify(_without_device(hass, entity_id, name)), taken)


def _without_device(hass: HomeAssistant, entity_id: str, name: str) -> str:
    """Return ``name`` without the name of the entity's device in front."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None or entry.device_id is None:
        return name
    device = dr.async_get(hass).async_get(entry.device_id)
    if device is None:
        return name
    for prefix in (device.name_by_user, device.name):
        if not prefix:
            continue
        rest = name[len(prefix) :].strip()
        if name.casefold().startswith(prefix.casefold()) and rest:
            return rest
    return name
