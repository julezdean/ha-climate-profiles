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
  unreadable - its stored value is simply skipped. To swap the entity behind
  a value without losing what profiles set for it, edit the value rather than
  deleting it: a value added anew gets a new id.
- **Setup is a single form** - a name and the climate entity. No starter
  profiles are created any more: the blueprint was shaped like an air
  conditioner, so a radiator thermostat got a single "Off" profile whose mode
  many such devices do not even accept, and everything else had to be rewritten
  by hand. Profiles and additional values are added afterwards under
  **Configure**.
- The integration declares `CONFIG_SCHEMA` as config-entry-only, so a stray
  `climate_profiles:` block in `configuration.yaml` is an error rather than
  something silently ignored.
- **Configure is two lists instead of eleven menu entries.** *Manage values*
  and *Manage profiles* each open a sortable list: one row per entry, with a
  drag handle, a pencil and a bin, and a button to add one. Adding, editing,
  reordering and deleting used to be four menu entries each, every one of them
  a separate walk through the dialog. A profile's row holds everything it is -
  name, colour, icon, how it becomes active, what a change by hand does, and
  every value it sets; its id travels with the row unseen, because that is what
  the stored values hang off and it is nothing to type at. The order of the rows is the order profiles
  are matched and shown in. Underneath the value list sit the two things that
  are not rows: the tick-off list of the device's own entities, and the order
  values are written in. Underneath the profile list sit the three fields of
  "custom".

### Added

- **A profile that does not take is reported.** Two values of one profile can
  contradict each other on a device - a silent mode that sets its own fan
  speed makes "fan full, silent on" unreachable. After applying a profile the
  integration waits until the device has been quiet for a moment and checks
  whether it took. If not, the sensor carries `unreached` with the values the
  device did not keep, the log says so, and the card shows it - as a report,
  not an offer, because only the user knows which of the two values was meant.
- **Add values from this device.** When the climate entity sits on a Home
  Assistant device, its siblings are offered as a list to tick off: everything
  in the domains whose state is a single value, minus what is already
  configured, minus diagnostic entities - a battery level is not something a
  profile sets, while a calibration offset stays on offer. Nothing is added by
  itself: a device that gains entities with a firmware update must not quietly
  gain profile values. The climate entity remains what identifies an entry, so
  a template or helper climate entity without a device loses nothing; for those
  the menu entry simply does not appear.
- **The profiles can be a dropdown**: `profile_layout: dropdown`, or the entry
  in the card's editor. One list instead of a wall of buttons, for a dashboard
  where this is one card among many. It is not a `<select>`: that can draw
  neither an icon nor a colour, and those are how a profile is recognised at a
  glance - so the field and every row carry the same mark the buttons do, and
  the list takes the arrow keys, Enter and Escape. "Custom" is in the list only
  while it is what the device is doing, and stays unpickable - it has no values
  to apply. `auto` is unchanged and never picks it.
- **The temperature can be a dial** instead of the bar: `temperature_style:
  dial` in the card, or the dropdown in its editor. A 270° arc in the active
  profile's colour, the room's own temperature as a dot on the same scale, and
  what the device reports in the middle. The two step buttons stay, in the gap
  at the bottom of the arc - a finger dragged around a ring rarely lands on
  the half degree somebody meant. The ring can also be moved with the arrow
  keys. The default is unchanged, so no dashboard looks different until you
  ask for it.
- **"Custom" is editable like a profile**: name, colour and icon, under
  *Manage profiles*. It still has no values of its own - it is what the card
  shows when none of the stored profiles match - but it is a button next to
  them, and it looked like the one thing nobody was allowed to style. The
  sensor's `active_profile_color` follows the colour while nothing matches.
- **The humidity the device reports is shown** next to the current
  temperature, where a thermostat card shows it. `current_humidity` was in the
  climate entity's attributes all along and the card simply did not read it;
  a device without a humidity sensor prints no stray percent sign.
- **The order of the values** can be set under Configure: one list over the
  climate values and the additional ones, mixed, so a silent mode can be
  written before or after the fan mode - whichever should win. `hvac_mode`
  always goes first, because most devices ignore everything else while they
  are off. The card shows the additional values in the same order.

### Added

- **The offer to capture a manual change can be dismissed** with the × in its
  corner, through the new service `climate_profiles.dismiss_change`. The state
  stays as it is and is simply no longer presented as a fresh change.
- **The offer to capture a manual change expires.** It used to stay up for as
  long as the deviation lasted, still claiming hours later that something had
  just been changed. A minute after the last change the reference point is
  dropped and the state is plainly custom, the way a restart leaves it. Every
  further change starts that minute over, and capturing into a profile named
  explicitly is unaffected.

