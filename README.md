# Climate Profiles

A Home Assistant integration that turns any `climate` entity - an air
conditioner, a heat pump, a radiator thermostat - plus the optional
`number`/`switch` entities some devices expose, into freely configurable
profiles, and tells you which profile is currently active.

It replaces the usual "template sensor plus a script full of `choose` blocks"
package with a proper integration: profiles are configured in the UI, the
matching happens server side, and a custom Lovelace card renders it.

![The card in light and dark mode](docs/images/card-themes.png)

## What it does

* pick a climate entity, then add as many **additional values** as your device
  has: a fan speed `number`, a display `switch`, a preset `select` - anything
  whose state is a single value
* create as many profiles as you like, with your own names, colours and icons
* a profile only defines the values it cares about; applying it leaves
  everything else exactly where it is
* the integration continuously reports which profile matches the current state
  - and **Custom** as soon as you change anything by hand
* custom is a status, never a preset: it has no stored values and never writes
  anything back
* adjusted something by hand? Write it back into the profile it came from, or
  save the state as a new profile - with a click, never behind your back
* profiles can be write protected, so the ones you rely on cannot be
  overwritten by accident
* modes, temperature range, step widths and fan limits are read from the
  devices, never hard coded - a thermostat simply shows fewer controls
* several devices, each with its own profiles and its own Home Assistant device

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=julezdean&repository=ha-climate-profiles&category=integration)

The button opens this repository in your own HACS, adding it as a custom
repository if it is not known there yet. Download it and restart Home
Assistant. By hand it is the same thing:

1. HACS → Integrations → ⋮ → *Custom repositories*
2. add this repository, category *Integration*
3. install **Climate Profiles**
4. restart Home Assistant

### Manual

