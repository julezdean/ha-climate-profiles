# Additional values

The design for 2.0.0, written down before it is built. This is the reasoning,
not a changelog: what was decided, and why the obvious alternative was not.

## What changes

Until 1.0.1 a config entry drives a climate entity plus exactly three optional
ones: a fan speed `number`, a display `switch` and a silent mode `switch`.
Those three are the vocabulary of one air conditioner. A radiator thermostat
has none of them; another device has three different ones.

From 2.0.0 a config entry drives a climate entity plus **any number of
additional values**, each backed by an entity of the user's choosing.

The four values that live on the climate entity itself - `hvac_mode`,
`temperature`, `swing_mode`, `fan_mode` - are not affected. They are not user
data: they cannot be renamed, removed or pointed somewhere else, because Home
Assistant defines them.

Two of the three old fields were already the same thing twice: `display` and
`silent` are both a `switch`, and the integration told them apart by nothing
but the label and the icon the card drew. Two fields that differ only in their
caption are a list that has not been written yet.

## Decisions

### Identity is a stable id, not a name or an entity id

Every additional value carries an id of its own. Profiles store their values
under it.

```yaml
additional_values:
  - id: 7f3a9c1e…
    name: Fan speed
    entity: number.living_room_fan_speed
    icon: mdi:fan
    order: 0

# in a profile
values:
  hvac_mode: cool
  temperature: 24
  7f3a9c1e…: 42
```

The alternative - using the entity id as the key - reads better and breaks
quietly: rename the entity and every profile that sets that value stops
matching, with nothing in the log and no visible cause. This project already
made that choice once, for profiles, and says so in the README: "the state is
the display name and changes when you rename a profile; the id does not". The
same reasoning applies here.

The key space is therefore mixed: fixed, speaking keys for the four climate
values, ids for everything else. That is not an oversight. The climate values
are given by Home Assistant and cannot be renamed; the additional ones are the
user's and can.

### The fields are the entry's own, with defaults from the entity

Name and icon are stored on the additional value, not read from the entity
every time. They are pre-filled from the entity when it is picked, so adding
one is still a single choice, and they can be edited afterwards without
touching the entity.

### Names are unique, enforced when they are set

Profile names are free text and may collide; `display_names()` appends a
counter when the select entity needs distinct options. Additional values are
handled the other way round: the config flow keeps names unique when they are
created and when they are renamed, appending a counter to a pre-filled name
that is already taken.

The difference is where the collision comes from. A duplicate profile name is
typed by the user. A duplicate additional value name arrives on its own, as
soon as two device switches are both called "Silent" - and a problem the user
did not cause should not be theirs to untangle in an automation at runtime.

The payoff is that resolving a name in `set_value` and `capture_profile` stays
as simple as it is for profiles: id first, then name, done. No ambiguous case
to handle where a service is about to write a value to a device.

### Only domains whose state is a single value

`number`, `input_number`, `switch`, `input_boolean`, `select`, `input_select`.

Generic is not the same as arbitrary. A `light` would force an answer to what
"equal" means - brightness? colour? colour temperature? - and matching would
have to carry that answer for every domain anybody might pick. These six have
one value per entity, which is exactly what a profile compares and writes.

The service to call follows from the domain, not from the key: `set_value` for
the two number domains, `turn_on`/`turn_off` for the two boolean ones,
`select_option` for the two select ones.

### Types are passed in, not looked up

`normalise_value` and its neighbours in `matching.py` take the key and the raw
value today, and decide from the constants `BOOLEAN_KEYS` and `NUMERIC_KEYS`.
With free entities the type follows from the domain, which is runtime
knowledge.

`matching.py` has no Home Assistant imports and is testable on its own. That
property stays: the type is handed in as data along with the value, never
fetched from `hass` inside the module.

### The card hides by list

`show_fan`, `show_display`, `show_silent` and the four `show_*` for the climate
values are replaced by one list:

```yaml
type: custom:climate-profile-card
entity: sensor.living_room_climate_profile
hide: [swing_mode, 7f3a9c1e…]
```

Everything configured is shown unless it is hidden, so a value that is added
later appears without editing every dashboard. One key space rather than two,
matching the way `values:` already mixes fixed keys and ids. The visual editor
keeps its switches - it builds them from the definitions and stores the result
as this list.

The cost: a card configuration on its own no longer says what is visible, only
what is missing, and the ids in it mean nothing without the definition list.

### No migration

Nothing runs this integration yet. The three old fields are dropped rather than
converted, and no code is written to read a shape that never reached anybody.

## What it turned into

Built in 2.0.0. Three things the design did not foresee, decided while
building:

- **The limits had nowhere to live.** Dropping `fan_min`/`fan_max` from the
  capabilities left the card with no range for a slider. The definition list
  carries them now, filled from the vocabulary, so a control gets its bounds
  from the entity behind it.
- **Values in the options change what has to be listened to.** With the
  additional values in the entry's options, the check in `async_reload_entry`
  compared entity maps that could never be equal, and every captured profile
  reloaded the entry - every entity blinking to unavailable on the way. The
  comparison reads them from the options too, so a profile change still only
  recalculates while a changed set of entities still reloads.
- **The order became a decision of its own.** Values can contradict each
  other on a device - a silent mode that sets its own fan speed - and then the
  one written last wins. So the apply order is one list over everything, the
  climate keys and the additional values mixed, set under Configure; anything
  it does not name keeps its default place at the end. `hvac_mode` is not in
  it and always goes first, because most devices ignore everything else while
  they are off. The card shows the additional values in the same order: one
  list, one truth, rather than a second sorting nobody can tell apart.
- **A contradiction cannot be prevented, only reported.** Which values exclude
  each other is device knowledge. What the integration can do is look: after a
  profile is applied it waits for the device to be quiet, checks whether the
  profile took, and if not reports which values the device did not keep. A
  report, not a fix - offering to write the result into the profile would be
  the wrong answer whenever the other of the two values was the one meant.
- **Leaving a profile has to mean leaving it.** Right after the calls the
  device has not reported yet, so the profile you came from still matches for
  a moment and used to take the reference point for "changed by hand" back. A
  profile the device could not keep was then offered for capture into the
  previous one. While an applied profile is pending, no other profile may take
  that reference point.

The waiting times are provisional (`REACH_QUIET_SECONDS`,
`REACH_MAX_SECONDS`): how long a device takes to report what it did differs per
device, and the debug log of the coordinator records exactly that, so they can
be set from a real one.

Still open:

- Whether `capture_profile` should offer additional values in the same list as
  the climate ones, or in a second one.
