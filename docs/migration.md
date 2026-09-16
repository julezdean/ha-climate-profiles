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
* `hvac_mode` is applied first, then temperature, swing, fan mode, fan,
  display, silent - the order the script used
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
   Climate Profiles) and let it create the starter profiles, or add your own.
2. Compare: with the package still active, both the old sensor and
   `sensor.<name>_climate_profile` should show the same profile. If they do not,
   the profile values differ - fix them in the options flow.
3. Point your automations and dashboards at the new entities. Trigger on the
   `active_profile_id` attribute rather than the state.
4. Remove `packages/klimaanlage_*.yaml` and restart.

Nothing in the package has to be deleted before you start - the integration
only reads the climate entity and writes when you tell it to, so both can run
side by side while you check.
