"""Tests for serving the Lovelace card.

The card ships inside the integration and registers itself, so there are two
ways to get it wrong: not shipping it, and leaving a browser with last week's
card against this week's attributes. The resource list is what the frontend
reads at runtime, which is why the card goes there and not into a script tag.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from homeassistant.components.lovelace import LovelaceData
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.components.lovelace.resources import (
    RESOURCE_STORAGE_KEY,
    ResourceStorageCollection,
    ResourceYAMLCollection,
)
from homeassistant.core import HomeAssistant

from custom_components.climate_profiles import frontend

CARD = (
    Path(__file__).parent.parent
    / "custom_components"
    / "climate_profiles"
    / "frontend"
    / frontend.CARD_FILENAME
)


class _Http:
    """Stand-in for ``hass.http``, which a bare test instance has not got."""

    def __init__(self) -> None:
        self.paths: list[Any] = []

    async def async_register_static_paths(self, configs: list[Any]) -> None:
        self.paths.extend(configs)


@pytest.fixture
def served(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> _Http:
    """Pretend this instance serves a frontend, and record what is registered."""
    hass.config.components.add("frontend")
    http = _Http()
    monkeypatch.setattr(hass, "http", http, raising=False)
    return http


@pytest.fixture
def lovelace(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> ResourceStorageCollection:
    """Return a real Lovelace resource collection, backed by an empty store."""
    hass_storage[RESOURCE_STORAGE_KEY] = {
        "version": 1,
        "key": RESOURCE_STORAGE_KEY,
        "data": {"items": []},
    }
    collection = ResourceStorageCollection(hass, None)
    hass.data[LOVELACE_DATA] = LovelaceData(
        resource_mode="storage",
        dashboards={},
        resources=collection,
        yaml_dashboards={},
    )
    return collection


def _urls(collection: ResourceStorageCollection) -> list[str]:
    return [item["url"] for item in collection.async_items()]


def test_the_card_is_shipped() -> None:
    """A release without the card would install an integration with no card."""
    assert CARD.is_file()


async def test_registers_the_card_as_a_resource(
    hass: HomeAssistant, served: _Http, lovelace: ResourceStorageCollection
) -> None:
    await frontend.async_register_card(hass)

    urls = _urls(lovelace)
    assert len(urls) == 1
    assert urls[0].startswith(frontend.CARD_URL)
    assert [item["type"] for item in lovelace.async_items()] == ["module"]


async def test_the_url_carries_the_version(
    hass: HomeAssistant, served: _Http, lovelace: ResourceStorageCollection
) -> None:
    """Without it a browser keeps the cached card after an update."""
    await frontend.async_register_card(hass)

    assert _urls(lovelace)[0].endswith("?v=2.0.0-beta.2")


async def test_serves_the_card_over_http(
    hass: HomeAssistant, served: _Http, lovelace: ResourceStorageCollection
) -> None:
    await frontend.async_register_card(hass)

    assert len(served.paths) == 1
    assert served.paths[0].url_path == frontend.CARD_URL
    # A stale card is worse than an extra request.
    assert served.paths[0].cache_headers is False


async def test_serves_the_static_path_only_once(
    hass: HomeAssistant, served: _Http, lovelace: ResourceStorageCollection
) -> None:
    """Every entry reconciles the resource; the route is registered once."""
    await frontend.async_register_card(hass)
    await frontend.async_register_card(hass)

    assert len(served.paths) == 1
    assert len(_urls(lovelace)) == 1


async def test_updates_an_entry_from_an_older_version(
    hass: HomeAssistant, served: _Http, lovelace: ResourceStorageCollection
) -> None:
    """A second entry per release would define the element twice."""
    await lovelace.async_create_item(
        {"res_type": "module", "url": f"{frontend.CARD_URL}?v=0.9.0"}
    )

    await frontend.async_register_card(hass)

    urls = _urls(lovelace)
    assert len(urls) == 1
    assert urls[0].endswith("?v=2.0.0-beta.2")


async def test_leaves_other_resources_alone(
    hass: HomeAssistant, served: _Http, lovelace: ResourceStorageCollection
) -> None:
    await lovelace.async_create_item(
        {"res_type": "module", "url": "/local/somebody-elses-card.js"}
    )

    await frontend.async_register_card(hass)

    assert "/local/somebody-elses-card.js" in _urls(lovelace)
    assert len(_urls(lovelace)) == 2


async def test_says_what_to_add_when_lovelace_is_in_yaml_mode(
    hass: HomeAssistant,
    served: _Http,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """That list is the user's file. Saying so beats failing quietly."""
    hass.data[LOVELACE_DATA] = LovelaceData(
        resource_mode="yaml",
        dashboards={},
        resources=ResourceYAMLCollection([]),
        yaml_dashboards={},
    )

    await frontend.async_register_card(hass)

    assert "YAML mode" in caplog.text
    assert frontend.CARD_URL in caplog.text


async def test_says_so_when_lovelace_is_not_there(
    hass: HomeAssistant, served: _Http, caplog: pytest.LogCaptureFixture
) -> None:
    hass.data.pop(LOVELACE_DATA, None)

    await frontend.async_register_card(hass)

    assert frontend.CARD_URL in caplog.text


async def test_leaves_a_headless_instance_alone(
    hass: HomeAssistant, lovelace: ResourceStorageCollection
) -> None:
    """No dashboards, no use for a card - and no warning worth the noise."""
    assert "frontend" not in hass.config.components

    await frontend.async_register_card(hass)

    assert _urls(lovelace) == []


async def test_removing_takes_the_resource_back_out(
    hass: HomeAssistant, served: _Http, lovelace: ResourceStorageCollection
) -> None:
    """A resource pointing at nothing looks exactly like a broken card."""
    await frontend.async_register_card(hass)
    assert len(_urls(lovelace)) == 1

    await frontend.async_remove_card(hass)

    assert _urls(lovelace) == []


async def test_registering_again_after_a_removal(
    hass: HomeAssistant, served: _Http, lovelace: ResourceStorageCollection
) -> None:
    """async_setup does not run twice, so the resource has to come back here."""
    await frontend.async_register_card(hass)
    await frontend.async_remove_card(hass)

    await frontend.async_register_card(hass)

    assert len(_urls(lovelace)) == 1
