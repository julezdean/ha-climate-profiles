# Migrating from the YAML package

The original package built a template sensor that compared the current state
against a dict of presets, plus a script with one `choose` block per value.
This integration does the same thing, with the same rules.

## What maps to what

| YAML package | Integration |
| --- | --- |
| `presets` attribute of the template sensor | the profiles in the config entry's options |
| the `state:` template that compares everything | `matching.resolve_active_profile` |
| `'Benutzerdefiniert'` as the namespace default | the virtual custom profile (`active_profile_id: __custom__`), called "Custom" until you rename it |
| `script.<device>_preset_apply` | `climate_profiles.apply_profile` |
| `choose:` per value | `matching.build_apply_plan` - only defined values are sent |
| hard coded entity ids in every template | the config entry's entities |

## Behaviour that is intentionally identical

* a profile only sets what it defines; `Nacht` without `fan_mode` leaves the
  fan alone
* `hvac_mode` is applied first, as in the script; everything after it goes in
  the order you set under Configure, which is where the script's fixed
  sequence of temperature, swing, fan mode, fan, display and silent ended up
* comparison is case insensitive for modes (the template lower-cased fan modes)
* a second run replaces a running one (`mode: restart`)

## Behaviour that is deliberately different

| Then | Now | Why |
| --- | --- | --- |
| every value was sent on every apply | values that already match are skipped | fewer service calls, less wear on the device |
| — | on a mode change everything defined is re-sent | devices reset their attributes when switching on |
| temperature compared exactly | compared with half the device's step as tolerance | a device reporting 23.999 is not "custom" |
| an unavailable entity compared as a string | never counts as a match | "unavailable" is not a value |
| an unknown preset raised a template error | `ServiceValidationError` naming the known profiles | a typo should not destabilise anything |

## Steps

1. Set up the integration (Settings → Devices & services → Add integration →
   Climate Profiles) and add your profiles under Configure.
2. Compare: with the package still active, both the old sensor and
   `sensor.<name>_climate_profile` should show the same profile. If they do not,
   the profile values differ - fix them in the options flow.
3. Point your automations and dashboards at the new entities. Trigger on the
   `active_profile_id` attribute rather than the state.
4. Remove `packages/klimaanlage_*.yaml` and restart.

Nothing in the package has to be deleted before you start - the integration
only reads the climate entity and writes when you tell it to, so both can run
side by side while you check.

## Updating from 2.x to 3.0

3.0 gives every additional value a readable key instead of a uuid, and
rewrites what is stored once, on the first start: the values, every profile
and the apply order. Nothing has to be done by hand. What to know:

- **There is no way back.** A 2.x installation reading the new keys takes them
  for values that do not exist, and every profile loses its additional
  values. Make a backup before updating.
- **Dashboards keep working.** A card that hides a value by its uuid still
  hides it; the visual editor writes the key the next time it saves the card.
  The same goes for automations that call `set_value` or `capture_profile`
  with a uuid.
- **The keys are listed** under Configure → Manage values. `hide` takes them
  from now on: `hide: [kindersicherung]`.
- **Automatic mode has no custom any more.** An automation that waited for
  `active_profile_id: __custom__` while automatic mode was on never sees it
  now; trigger on the sensor's `deviates` attribute instead.
- **Profiles can be edited on the card.** `show_edit: true` puts a pencil
  into the header; see the README. If you tried 3.0.0-beta.1, the entities it
  made for every profile value are removed on the first start.
