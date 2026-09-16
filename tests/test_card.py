"""Tests for the Lovelace card, driven in a real browser.

The card is the one part no Python test reaches, and it is where a wrong
selector - or a `display` beating a `hidden` attribute - hides for months.
These tests render the actual shipped file through tools/card-preview.html.

Skipped when Playwright is not installed; see docs/screenshots.md.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path

import pytest

async_playwright = pytest.importorskip(
    "playwright.async_api", reason="playwright is not installed"
).async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.make_screenshots import launch_options, serve  # noqa: E402

PORT = 8721

#: Replaces callService so a click records instead of talking to anything.
RECORDER = """
window.__calls = [];
const card = document.querySelector('climate-profile-card');
const hass = card._hass;
hass.callService = async (domain, service, data) => {
  window.__calls.push({ domain, service, data });
};
card.hass = hass;
"""

CHANGED = {
    "temperature": 23,
    "fan_mode": "high",
    "active_profile": "Benutzerdefiniert",
    "active_profile_id": "__custom__",
    "active_profile_color": "#78909c",
    "changed_values": ["temperature", "fan_mode"],
    "last_matched_profile_id": "p3",
}


@pytest.fixture(autouse=True)
def _allow_sockets():
    """Let Playwright talk to the browser.

    pytest-socket blocks sockets for every test and re-arms before each one,
    so the permission has to be granted per test.
    """
    import pytest_socket

    pytest_socket.enable_socket()
    yield


@pytest.fixture(scope="module")
def base_url():
    """Serve the repository. Plain threads, no event loop involved."""
    import pytest_socket

    pytest_socket.enable_socket()
    with serve(ROOT, PORT) as url:
        yield url


@pytest.fixture
async def open_card(base_url):
    """Return a factory that opens the preview and records service calls."""
    pages = []

    async with async_playwright() as play:
        browser = await play.chromium.launch(**launch_options())

        async def factory(state: dict | None = None, device: str = "ac"):
            query = {"theme": "light", "shot": "1", "device": device}
            if state:
                query["state"] = json.dumps(state)
            page = await browser.new_page(viewport={"width": 460, "height": 1200})
            await page.goto(
                f"{base_url}/tools/card-preview.html?{urllib.parse.urlencode(query)}"
            )
            await page.wait_for_selector("climate-profile-card")
            await page.evaluate(RECORDER)
            pages.append(page)
            return page

        yield factory
        await browser.close()


async def calls(page) -> list[dict]:
    """Return the service calls the card made."""
    return await page.evaluate("window.__calls")


# --- the capture bar -------------------------------------------------------


async def test_the_capture_bar_stays_hidden_without_changes(open_card):
    page = await open_card()
    assert await page.locator("climate-profile-card .capture").is_hidden()


async def test_the_capture_bar_names_what_changed(open_card):
    page = await open_card(CHANGED)
    capture = page.locator("climate-profile-card .capture")
    assert await capture.is_visible()

    values = await capture.locator(".capture-values").inner_text()
    assert "Temperatur" in values
    assert "Lüftermodus" in values
    assert "Komfort" in await capture.locator(".capture-into").inner_text()


async def test_capturing_calls_the_service(open_card):
    page = await open_card(CHANGED)
    await page.locator("climate-profile-card .capture-into").click()
    await page.wait_for_timeout(200)

    assert await calls(page) == [
        {
            "domain": "climate_profiles",
            "service": "capture_profile",
            "data": {"entity_id": "sensor.wohnzimmer_klimaprofil"},
        }
    ]


async def test_saving_as_a_new_profile_asks_for_a_name(open_card):
    page = await open_card(CHANGED)
    await page.locator("climate-profile-card .capture-new").click()

    assert await page.locator("climate-profile-card .capture-form").is_visible()
    assert await page.locator("climate-profile-card .capture-actions").is_hidden()
    assert await calls(page) == [], "nothing is saved before a name is given"

    await page.locator("climate-profile-card .capture-name").fill("Mittagshitze")
    await page.locator("climate-profile-card .capture-name").press("Enter")
    await page.wait_for_timeout(200)

    assert await calls(page) == [
        {
            "domain": "climate_profiles",
            "service": "save_as_profile",
            "data": {
                "entity_id": "sensor.wohnzimmer_klimaprofil",
                "name": "Mittagshitze",
            },
        }
    ]


async def test_an_empty_name_is_refused_without_a_service_call(open_card):
    page = await open_card(CHANGED)
    await page.locator("climate-profile-card .capture-new").click()
    await page.locator("climate-profile-card .capture-name").fill("   ")
    await page.locator("climate-profile-card .capture-name").press("Enter")
    await page.wait_for_timeout(200)

    assert await calls(page) == []
    assert await page.locator("climate-profile-card .alert").is_visible()


async def test_escape_closes_the_name_field(open_card):
    page = await open_card(CHANGED)
    await page.locator("climate-profile-card .capture-new").click()
    await page.locator("climate-profile-card .capture-name").press("Escape")

    assert await page.locator("climate-profile-card .capture-form").is_hidden()
    assert await page.locator("climate-profile-card .capture-actions").is_visible()


async def test_a_protected_profile_offers_only_the_new_profile_route(open_card):
    """The "Aus" profile is protected in the preview fixture."""
    page = await open_card(
        {
            **CHANGED,
            "hvac_mode": "off",
            "last_matched_profile_id": "p1",
            "changed_values": ["temperature"],
        }
    )
    capture = page.locator("climate-profile-card .capture")
    assert await capture.is_visible()
    assert await capture.locator(".capture-into").is_hidden()
    assert await capture.locator(".capture-new").is_visible()
    assert "schreibgeschützt" in await capture.locator(".capture-title").inner_text()


# --- regressions -----------------------------------------------------------


async def test_the_error_bar_is_hidden_by_default(open_card):
    """`display: flex` used to beat the `hidden` attribute and show it empty."""
    page = await open_card()
    assert await page.locator("climate-profile-card .alert").is_hidden()


async def test_a_thermostat_hides_what_it_cannot_do(open_card):
    page = await open_card(device="heating")
    card = page.locator("climate-profile-card")
    assert await card.locator(".chips").count() == 0, "no fan or swing chips"
    assert await card.locator(".slider").count() == 0, "no fan slider"
    assert await card.locator(".toggle").count() == 0, "no display/silent toggles"
    assert await card.locator(".segmented").is_visible(), "but the modes are there"