1. download `climate_profiles.zip` from the [latest
   release](https://github.com/julezdean/ha-climate-profiles/releases/latest)
   and unpack it into `config/custom_components/climate_profiles/`, or copy the
   `custom_components/climate_profiles` folder out of the repository
2. restart Home Assistant

The Lovelace card is registered automatically, as a resource under
**Settings → Dashboards → Resources** - you do not have to add it by hand. Only
a dashboard whose resources are declared in YAML owns that list itself; there
the log says which URL to add.

What changed in each version is in the [changelog](CHANGELOG.md).

## Setup

**Settings → Devices & services → Add integration → Climate Profiles**

1. **Climate device** - a name and the `climate` entity.
2. **Profiles** - a starter set is offered, built from what your device
   actually supports. Modes it does not advertise are left out, temperatures
   are clamped into its range.

Everything your device has beyond the climate entity is added afterwards, under
**Configure → Add a value**: pick the entity, and it is there. Supported are
`number`, `input_number`, `switch`, `input_boolean`, `select` and
`input_select` - the domains whose state is a single value, which is what a
profile can compare and write.

Each config entry creates one device with two entities:

| Entity | Purpose |
| --- | --- |
| `sensor.<name>_klimaprofil` | the active profile's name, plus everything the card needs as attributes |
| `select.<name>_profil` | pick a profile - works in automations, scripts and voice assistants |

## Managing profiles

**Settings → Devices & services → Climate Profiles → Configure**

| Menu entry | What it does |
| --- | --- |
| Add a value | an additional value, backed by an entity you pick |
| Edit a value | point it at a different entity, rename it, give it an icon |
| Order of the values | the order values are written in - and the card shows them in |
| Delete values | profiles keep what they stored, but it is skipped from then on; adding the entity again creates a new value, so to swap an entity, edit instead |
| Add profile | name, colour, icon and the values it should set |
| Edit profile | change everything; **clear a field to remove that value from the profile** |
| Change order | the order profiles are matched and shown in |
| Delete profiles | remove one or several |
| Rename "custom" | the name shown when nothing matches |

Each profile form has a **write protection** checkbox. It only blocks the
quick "capture" path - this form always stays editable.

Only `hvac_mode` is required - a profile that does not say what the device
should do is rarely useful. Everything else is optional and, when left empty,
is not touched when the profile is applied.

### Why "change order" is not drag & drop

Home Assistant renders config flows as plain forms; there is no sortable list
widget available to a custom integration. The closest native equivalent is
what this integration does: pick the profiles one after another in the order
you want. Anything you leave out keeps its relative position at the end.

The order matters: **the first profile that matches the current state wins.**
So put specific profiles above broad ones.

## The card

```yaml
type: custom:climate-profile-card
entity: sensor.living_room_climate_profile
```

Everything else - profiles, colours, which controls exist, the temperature
range - comes from the integration. Options, all optional:

| Option | Default | Meaning |
| --- | --- | --- |
| `name` | the entity's name | title shown in the header |
| `profile_layout` | `auto` | `auto`, `grid` or `scroll` |
| `hide` | `[]` | values to leave out, by key or id |

Everything configured is shown unless you hide it, so a value you add later
appears without editing every dashboard. The list mixes the four climate keys
with the ids of your additional values, the same way a profile's values do:

```yaml
hide: [swing_mode, 7f3a9c1e…]
```

The visual editor shows a switch per value and writes this list for you. A
control whose device does not offer it is hidden regardless.
More examples: [`examples/lovelace.yaml`](examples/lovelace.yaml).

| Profile active | Nothing matches |
| --- | --- |
| ![](docs/images/card-light.png) | ![](docs/images/card-custom.png) |

The card only renders and calls services. It never decides which profile is
active - that answer always comes from the integration, so the developer
tools, your automations and the card can never disagree.

## Taking manual changes into a profile

Adjust anything while a profile is active and the card offers to keep it:

![The capture offer](docs/images/card-capture.png)

* **Save into <profile>** updates the profile you were in. Values it already
  defines are updated; a value you changed by hand is added to it.
* **New profile** stores the state as a new profile - useful when the
  deviation is worth keeping without bending an existing profile.
* Doing nothing is a third option: the state simply stays custom.

The offer also appears while a *partial* profile is still active. A profile
that says nothing about the fan keeps matching when you change the fan - and
that is exactly a change worth offering to capture.

Nothing is ever captured automatically. That is deliberate: a profile that
rewrites itself silently is the most unpleasant kind of surprise, and it would
mean the profile could never report "custom" again.

**Write protection** is set per profile in the options. A protected profile
refuses to be captured into - the card then only offers the "new profile"
route. It can still be edited deliberately in the options; protection guards
the quick path, not the deliberate one.

**After a restart** nothing is assumed. The reference point for "what did you
change" only exists while Home Assistant runs, so a fresh start with a
deviating state stays custom and offers no target until a profile matches
again. Name the profile explicitly in the service call if you need it anyway.

### When a profile does not take

Two values of one profile can contradict each other on a real device. A silent
mode that sets its own fan speed makes "fan mode full, silent on" impossible:
whichever is written last wins, and the profile can never match afterwards.

The integration cannot know that - it is device knowledge. It can see the
result. After a profile is applied it waits until the device has been quiet for
a moment, then checks whether the profile actually took. If not, the card says
which values the device did not keep:

![A profile that did not take](docs/images/card-unreached.png)

It is a report, not an offer: only you know which of the two values was meant.
The same verdict is on the sensor as `unreached`, so an automation can react to
it, and in the log as a warning.

Which value wins is decided by the **order of the values** under Configure. It
is one list over everything - the climate values and your additional ones,
mixed - so a silent mode can go before or after the fan mode. The mode itself
always goes first: most devices ignore everything else while they are off.

### Not only air conditioners

Nothing in the integration assumes cooling. A radiator thermostat with no fan
and no swing modes gets the same profiles, with everything it cannot do left
out - of the card as well:

![A radiator thermostat](docs/images/card-heating.png)

The starter profiles are cooling shaped, so a heating only device gets just
the "Aus" profile offered and you add your own. Modes the device does not
advertise are never sent.

### Known limitations

| Not covered | What happens |
| --- | --- |
| `preset_mode` (eco/comfort/boost on many thermostats) | not a profile value; profiles set the temperature instead of the device's own preset |
| `target_temp_low`/`target_temp_high` (devices in `heat_cool`) | only `temperature` is read and written, so a profile with a temperature never matches such a device - the state stays custom rather than claiming a match |
| `humidity` | not a profile value |

Both gaps are pinned down by tests in `tests/test_heating.py`.

## Services

### `climate_profiles.apply_profile`

```yaml
action: climate_profiles.apply_profile
target:
  entity_id: sensor.living_room_climate_profile
data:
  profile: Comfort        # name or id
```

Writes only the values the profile defines. Values that already match produce
no service call at all - except when the hvac mode changes, because many
devices reset their attributes on a mode change.

An unknown profile raises a clean `ServiceValidationError` naming the profiles
that do exist; it never destabilises Home Assistant.

### `climate_profiles.set_value`

```yaml
action: climate_profiles.set_value
target:
  entity_id: sensor.living_room_climate_profile
data:
  temperature: 23
  Silent: true          # an additional value, by name or by id
```

Writes individual values and re-evaluates which profile that state
corresponds to. All fields are optional, at least one is required.

Besides the four climate values you can name any of your additional values,
by its name or by its id - ids win, so a value named like another one's id
cannot shadow it. An unknown name is refused with the list of what this device
knows.

### `climate_profiles.capture_profile`

```yaml
action: climate_profiles.capture_profile
target:
  entity_id: sensor.living_room_climate_profile
data:
  profile: Comfort        # optional - defaults to the profile that last matched
  values: [temperature]   # optional - defaults to deciding automatically
```

### `climate_profiles.save_as_profile`

```yaml
action: climate_profiles.save_as_profile
target:
  entity_id: sensor.living_room_climate_profile
data:
  name: Mittagshitze
  color: "#f59e0b"        # optional
  icon: mdi:weather-sunny # optional
  values: [temperature]   # optional - defaults to the whole state
```

More: [`examples/automations.yaml`](examples/automations.yaml).

## Sensor attributes

```yaml
active_profile: Comfort
active_profile_id: 2b3c4d5e…      # stable, use this in automations
active_profile_color: "#22c55e"
profiles: [{id, name, color, icon, order, protected, values}, …]
custom_profile: {id: __custom__, name: Custom, color: "#78909c"}
additional_values: [{id, name, entity, icon, order, kind, min, max, step, options}, …]
current_values: {hvac_mode: cool, temperature: 24.0, 7f3a9c1e…: 42, …}
capabilities: {hvac_modes: […], min_temp: 16, target_temp_step: 1, …}
entities: {climate: …, additional: {id: entity_id, …}}
applying: false
last_matched_profile_id: 2b3c4d5e…   # what "capture" would write into
changed_values: [temperature]        # what it would change; empty after a restart
unreached:                           # a profile that was applied but did not take
  {profile_id: …, profile: Max, values: {fan_mode: {wanted: full, actual: silent}}}
```

Automations should trigger on `active_profile_id`. The state is the display
name and changes when you rename a profile; the id does not.

The same holds for the additional values: `current_values` and `changed_values`
carry their ids, and `additional_values` says what each id is called and which
entity is behind it. Renaming a value or pointing it at a different entity
leaves every profile that sets it intact.

## How matching works

A profile matches when **every value it defines** equals the current state.
Values it does not define are ignored:

```text
Profile:  hvac_mode = cool, temperature = 24
Current:  hvac_mode = cool, temperature = 24, fan_mode = high, swing = both
          -> matches
```

Comparison is tolerant where devices are sloppy: case insensitive for modes,
half the device's step width as tolerance for temperatures, and `on`/`off`/
`true`/`false` all mean the same thing. A value that cannot be read (an
unavailable entity) never counts as a match.

If no profile matches, the state is the custom profile. It has no values, so
it can never be "applied" - selecting it does nothing on purpose.

## Development

```bash
pip install pytest-homeassistant-custom-component ruff
pytest                 # unit tests + tests against a real Home Assistant
ruff check . && ruff format --check .
python tools/make_screenshots.py     # see docs/screenshots.md
```

The matching logic (`models.py`, `matching.py`) has no Home Assistant imports
at all, which keeps it testable on its own and keeps the rules in one place.

The brand images in `custom_components/climate_profiles/brand/` are rendered
from [assets/climate_profiles_icon.svg](assets/climate_profiles_icon.svg) with
`rsvg-convert` (`brew install librsvg`):

```bash
rsvg-convert -w 256 -h 256 assets/climate_profiles_icon.svg \
  -o custom_components/climate_profiles/brand/icon.png
rsvg-convert -w 512 -h 512 assets/climate_profiles_icon.svg \
  -o custom_components/climate_profiles/brand/icon@2x.png
```

One icon serves both themes on purpose, so there are no `dark_*` variants, and
there is no separate logo either: Home Assistant falls back to the icon
wherever a logo would go. The bundled images are picked up from Home Assistant
2026.3 onwards; older versions show a placeholder on the integrations page.

## Accessibility

Every control is a real button with an `aria-label` and `aria-pressed`, the
focus ring is visible, and the active profile is marked with a check mark and
not by colour alone. The card measures both candidate text colours against
each profile colour and picks the more readable one. Very saturated mid tone
colours (a strong violet, for example) can still stay slightly below the 4.5:1
AA ratio - the profile name is always shown in the header as plain text as
well.

## Licence

MIT. The vendored Material Design Icons paths in `tools/mdi-paths.js` are
Apache-2.0.
