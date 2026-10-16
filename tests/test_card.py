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

#: Changed by hand, so nothing matches any more.
CHANGED = {
    "temperature": 23,
    "fan_mode": "high",
    "active_profile": "Custom",
    "active_profile_id": "__custom__",
    "active_profile_color": "#78909c",
}

#: The fixture's "Off" is write protected and active here.
OFF = {
    "hvac_mode": "off",
    "active_profile": "Off",
    "active_profile_id": "p1",
    "active_profile_color": "#64748b",
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


# --- write protection -------------------------------------------------------


async def test_a_change_by_hand_offers_nothing(open_card):
    """Changes are stored by the profile itself, or not at all - never asked."""
    page = await open_card(CHANGED)
    card = page.locator("climate-profile-card")
    assert await card.locator(".capture").count() == 0
    assert await card.locator("input[type=text]").count() == 0, "no name field"


async def test_the_lock_is_left_out_unless_asked_for(open_card):
    page = await open_card()
    assert await page.locator("climate-profile-card .lock").is_hidden()


async def test_the_lock_shows_whether_the_active_profile_is_protected(open_card):
    page = await open_card(card={"show_protection": True})
    lock = page.locator("climate-profile-card .lock")
    assert await lock.is_visible()
    assert await lock.get_attribute("aria-pressed") == "false"
    assert await lock.get_attribute("title") == "Comfort takes changes made by hand"

    await page.evaluate(f"setCardState({json.dumps(OFF)})")
    assert await lock.get_attribute("aria-pressed") == "true"
    assert await lock.get_attribute("title") == "Off is write protected"


async def test_the_lock_flips_the_profiles_switch(open_card):
    page = await open_card(card={"show_protection": True})
    await page.locator("climate-profile-card .lock").click()
    await page.wait_for_timeout(200)

    assert await calls(page) == [
        {
            "domain": "switch",
            "service": "turn_on",
            "data": {"entity_id": "switch.living_room_comfort_write_protected"},
        }
    ]


async def test_the_lock_opens_a_protected_profile(open_card):
    page = await open_card(OFF, card={"show_protection": True})
    await page.locator("climate-profile-card .lock").click()
    await page.wait_for_timeout(200)

    assert await calls(page) == [
        {
            "domain": "switch",
            "service": "turn_off",
            "data": {"entity_id": "switch.living_room_off_write_protected"},
        }
    ]


async def test_custom_has_no_lock(open_card):
    """Custom stores nothing, so there is nothing to protect."""
    page = await open_card(CHANGED, card={"show_protection": True})
    assert await page.locator("climate-profile-card .lock").is_hidden()


async def test_the_editor_offers_the_lock(open_card):
    page = await open_card()
    labels = await page.evaluate(
        """() => {
            const editor = document.createElement("climate-profile-card-editor");
            editor.hass = document.querySelector("climate-profile-card")._hass;
            editor.setConfig({ entity: "sensor.living_room_climate_profile" });
            return editor._schema().map((field) => field.name);
        }"""
    )
    assert "show_protection" in labels


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


async def test_the_open_list_stays_inside_the_card(open_card):
    """Floating above the card left it cut off wherever something clips it."""
    page = await open_card(card={"profile_layout": "dropdown"})
    card = page.locator("climate-profile-card")

    before = (await card.bounding_box())["height"]
    await card.locator(".picker-trigger").click()
    after = await card.bounding_box()
    list_box = await card.locator(".picker-list").bounding_box()

    # The card grows by the list instead of the list hanging over its edge.
    assert after["height"] > before
    assert list_box["y"] + list_box["height"] <= after["y"] + after["height"]


async def test_the_profiles_can_be_icons_only(open_card):
    page = await open_card(card={"profile_layout": "icons"})
    card = page.locator("climate-profile-card")

    buttons = card.locator(".profile")
    # Six profiles, no "Custom" box - it joins only while it is what is on.
    assert await buttons.count() == 6
    assert await buttons.locator(".profile-name").count() == 0
    # The name is what names the button instead.
    assert await buttons.nth(5).get_attribute("aria-label") == "Max"
    assert await buttons.nth(5).get_attribute("title") == "Max"
    # A profile without an icon keeps its colour as a dot.
    assert await buttons.nth(1).locator(".dot-mark").count() == 1
    active = card.locator(".profile.active")
    assert await active.get_attribute("data-id") == "p3"
    # The filled button says which one is on; a check mark would sit on top of
    # the icon, and aria-pressed carries it where nothing is seen.
    assert await active.locator(".check").is_hidden()
    assert await active.get_attribute("aria-pressed") == "true"


async def test_an_icon_button_applies_its_profile(open_card):
    page = await open_card(card={"profile_layout": "icons"})

    await page.locator("climate-profile-card .profile[data-id='p5']").click()
    await page.wait_for_timeout(200)

    assert (await calls(page))[0]["data"]["profile"] == "p5"


async def test_custom_joins_the_icons_while_it_is_what_is_on(open_card):
    page = await open_card(CHANGED, card={"profile_layout": "icons"})
    card = page.locator("climate-profile-card")

    custom = card.locator(".profile[data-id='__custom__']")
    assert await custom.count() == 1
    assert await custom.is_disabled()
    assert "active" in (await custom.get_attribute("class"))


async def test_custom_joins_when_it_becomes_what_is_on(open_card):
    """Not only when the card is built: the list follows the device.

    Custom used to be in the list only if it was active when the card was
    built - a manual change afterwards left the icons without an active one.
    """
    for layout, selector in (
        ("icons", ".profile[data-id='__custom__']"),
        ("dropdown", ".picker-option[data-id='__custom__']"),
    ):
        page = await open_card(card={"profile_layout": layout})
        custom = page.locator(f"climate-profile-card {selector}")
        assert await custom.count() == 0

        await page.evaluate(f"setCardState({json.dumps(CHANGED)})")
        await page.wait_for_timeout(100)
        assert await custom.count() == 1, layout

        await page.evaluate("setCardState({})")
        await page.wait_for_timeout(100)
        assert await custom.count() == 0, layout


# --- profiles hidden from the card ------------------------------------------

#: The fixture's "Summer" is hidden from the card and active here.
SUMMER = {
    "temperature": 25,
    "silent": "on",
    "active_profile": "Summer",
    "active_profile_id": "p7",
    "active_profile_color": "#f59e0b",
}


@pytest.mark.parametrize(
    ("layout", "selector"),
    [
        ("grid", ".profile"),
        ("scroll", ".profile"),
        ("icons", ".profile"),
        ("dropdown", ".picker-option"),
    ],
)
async def test_a_hidden_profile_is_not_offered(open_card, layout, selector):
    page = await open_card(card={"profile_layout": layout})
    card = page.locator("climate-profile-card")

    assert await card.locator(f"{selector}[data-id='p7']").count() == 0
    # The six others are all still there.
    for profile_id in ("p1", "p2", "p3", "p4", "p5", "p6"):
        assert await card.locator(f"{selector}[data-id='{profile_id}']").count() == 1


@pytest.mark.parametrize(
    ("layout", "selector"),
    [
        ("grid", ".profile"),
        ("scroll", ".profile"),
        ("icons", ".profile"),
        ("dropdown", ".picker-option"),
    ],
)
async def test_a_hidden_profile_is_not_shown_while_it_is_on(
    open_card, layout, selector
):
    """Hidden is hidden: nothing on the card is marked active, not even custom."""
    page = await open_card(SUMMER, card={"profile_layout": layout})
    card = page.locator("climate-profile-card")

    assert await card.locator(f"{selector}[data-id='p7']").count() == 0
    assert await card.locator(f"{selector}.active").count() == 0
    if layout == "dropdown":
        trigger = card.locator(".picker-trigger")
        assert await trigger.locator(".picker-name").inner_text() == "Profiles"
        assert await trigger.locator(".picker-mark").is_hidden()


async def test_a_hidden_profile_stays_away_as_the_state_changes(open_card):
    page = await open_card()
    card = page.locator("climate-profile-card")

    await page.evaluate(f"setCardState({json.dumps(SUMMER)})")
    await page.wait_for_timeout(100)
    assert await card.locator(".profile[data-id='p7']").count() == 0
    assert await card.locator(".profile.active").count() == 0

    await page.evaluate("setCardState({})")
    await page.wait_for_timeout(100)
    assert await card.locator(".profile.active").count() == 1


@pytest.mark.parametrize("card", [{}, {"profile_layout": "auto"}])
async def test_without_a_layout_the_profiles_are_a_grid(open_card, card):
    """There is no "auto" any more: it jumped as automatic mode came and went."""
    page = await open_card(card=card)
    layout = await page.locator("climate-profile-card .profiles").get_attribute(
        "data-layout"
    )
    assert layout == "grid"


# --- automatic mode -----------------------------------------------------------

#: Automatic mode on, the sensor names "Comfort", which is what is on.
AUTOMATIC = {
    "automatic": {
        "status": "following",
        "sensor": "sensor.wanted_profile",
        "sensor_state": "Comfort",
        "target": "Comfort",
        "target_id": "p3",
        "problem": None,
        "temporary": None,
    }
}

#: The temporary "Night" runs for another 24 minutes; the sensor still says
#: "Comfort", which takes over afterwards.
RUNNING = {
    "active_profile": "Night",
    "active_profile_id": "p5",
    "active_profile_color": "#8b5cf6",
    "automatic": {
        **AUTOMATIC["automatic"],
        "status": "temporary",
        "temporary": {"profile": "Night", "profile_id": "p5", "until": "+1452"},
    },
}


def automatic_state(**changes) -> dict:
    """Return ``AUTOMATIC`` with some of its ``automatic`` fields changed."""
    return {"automatic": {**AUTOMATIC["automatic"], **changes}}


async def test_the_automatic_switch_is_left_out_unless_asked_for(open_card):
    page = await open_card(AUTOMATIC)
    assert await page.locator("climate-profile-card .auto").is_hidden()


async def test_without_a_profile_sensor_there_is_no_switch(open_card):
    page = await open_card(card={"show_automatic": True})
    assert await page.locator("climate-profile-card .auto").is_hidden()


@pytest.mark.parametrize(
    ("status", "pressed", "waiting"),
    [("off", "false", False), ("following", "true", False), ("waiting", "true", True)],
)
async def test_the_automatic_switch_shows_its_state(
    open_card, status, pressed, waiting
):
    page = await open_card(
        automatic_state(status=status), card={"show_automatic": True}
    )
    button = page.locator("climate-profile-card .auto")
    assert await button.is_visible()
    assert await button.get_attribute("aria-pressed") == pressed
    assert ("waiting" in (await button.get_attribute("class"))) is waiting


@pytest.mark.parametrize(
    ("status", "service"), [("off", "turn_on"), ("on", "turn_off")]
)
async def test_the_automatic_switch_flips_the_devices_switch(
    open_card, status, service
):
    page = await open_card(
        automatic_state(status="off" if status == "off" else "following"),
        card={"show_automatic": True},
    )
    await page.locator("climate-profile-card .auto").click()
    assert await calls(page) == [
        {
            "domain": "switch",
            "service": service,
            "data": {"entity_id": "switch.living_room_automatic_mode"},
        }
    ]


async def test_the_target_is_shown_by_default(open_card):
    page = await open_card(AUTOMATIC)
    target = page.locator("climate-profile-card .target")
    assert await target.is_visible()
    assert await target.locator(".target-name").inner_text() == "Comfort"
    assert "problem" not in (await target.get_attribute("class"))


async def test_the_target_is_only_the_profile(open_card):
    """No "Target" label and no target icon: the profile's mark and name."""
    page = await open_card(AUTOMATIC)
    target = page.locator("climate-profile-card .target")
    assert (await target.inner_text()).strip() == "Comfort"
    assert await target.locator("ha-icon[icon='mdi:target']").count() == 0


async def test_the_target_is_left_out_while_automatic_mode_is_off(open_card):
    page = await open_card(automatic_state(status="off"))
    assert await page.locator("climate-profile-card .target").is_hidden()


async def test_the_target_can_be_switched_off(open_card):
    page = await open_card(AUTOMATIC, card={"show_target": False})
    assert await page.locator("climate-profile-card .target").is_hidden()


async def test_without_a_profile_sensor_there_is_no_target(open_card):
    page = await open_card()
    assert await page.locator("climate-profile-card .target").is_hidden()


@pytest.mark.parametrize(
    ("problem", "sensor_state", "text"),
    [
        ("unknown_profile", "Komfort", 'No profile "Komfort"'),
        ("sensor_unavailable", "unavailable", "Sensor unavailable"),
    ],
)
async def test_the_target_says_why_there_is_none(
    open_card, problem, sensor_state, text
):
    page = await open_card(
        automatic_state(
            status="waiting",
            target=None,
            target_id=None,
            problem=problem,
            sensor_state=sensor_state,
        )
    )
    target = page.locator("climate-profile-card .target")
    assert await target.locator(".target-name").inner_text() == text
    assert "problem" in (await target.get_attribute("class"))


@pytest.mark.parametrize("layout", ["grid", "scroll", "icons"])
async def test_automatic_mode_offers_only_temporary_profiles(open_card, layout):
    page = await open_card(AUTOMATIC, card={"profile_layout": layout})
    card = page.locator("climate-profile-card")

    for profile_id in ("p5", "p6"):
        button = card.locator(f".profile[data-id='{profile_id}']")
        assert await button.is_enabled(), profile_id
    # What automatic mode chose is not in the list either, though it is on.
    for profile_id in ("p1", "p2", "p3", "p4", "p7", "__custom__"):
        assert await card.locator(f".profile[data-id='{profile_id}']").count() == 0
    assert await card.locator(".profile.active").count() == 0


async def test_automatic_mode_offers_only_temporary_profiles_in_the_list(open_card):
    page = await open_card(AUTOMATIC, card={"profile_layout": "dropdown"})
    card = page.locator("climate-profile-card")
    await card.locator(".picker-trigger").click()

    listed = card.locator(".picker-option")
    assert [await item.get_attribute("data-id") for item in await listed.all()] == [
        "p5",
        "p6",
    ]
    assert await listed.locator(":disabled").count() == 0
    # The closed list is not named after what automatic mode chose.
    trigger = card.locator(".picker-trigger")
    assert await trigger.locator(".picker-name").inner_text() == "Profiles"


@pytest.mark.parametrize("layout", ["grid", "icons", "dropdown"])
async def test_automatic_mode_does_not_list_custom(open_card, layout):
    state = {
        **AUTOMATIC,
        "active_profile": "Custom",
        "active_profile_id": "__custom__",
        "active_profile_color": "#78909c",
    }
    page = await open_card(state, card={"profile_layout": layout})
    card = page.locator("climate-profile-card")
    assert await card.locator("[data-id='__custom__']").count() == 0


@pytest.mark.parametrize("layout", ["grid", "scroll", "icons", "dropdown"])
async def test_without_temporary_profiles_automatic_mode_lists_nothing(
    open_card, layout
):
    """No empty box where the profiles were."""
    page = await open_card(
        automatic_state(target="Comfort", target_id="h3"),
        device="heating",
        card={"profile_layout": layout},
    )
    card = page.locator("climate-profile-card")
    assert await card.locator(".profiles").is_hidden()
    assert await card.locator(".target-name").inner_text() == "Comfort"

    await page.evaluate("setCardState({})")
    await page.wait_for_timeout(100)
    assert await card.locator(".profiles").is_visible(), "back with automatic mode off"


async def test_a_temporary_profile_is_started_from_the_card(open_card):
    page = await open_card(AUTOMATIC)
    await page.locator("climate-profile-card .profile[data-id='p5']").click()
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


@pytest.mark.parametrize("layout", ["grid", "scroll", "icons"])
async def test_the_running_one_counts_down_and_a_tap_ends_it(open_card, layout):
    page = await open_card(RUNNING, card={"profile_layout": layout})
    button = page.locator("climate-profile-card .profile[data-id='p5']")
    countdown = button.locator(".profile-countdown")

    assert await countdown.is_visible()
    first = await countdown.inner_text()
    assert first.startswith("24:")
    await page.wait_for_timeout(1100)
    assert await countdown.inner_text() != first, "it counts"
    # Only the running one counts.
    other = page.locator(
        "climate-profile-card .profile[data-id='p6'] .profile-countdown"
    )
    assert await other.is_hidden()

    await button.click()
    assert await calls(page) == [
        {
            "domain": "climate_profiles",
            "service": "end_temporary",
            "data": {"entity_id": "sensor.living_room_climate_profile"},
        }
    ]


async def test_the_countdown_goes_under_the_name(open_card):
    page = await open_card(RUNNING)
    button = page.locator("climate-profile-card .profile[data-id='p5']")
    name = await button.locator(".profile-name").bounding_box()
    countdown = await button.locator(".profile-countdown").bounding_box()
    assert countdown["y"] >= name["y"] + name["height"] - 1


async def test_in_the_list_a_tap_ends_it_instead_of_opening(open_card):
    page = await open_card(RUNNING, card={"profile_layout": "dropdown"})
    card = page.locator("climate-profile-card")
    trigger = card.locator(".picker-trigger")

    assert (await trigger.locator(".picker-countdown").inner_text()).startswith("24:")
    await trigger.click()

    assert await card.locator(".picker-list").is_hidden()
    assert [call["service"] for call in await calls(page)] == ["end_temporary"]


async def test_outside_automatic_mode_temporary_changes_nothing(open_card):
    page = await open_card(automatic_state(status="off"))
    card = page.locator("climate-profile-card")
    for profile_id in ("p1", "p2", "p3", "p4", "p5", "p6"):
        assert await card.locator(f".profile[data-id='{profile_id}']").is_enabled()
    assert await card.locator(".profile-countdown:visible").count() == 0


async def test_the_editor_offers_automatic_mode(open_card):
    page = await open_card()
    schema = await page.evaluate(
        """() => {
          const editor = document.createElement('climate-profile-card-editor');
          editor.setConfig({ entity: 'sensor.living_room_climate_profile' });
          return editor._schema().map((field) => field.name);
        }"""
    )
    assert "show_automatic" in schema
    assert "show_target" in schema
    data = await page.evaluate(
        """() => {
          const editor = document.createElement('climate-profile-card-editor');
          editor.setConfig({ entity: 'sensor.living_room_climate_profile' });
          return editor._data();
        }"""
    )
    assert data["show_target"] is True, "on unless switched off"


#: Automatic mode holds "Comfort+", which is write protected.
FROZEN = {
    "temperature": 22,
    "active_profile": "Comfort+",
    "active_profile_id": "p4",
    "active_profile_color": "#10b981",
    "automatic": {
        **AUTOMATIC["automatic"],
        "sensor_state": "Comfort+",
        "target": "Comfort+",
        "target_id": "p4",
    },
}


async def test_a_protected_profile_held_by_automatic_mode_is_display_only(
    open_card,
):
    page = await open_card(FROZEN, card={"show_protection": True})
    card = page.locator("climate-profile-card")

    for selector in (".step", ".pill", ".segmented button", ".slider", ".toggle"):
        for control in await card.locator(selector).all():
            assert await control.is_disabled(), selector
    await card.locator(".step[data-step='up']").click(force=True)
    await card.locator(".segmented button").first.click(force=True)
    await page.wait_for_timeout(800)
    assert await calls(page) == []

    # What stays: starting a temporary profile, automatic mode, the lock.
    assert await card.locator(".profile[data-id='p5']").is_enabled()
    assert await card.locator(".lock").is_enabled()


async def test_an_unprotected_profile_held_by_automatic_mode_can_be_changed(
    open_card,
):
    page = await open_card(AUTOMATIC)
    card = page.locator("climate-profile-card")
    assert await card.locator(".step[data-step='up']").is_enabled()
