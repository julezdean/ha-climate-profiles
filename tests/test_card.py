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
    "active_profile": "Custom",
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

        async def factory(
            state: dict | None = None,
            device: str = "ac",
            card: dict | None = None,
        ):
            query = {"theme": "light", "shot": "1", "device": device}
            if state:
                query["state"] = json.dumps(state)
            if card:
                query["card"] = json.dumps(card)
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
    assert "Temperature" in values
    assert "Fan mode" in values
    assert "Comfort" in await capture.locator(".capture-into").inner_text()


async def test_capturing_calls_the_service(open_card):
    page = await open_card(CHANGED)
    await page.locator("climate-profile-card .capture-into").click()
    await page.wait_for_timeout(200)

    assert await calls(page) == [
        {
            "domain": "climate_profiles",
            "service": "capture_profile",
            "data": {"entity_id": "sensor.living_room_climate_profile"},
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
                "entity_id": "sensor.living_room_climate_profile",
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
    """The "Off" profile is protected in the preview fixture."""
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
    assert "write protected" in await capture.locator(".capture-title").inner_text()


async def test_a_profile_that_stores_by_itself_asks_nothing(open_card):
    """The "Comfort+" profile captures automatically in the preview fixture."""
    page = await open_card(
        {
            **CHANGED,
            "temperature": 23,
            "last_matched_profile_id": "p4",
            "changed_values": ["temperature"],
        }
    )

    # Not the bar without its buttons: nothing at all, the way it looks once
    # the write has happened a few seconds later.
    assert await page.locator("climate-profile-card .capture").is_hidden()


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


# --- additional values -----------------------------------------------------


async def test_each_kind_gets_the_control_it_needs(open_card):
    """The card knows no value by name - only what kind its entity carries."""
    page = await open_card()
    card = page.locator("climate-profile-card")

    # A number becomes a slider, carrying the range of its own entity.
    # The label is upper-cased by the stylesheet, so compare case-insensitively.
    labels = [
        text.casefold()
        for text in await card.locator(".block .label").all_inner_texts()
    ]
    assert "fan speed" in labels
    slider = card.locator("input.slider")
    assert await slider.get_attribute("min") == "1"
    assert await slider.get_attribute("max") == "100"

    # Two switches become toggles, named by their definitions.
    assert await card.locator(".toggle .toggle-label").all_inner_texts() == [
        "Display",
        "Silent",
    ]

    # A select becomes a group of options - a kind the three fixed fields
    # could never carry.
    assert await card.get_by_role("button", name="Boost").count() == 1


async def test_hiding_a_value_leaves_it_out(open_card):
    """Everything is shown unless it is hidden, over one key space."""
    page = await open_card(card={"hide": ["silent", "swing_mode"]})
    card = page.locator("climate-profile-card")

    assert await card.locator(".toggle .toggle-label").all_inner_texts() == ["Display"]
    assert await card.get_by_role("button", name="Vertical").count() == 0


async def test_a_device_without_additional_values_shows_none(open_card):
    """A radiator thermostat has none of them, and no empty controls either."""
    page = await open_card(device="heating")
    card = page.locator("climate-profile-card")

    assert await card.locator("input.slider").count() == 0
    assert await card.locator(".toggle").count() == 0


# --- a profile that did not take --------------------------------------------

UNREACHED = {
    "temperature": 24,
    "fan_mode": "silent",
    "silent": "on",
    "active_profile": "Custom",
    "active_profile_id": "__custom__",
    "active_profile_color": "#78909c",
    "unreached": {
        "profile_id": "p6",
        "profile": "Max",
        "values": {"fan_mode": {"wanted": "full", "actual": "silent"}},
    },
}


async def test_the_unreached_hint_is_hidden_by_default(open_card):
    page = await open_card()
    assert await page.locator("climate-profile-card .unreached").is_hidden()


async def test_an_unreached_profile_is_reported_not_offered(open_card):
    """A report only: which value did not take, and no button to guess a fix."""
    page = await open_card(UNREACHED)
    hint = page.locator("climate-profile-card .unreached")

    assert await hint.is_visible()
    assert await hint.locator(".unreached-title").inner_text() == "Max not reached"
    assert (
        await hint.locator(".unreached-values").inner_text()
        == "Fan mode: Silent instead of Full"
    )
    assert await hint.locator("button").count() == 0


async def test_the_offer_can_be_dismissed(open_card):
    """A minute is long: the x says "not this time" right away."""
    page = await open_card(CHANGED)
    card = page.locator("climate-profile-card")

    await card.locator(".capture-dismiss").click()

    assert [call["service"] for call in await calls(page)] == ["dismiss_change"]


# --- what the room reports --------------------------------------------------


async def test_the_humidity_is_shown_next_to_the_temperature(open_card):
    """A thermostat card shows it, and the attribute was there all along."""
    page = await open_card()

    ambient = await page.locator("climate-profile-card .ambient").inner_text()
    assert "25.4 °C" in ambient
    assert "54 %" in ambient


async def test_a_device_without_a_humidity_sensor_shows_no_percent(open_card):
    page = await open_card(device="heating")

    ambient = await page.locator("climate-profile-card .ambient").inner_text()
    assert "%" not in ambient
    assert "20.2 °C" in ambient


# --- the visual editor ------------------------------------------------------

EDITOR_VALUES = """
const card = document.querySelector('climate-profile-card');
const editor = document.createElement('climate-profile-card-editor');
editor.hass = card._hass;
editor.setConfig({ type: 'custom:climate-profile-card', entity: card._config.entity });
return editor._values().map(([key]) => key);
"""


async def test_the_editor_offers_what_the_device_has(open_card):
    page = await open_card()

    keys = await page.evaluate(f"(() => {{{EDITOR_VALUES}}})()")
    assert keys == [
        "temperature",
        "hvac_mode",
        "fan_mode",
        "swing_mode",
        "fan",
        "display",
        "silent",
        "preset",
    ]


async def test_the_editor_leaves_out_what_the_device_cannot_do(open_card):
    """A radiator has no fan and no swing - a switch for them hides nothing."""
    page = await open_card(device="heating")

    keys = await page.evaluate(f"(() => {{{EDITOR_VALUES}}})()")
    assert keys == ["temperature", "hvac_mode"]


async def test_hiding_the_temperature_takes_it_out(open_card):
    """It kept its own `show_temperature`, so the editor's switch did nothing."""
    page = await open_card(card={"hide": ["temperature"]})

    assert await page.locator("climate-profile-card .temp").is_hidden()


KEEPS_HIDDEN = """
const card = document.querySelector('climate-profile-card');
const editor = document.createElement('climate-profile-card-editor');
editor.hass = card._hass;
editor.setConfig({
  type: 'custom:climate-profile-card',
  entity: card._config.entity,
  hide: ['fan_mode'],
});
let out = null;
editor.addEventListener('config-changed', (event) => { out = event.detail.config; });
editor._form.dispatchEvent(
  new CustomEvent('value-changed', { detail: { value: editor._data() } })
);
return out.hide || [];
"""


async def test_the_editor_keeps_a_decision_about_a_value_it_cannot_show(open_card):
    """A radiator shows no fan switch - and must not drop what was set for it."""
    page = await open_card(device="heating")

    assert await page.evaluate(f"(() => {{{KEEPS_HIDDEN}}})()") == ["fan_mode"]


# --- the temperature control ------------------------------------------------


async def test_the_bar_is_what_a_card_gets_without_asking(open_card):
    page = await open_card()
    card = page.locator("climate-profile-card")

    assert await card.locator(".meter").count() == 1
    assert await card.locator(".ring").count() == 0


async def test_the_dial_replaces_the_bar_and_keeps_the_steps(open_card):
    page = await open_card(card={"temperature_style": "dial"})
    card = page.locator("climate-profile-card")

    assert await card.locator(".meter").count() == 0
    assert await card.locator(".arc").is_visible()
    # Dragging a ring rarely lands on the half degree somebody meant.
    assert await card.locator(".ring-steps .step").count() == 2
    # The readings sit in the middle, the way a thermostat card shows them.
    assert "25.4 °C" in await card.locator(".ring-current").inner_text()
    assert "54 %" in await card.locator(".ring-humidity").inner_text()
    assert await card.locator(".ring-action").inner_text() == "Cooling"


async def test_a_reading_the_device_does_not_have_leaves_no_empty_row(open_card):
    page = await open_card(device="heating", card={"temperature_style": "dial"})
    card = page.locator("climate-profile-card")

    assert await card.locator(".ring-current").is_visible()
    assert await card.locator(".ring-humidity").is_hidden()


async def test_turning_the_dial_sets_the_temperature(open_card):
    """The top of the arc is the middle of the range: 16 to 30 makes 23."""
    page = await open_card(card={"temperature_style": "dial"})
    arc = page.locator("climate-profile-card .arc")
    box = await arc.bounding_box()

    await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + 4)
    # The card coalesces a drag into one call after 600 ms.
    await page.wait_for_timeout(800)

    assert await calls(page) == [
        {
            "domain": "climate_profiles",
            "service": "set_value",
            "data": {
                "entity_id": "sensor.living_room_climate_profile",
                "temperature": 23,
            },
        }
    ]


async def test_the_dial_can_be_moved_from_the_keyboard(open_card):
    page = await open_card(card={"temperature_style": "dial"})
    arc = page.locator("climate-profile-card .arc")

    await arc.focus()
    await arc.press("ArrowUp")
    await page.wait_for_timeout(800)

    assert (await calls(page))[0]["data"]["temperature"] == 25


# --- the profile layouts ----------------------------------------------------


async def test_the_profiles_can_be_a_dropdown(open_card):
    page = await open_card(card={"profile_layout": "dropdown"})
    card = page.locator("climate-profile-card")

    assert await card.locator(".profile").count() == 0, "no buttons"
    trigger = card.locator(".picker-trigger")
    assert "Comfort" in await trigger.inner_text()
    assert await card.locator(".picker-list").is_hidden()

    await trigger.click()

    options = card.locator(".picker-option")
    assert await options.locator(".picker-option-name").all_inner_texts() == [
        "Off",
        "Away",
        "Comfort",
        "Comfort+",
        "Night",
        "Max",
    ]
    # What a profile is recognised by comes along: an icon where there is one,
    # the profile's colour as a dot where there is not. (The second icon of a
    # row is the check mark of the active one.)
    assert (
        await options.nth(0).locator("ha-icon").first.get_attribute("icon")
        == "mdi:power"
    )
    assert await options.nth(1).locator(".dot-mark").count() == 1
    assert await options.nth(2).get_attribute("aria-selected") == "true"


async def test_picking_from_the_dropdown_applies_the_profile(open_card):
    page = await open_card(card={"profile_layout": "dropdown"})
    card = page.locator("climate-profile-card")

    await card.locator(".picker-trigger").click()
    await card.get_by_role("option", name="Night").click()
    await page.wait_for_timeout(200)

    assert await calls(page) == [
        {
            "domain": "climate_profiles",
            "service": "apply_profile",
            "data": {
                "entity_id": "sensor.living_room_climate_profile",
                "profile": "p5",
            },
        }
    ]
    assert await card.locator(".picker-list").is_hidden(), "and it closes again"


async def test_the_list_closes_on_escape(open_card):
    page = await open_card(card={"profile_layout": "dropdown"})
    card = page.locator("climate-profile-card")

    await card.locator(".picker-trigger").click()
    assert await card.locator(".picker-list").is_visible()
    await page.keyboard.press("Escape")

    assert await card.locator(".picker-list").is_hidden()


async def test_custom_joins_the_dropdown_while_it_is_what_is_on(open_card):
    """It has to be shown somewhere - but it still cannot be chosen."""
    page = await open_card(CHANGED, card={"profile_layout": "dropdown"})
    card = page.locator("climate-profile-card")

    assert "Custom" in await card.locator(".picker-trigger").inner_text()
    await card.locator(".picker-trigger").click()

    custom = card.locator(".picker-option[data-id='__custom__']")
    assert await custom.is_disabled()
    assert await custom.get_attribute("aria-selected") == "true"