### Added

- **Every profile says how it becomes active.** *Recognise this profile
  automatically* is on by default and is what the integration always did: the
  active profile is read off the device state. Switched off for a profile, it
  is active only while it is the one that was selected - through the card, the
  select entity or `apply_profile`. That is what lets two profiles hold the
  same values, and it stops an automation writing to the climate entity from
  making the card claim a profile nobody chose. Set per profile rather than per
  device, so recognition can be off for your named targets and on for "Off" at
  the same time. A selected profile wins while its values hold, otherwise the
  most specific of the recognisable ones; the selection survives a restart and
  counts only while it still holds.
- **What a change by hand does is set per profile.** The write protection
  checkbox is replaced by one field with three answers: ask before storing (the
  default, what the card has always offered), store automatically, or write
  protected. One question, one place - a device-wide switch next to a per
  profile checkbox could contradict itself. Storing automatically means what
  the "save into" button stores: values the profile defines are updated and a
  value adjusted on top is taken into it. It applies wherever the change was
  made - this card, another one, a script, or the thermostat's own buttons -
  because Home Assistant cannot tell a hand on the device from the device
  changing a value by itself. The one exception is the window right after a
  profile was applied, which is where a device's overrides happen.
- Profiles stored by 1.x and the earlier 2.0 betas are read as before:
  `protected: true` becomes "write protected", everything else "ask".

### Fixed

- **A profile that stores automatically no longer asks first.** The offer to
  capture went up the moment the state deviated and vanished again when the
  write happened three seconds later - a question that answered itself, with
  a "save as a new profile" button nobody wanted there. A profile set to store
  automatically now shows no offer at all. The README's claim that nothing is
  ever captured automatically was left over from 1.x and is corrected with it.
- **A value the profile does not define is stored too.** Both the offer to
  capture and automatic capture compare the state against the moment the
  profile was applied. Writing a single value - through `set_value` or the
  card - renewed that moment as well, so the change was gone before anything
  could be stored. It only showed on values a profile says nothing about,
  because those leave it matching; a value the profile does define makes it
  stop matching, and the offer appeared as it should. Only applying a profile
  makes a new reference point now. Devices that report the new state inside
  the service call - what a real one does - are where this was visible at all.
- **The card's editor offers only values the device actually has.** The four
  climate switches - temperature, mode, fan mode, swing - were hard coded and
  stood in the editor of every device, so a radiator thermostat offered to
  hide a fan mode it does not have. They are now read from the sensor's
  attributes, the same ones the card draws from, which is how the additional
  values always worked.
- **Hiding the temperature takes it out of the card.** Two faults in one
  place: the temperature block still read a `show_temperature` of its own
  instead of the `hide` list, and its `display: grid` beat the `hidden`
  attribute - so the switch in the editor did nothing either way.
- **The most specific of the matching profiles is shown, not the first one.**
  Several profiles can match at once, and a profile that only says "heating"
  matches every heated state. With first-match-wins it swallowed every
  narrower profile that came after it: tapping "Sleep" or "Boost" wrote the
  values, but the card kept showing the catch-all, and it looked as if nothing
  had happened. The profile defining the most values now wins; the order
  decides between profiles that are equally specific, which is what it was
  always for. The options flow logs which profiles are catch-alls for others.
- **A value whose entity is unavailable is skipped instead of counted as a
  mismatch.** Some devices drop an entity while they are off - a silent mode
  switch that only exists while the unit runs. Every profile mentioning it was
  stuck on "custom", and nothing was ever written to it either: the integration
  now leaves such values out of both the comparison and the plan. A value that
  is merely missing still counts as a mismatch, because nothing confirms it.
- **A profile is watched until the window is over, not judged once.** A device
  that accepts a value and drops it again seconds later used to count as
  success, because the check looked once and stopped. It now keeps looking
  until the maximum wait is over and reports a value that did not hold.
- **A change by hand ends the check.** Adjusting something right after applying
  a profile made the integration blame the profile for what the user did.
- Applying a profile the device could not keep made the card offer the result
  as a hand edit of the profile you came from - "Changed by hand, save into
  Comfort" after tapping Max. Applying a profile now leaves the previous one
  for good: until the applied profile matches, no other profile takes the
  reference point back, even though it keeps matching for the moment before
  the device reports. This was already the case in 1.x.

### Changed (the card)

- **The tinted gradient behind the header is gone.** The profile's colour is
  on the profile buttons, the mode pill and the temperature it sets; washing
  the title with it as well was decoration, not information. In the dial it
  stays as a quiet glow behind the ring, where it belongs to the arc.

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
