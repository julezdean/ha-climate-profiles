"""Stores shared by every entry of the integration.

The selection and automatic mode live in one file each, keyed by entry. Each
coordinator reading the file, changing its own key and writing it back loses
updates as soon as two entries do that at once - a sensor switching every room
to the same profile is exactly that case, and the room whose write came first
woke up after a restart with a profile it had long left.

So the file is read once and held in memory, every entry changes that one
dict, and writing it is only ever a copy of what is there.
"""

from __future__ import annotations

import asyncio
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN

#: Short enough that a crash right after a change rarely loses it, long enough
#: for several rooms switching at once to end up in one write. Home Assistant
#: writes whatever is pending when it stops.
SAVE_DELAY: float = 1.0

_DATA_KEY = f"{DOMAIN}_shared_stores"


class SharedStore:
    """One storage file, one dict in memory, one key per entry."""

    def __init__(self, hass: HomeAssistant, version: int, key: str) -> None:
        """Wrap the store; nothing is read until :meth:`async_load`."""
        self._store: Store[dict[str, Any]] = Store(hass, version, key)
        self._data: dict[str, Any] = {}
        self._loaded = False
        self._lock = asyncio.Lock()

    async def async_load(self) -> None:
        """Read the file, once - every later call finds it in memory."""
        async with self._lock:
            if self._loaded:
                return
            self._data = dict(await self._store.async_load() or {})
            self._loaded = True

    @callback
    def get(self, entry_id: str) -> Any:
        """Return what is kept for ``entry_id``, ``None`` without anything."""
        return self._data.get(entry_id)

    @callback
    def set(self, entry_id: str, value: Any) -> None:
        """Keep ``value`` for ``entry_id``; ``None`` forgets the key."""
        if value is None:
            if self._data.pop(entry_id, None) is None:
                return
        else:
            self._data[entry_id] = value
        self._store.async_delay_save(lambda: dict(self._data), SAVE_DELAY)


async def async_get_shared_store(
    hass: HomeAssistant, version: int, key: str
) -> SharedStore:
    """Return the loaded store for ``key``, the same one for every entry."""
    stores: dict[str, SharedStore] = hass.data.setdefault(_DATA_KEY, {})
    if (store := stores.get(key)) is None:
        store = stores[key] = SharedStore(hass, version, key)
    await store.async_load()
    return store


@callback
def forget_shared_stores(hass: HomeAssistant) -> None:
    """Drop the stores from memory, so the next entry reads the files again."""
    hass.data.pop(_DATA_KEY, None)
