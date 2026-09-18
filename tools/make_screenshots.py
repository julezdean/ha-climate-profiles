#!/usr/bin/env python3
"""Render the Lovelace card and write the screenshots used in the README.

    uv run --with playwright python tools/make_screenshots.py
    # or, with playwright installed in your venv:
    python tools/make_screenshots.py

Uses the Google Chrome that is already installed (``channel="chrome"``), so
nothing has to be downloaded.

The image sizes are not constants: the card grows with the number of profiles
and controls. Each shot is clipped to the element's measured bounding box, so
the pictures follow the card instead of the other way round.
"""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import sys
import threading
import urllib.parse
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
PORT = 8719

#: name -> {theme, device, state overrides}
SHOTS: dict[str, dict] = {
    "card-light": {"theme": "light"},
    "card-dark": {"theme": "dark"},
    "card-themes": {"theme": "both"},
    # Deliberately a special case: one manual change and no stored profile
    # matches any more. Do not replace this with a "normal" state.
    "card-custom": {
        "theme": "light",
        "state": {
            "temperature": 23,
            "active_profile": "Custom",
            "active_profile_id": "__custom__",
            "active_profile_color": "#78909c",
        },
    },
    "card-off": {
        "theme": "light",
        "state": {
            "hvac_mode": "off",
            "active_profile": "Off",
            "active_profile_id": "p1",
            "active_profile_color": "#64748b",
        },
    },
    # A radiator thermostat: everything the device cannot do is gone.
    "card-heating": {"theme": "light", "device": "heating"},
    # A profile the device could not keep: two of its values contradict each
    # other on the device. A report, deliberately without a button.
    "card-unreached": {
        "theme": "light",
        "state": {
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
        },
    },
    # The offer to write a manual change back into the profile it came from.
    "card-capture": {
        "theme": "light",
        "state": {
            "temperature": 23,
            "fan_mode": "high",
            "active_profile": "Custom",
            "active_profile_id": "__custom__",
            "active_profile_color": "#78909c",
            "changed_values": ["temperature", "fan_mode"],
            "last_matched_profile_id": "p3",
        },
    },
}


def launch_options() -> dict:
    """Return how to start the browser.

    Locally this drives the Google Chrome that is already installed, so
    nothing has to be downloaded. CI has no Chrome channel, so setting
    PLAYWRIGHT_CHANNEL to an empty string falls back to Playwright's own
    bundled Chromium.
    """
    channel = os.environ.get("PLAYWRIGHT_CHANNEL", "chrome")
    return {"channel": channel} if channel else {}


@contextmanager
def serve(directory: Path, port: int):
    """Serve ``directory`` on localhost for the lifetime of the block."""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, *_args):  # keep the output readable
            pass

    class Server(socketserver.TCPServer):
        # Without this a second run within a minute dies on TIME_WAIT.
        allow_reuse_address = True

    with Server(("127.0.0.1", port), Handler) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            httpd.shutdown()


def build_url(base: str, shot: dict) -> str:
    """Return the preview URL for one shot."""
    query = {"theme": shot.get("theme", "light"), "shot": "1"}
    if shot.get("device"):
        query["device"] = shot["device"]
    if shot.get("state"):
        query["state"] = json.dumps(shot["state"])
    return f"{base}/tools/card-preview.html?{urllib.parse.urlencode(query)}"


def main() -> int:
    """Write every screenshot in SHOTS."""
    OUT.mkdir(parents=True, exist_ok=True)

    with serve(ROOT, PORT) as base, sync_playwright() as play:
        browser = play.chromium.launch(**launch_options())
        page = browser.new_page(
            viewport={"width": 1000, "height": 1200}, device_scale_factor=2
        )
        for name, shot in SHOTS.items():
            page.goto(build_url(base, shot), wait_until="networkidle")
            page.wait_for_timeout(250)
            target = page.locator("#stage")
            box = target.bounding_box()
            if box is None:  # pragma: no cover - defensive
                print(f"could not measure {name}", file=sys.stderr)
                return 1
            path = OUT / f"{name}.png"
            target.screenshot(path=str(path))
            print(f"{path.relative_to(ROOT)}  {int(box['width'])}x{int(box['height'])}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
