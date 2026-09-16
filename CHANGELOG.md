# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
versioning [Semantic Versioning](https://semver.org/).

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
