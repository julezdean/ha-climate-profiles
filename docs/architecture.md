# Architecture

## The one rule

**The integration decides which profile is active. The card renders it.**

Everything else follows from that. The card never compares values, never
decides what "custom" means and never writes to the climate entity directly.
It reads one sensor and calls two services. That is why profiles behave
identically in automations, scripts, voice assistants, the developer tools and
any other dashboard.

## Layers

```
models.py     data:    ClimateProfile, ProfileSet, EntityMap, Capabilities
matching.py   rules:   normalise -> compare -> resolve active -> build a plan
                       (no Home Assistant imports in either file)
─────────────────────────────────────────────────────────────────────────────
coordinator.py glue:   read states, run the rules, execute the plan
entity.py              one device per config entry
sensor.py              the active profile + everything the card needs
                       + the two entity services
select.py              picking a profile the native way
config_flow.py         setup and profile management
─────────────────────────────────────────────────────────────────────────────
frontend/…js  view:    renders the sensor, calls the services
```

`models.py` and `matching.py` deliberately import nothing from Home Assistant.
That keeps the rules in exactly one place, makes them unit testable without a
running Home Assistant, and means a bug in the matching can be reproduced in a
two line test instead of a full integration setup.

## Data flow

```
climate/number/switch state changes
        │
        ▼ (debounced 0.4 s)
ClimateProfilesCoordinator._async_update_data
        │  reads values + capabilities from the entities
        ▼
matching.resolve_active_profile(profiles, values, capabilities)
        │  first profile whose every defined value matches, else None
        ▼
ProfileState  ──►  sensor + select  ──►  the card
```

Applying goes the other way:

```
card / service / select
        ▼
coordinator.async_apply_profile(name or id)
        ▼
matching.build_apply_plan(values, current, entities, capabilities)
        │  skips values that already match
        │  re-sends everything when the hvac mode changes
        │  reports what cannot be applied instead of guessing
        ▼
hass.services.async_call(...) for each step, in the original script's order
        ▼
async_refresh -> the state is re-evaluated
```

## Decisions worth knowing

**No polling.** Every source is a local push entity, so the coordinator has no
`update_interval`; it listens to state changes instead. Recalculation is
debounced by 0.4 s because a climate device reports its new values one
attribute at a time, and the sensor should not flicker through half applied
intermediate states. There is a test for exactly that.

**Optimistic, then honest.** While a profile is being applied, the sensor
already reports the target profile and sets `applying: true`, so the card
reacts instantly. When the refresh afterwards shows the device did not follow,
the state falls back to what is really there. Also tested.

**Restart, not queue.** A second apply cancels a running one, mirroring the
`mode: restart` of the original script. Two users tapping two profiles get the
second one, not an interleaving of both. The superseded caller returns without
an error.

**Order is the list.** `ClimateProfile` has no `order` field: the position in
`ProfileSet` is the single source of truth, and `order` is derived from it for
the frontend. A stored index and a list position can disagree after an edit; a
list position cannot disagree with itself.

**Ids, not names.** Profiles have opaque ids. Renaming a profile keeps
automations working, and `active_profile_id` is the attribute automations
should trigger on. Names may even collide - the select entity disambiguates
them for its options.

**Options, not a custom store.** Profiles live in the config entry's options,
so Home Assistant persists them, and multiple instances cannot mix. Changing
options reloads the entry, which is easier to reason about than patching a
live coordinator.

**Nothing is hard coded.** Modes, swing modes, fan modes, temperature range,
step widths and the number entity's limits are all read from the devices. A
profile value the device does not advertise is reported as unsupported instead
of being sent and silently failing.

**The baseline is runtime only.** Capturing needs to know what you changed,
which means knowing what the state looked like before. That snapshot is taken
when a profile *becomes* active - not on every recalculation, because a
partial profile keeps matching while you adjust a value it does not define,
and refreshing the baseline there would forget exactly what you just changed.
It is renewed after the integration writes the state itself. Nothing of it is
persisted: after a restart there is no reference point, and saying so is
better than guessing.

**Capturing never happens on its own.** A profile that rewrites itself would
need an echo guard - a way to tell the integration's own writes from the
user's - and, worse, it could never report "custom" again, because every
deviation would be swallowed. The explicit route needs neither.

**Options changes do not reload the entry.** Only the entity map is baked into
the coordinator; profiles and the custom name are read fresh on each access.
So capturing from the card updates the options and refreshes, instead of
reloading and making every entity blink. A change to the entities themselves
still reloads - that is what `async_reload_entry` decides.

## What Home Assistant cannot do here

**Drag & drop in a config flow.** Config flows are forms; there is no sortable
list widget available to a custom integration. The nearest native equivalent
is the "change order" step, where profiles are picked one after another in the
wanted order. Anything left out keeps its relative position at the end.

**A translated state.** A sensor's state is a string. Translating the custom
profile's name per user language would make automations language dependent, so
the name is configurable but fixed per installation, and the language
independent `active_profile_id` (`__custom__`) is what automations should use.

**Enum device class on the sensor.** It would require a fixed list of options,
but profiles change at runtime. The `select` entity fills that role instead.
