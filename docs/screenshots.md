# Screenshots

The README pictures are generated, not taken by hand. Regenerate them whenever
the card changes - a screenshot showing yesterday's state claims something
untrue, and nobody checks it against the code.

```bash
python tools/make_screenshots.py
```

## What the recipe does

* `tools/card-preview.html` renders the real `climate-profile-card.js` outside
  Home Assistant. It stubs the two Home Assistant elements the card uses
  (`ha-card`, `ha-icon`) and feeds it a fake `hass` object with Home
  Assistant's own light and dark theme variables.
* Icons come from `tools/mdi-paths.js` (vendored MDI paths, Apache-2.0). They
  are inlined as SVG because the real `ha-icon` lives inside the card's shadow
  DOM, where a document level stylesheet would not reach it.
* `tools/make_screenshots.py` serves the repository over HTTP, drives the
  already installed Google Chrome through Playwright and clips each shot to
  the measured bounding box of `#stage`.

The same harness drives `tests/test_card.py`, which clicks through the card in
a real browser. Those tests are skipped when Playwright is missing.

## Requirements

```bash
pip install playwright     # the Python package only
```

No browser download: the script uses `channel="chrome"`, i.e. the Google Chrome
that is already on the machine. Override the port with `PORT` if 8719 is busy.

## Sizes are not constants

The card grows with the number of profiles and the controls the device offers,
so every shot is clipped to the element's measured box instead of a fixed
window size. If you change the frame width in `card-preview.html`, the images
follow on their own.

## The states in the pictures

`SHOTS` in `tools/make_screenshots.py` lists them. Two are deliberately special
cases - do not "fix" them into a normal state:

| File | State |
| --- | --- |
| `card-light.png`, `card-dark.png` | "Comfort" active, both themes |
| `card-themes.png` | both themes side by side |
| `card-custom.png` | one manual change, no profile matches -> custom |
| `card-off.png` | device off, the "Off" profile matches |
| `card-heating.png` | a radiator thermostat: no fan, no swing, no switches |
| `card-capture.png` | something was changed by hand, the capture offer is up |

To look at a state interactively:

```bash
python -m http.server 8712
# http://localhost:8712/tools/card-preview.html?theme=dark
```

`?state=<url encoded JSON>` overrides the device state, `?card=<url encoded
JSON>` the card configuration, and `?device=heating` swaps the air conditioner
for a radiator thermostat.
