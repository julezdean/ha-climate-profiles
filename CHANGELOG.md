# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
versioning [Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-09-17

### Changed

- **The three fixed optional entities are gone.** A config entry used to drive
  a fan speed `number`, a display `switch` and a silent mode `switch` - the
  vocabulary of one air conditioner. It now drives any number of **additional
  values**, each backed by an entity you pick: `number`, `input_number`,
  `switch`, `input_boolean`, `select` or `input_select`, the domains whose
  state is a single value. Two of the three old fields were the same thing
  twice anyway - `display` and `silent` were both a switch, told apart by
  nothing but the label the card drew.
- Each additional value carries a stable id of its own, and profiles store
  their values under it. Renaming a value or pointing it at a different entity
  leaves every profile that sets it intact - the same reasoning that made
  `active_profile_id` the thing to trigger on rather than the profile name.
- The card draws what the kind of a value needs: a number becomes a slider
  with the range of its own entity, a boolean a toggle, a select a group of
  options. Name and icon come from the value, so nothing in the card knows any
  single value by name any more.
- `set_value` takes any of your values, by name or by id, alongside the four
  climate ones. An unknown name is refused with the list of what the device
  knows instead of being ignored.
- The values a profile sets are read from what the entry knows at the moment
  it is evaluated, so a deleted additional value no longer makes a profile
  unreadable - its stored value is simply skipped, and putting the entity back
  restores what the profile meant.
- Setup asks for the climate entity and the starter profiles only; additional
  values are added afterwards under **Configure**.
- The integration declares `CONFIG_SCHEMA` as config-entry-only, so a stray
  `climate_profiles:` block in `configuration.yaml` is an error rather than
  something silently ignored.

### Card configuration

- The seven `show_*` options are replaced by one `hide` list, over one key
  space: the four climate keys and the ids of your additional values, the same
  mix a profile's values carry. Everything configured is shown unless it is
  hidden, so a value added later appears without editing every dashboard. The
  visual editor still shows a switch per value and writes the list for you.

### Attributes

- `additional_values` is new and says what each id is called, which entity is
  behind it, how to draw it and which limits it has.
- `current_values` and `changed_values` carry the ids of additional values.
- `entities` is now `{climate, additional: {id: entity_id}}`.
- `capabilities` no longer carries `fan_min`/`fan_max`/`fan_step`; the limits
  of an additional value belong to its own entity and ship with its definition.

### Migration

None. Nothing was running this integration, so the old fields are dropped
rather than converted. An entry created with 1.x keeps its climate entity and
its profiles; the three optional entities have to be added again as additional
values, and profiles that set them need those values filled in once more.

## [1.0.1] - 2026-09-17

### Fixed

- The card is registered as a Lovelace resource instead of through
  `frontend.add_extra_js_url`. The script tag that call injects lives in the
  Home Assistant page, and that page is cached by the service worker, per
  browser and per phone: a client holding an older copy never saw the card and
  showed "custom element not found" - across restarts, past a hard reload, and
  looking exactly like a card that is broken rather than one that never
  arrived. Resources are read from the resource list over the websocket API at
  runtime, so a cached page no longer decides whether the card exists. The
  entry is matched by path, so an update replaces it rather than leaving a
  second one behind, and the last config entry to go takes the resource with
  it.
- The card file was checked for existence in the event loop. That check now
  runs in the executor, like every other file access during setup.

## [1.0.0] - 2026-09-16

### Added

- Climate profiles as config entries: one Home Assistant device per climate
  entity, added through **Settings → Devices & services → Add integration**
- Any number of profiles per device, with their own names, colours and icons,
  configured in the UI instead of in a YAML package
- A profile defines only the values it cares about. Applying it leaves
  everything it says nothing about exactly where it is
- Server side matching: the integration continuously reports which profile the
  current state corresponds to, and the virtual **Custom** profile as soon as
  anything is changed by hand. Custom is a status, never a preset - it has no
  stored values and never writes anything back
- Comparison is tolerant where devices are sloppy: case insensitive for modes,
  half the device's step width as tolerance for temperatures, `on`/`off` and
  `true`/`false` treated alike, and a value that cannot be read never counts as
  a match
- Optional `number` and `switch` entities for fan speed, display and silent
  mode - whatever is left out is simply not offered
- Modes, temperature range, step widths and fan limits are read from the device
  rather than hard coded, so a radiator thermostat shows fewer controls without
  being configured differently
- Write protected profiles, so the ones the household relies on cannot be
  overwritten by accident
- A manual change can be written back into the profile it came from, or saved
  as a new profile - on a click, never behind your back
- Entities per device: an active profile sensor carrying the whole state in its
  attributes, and a select entity for voice assistants and plain dashboards
- Services `apply_profile`, `set_value`, `capture_profile` and
  `save_as_profile`, so profiles work in automations and not just in the card
- Bundled Lovelace card `custom:climate-profile-card`, served and registered
  automatically - no resource entry to add by hand
- English and German translations
- Brand images shipped with the integration in
  `custom_components/climate_profiles/brand/`, which Home Assistant reads from
  2026.3 onwards; older versions show a placeholder on the integrations page
- HACS installs from a `climate_profiles.zip` attached to the release, so an
  install arrives complete and there is an asset for GitHub to count downloads
  on
