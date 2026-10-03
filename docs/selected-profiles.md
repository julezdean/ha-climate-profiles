# Selected profiles and automatic capture

Two options per device, written down before they are built. This is the
reasoning, not a changelog.

## What they are for

Until now the active profile is **derived**: the integration compares the
device state against every profile and names the one that fits. That is the
whole idea, and for a device somebody also operates by remote control it is the
right one - turn the air conditioner off by hand and the card says "Off".

It has two consequences that get in the way of using profiles as named targets
of an automation:

- **Two profiles with the same values cannot both exist.** One of them is
  unreachable, because nothing in the state says which one was meant. Yet
  "Comfort" and "Emica" may well be 21 °C today and differ again tomorrow.
- **A profile becomes active without anybody choosing it.** An automation sets
  21 °C directly, and the card claims "Comfort" - which is a guess, not a fact.

## The two options

### Recognise this profile automatically

A field on every profile, default **on**, which is today's behaviour. Per
profile rather than per device: recognition can be off for the named targets of
an automation and on for "Off" at the same time, and a device-wide switch next
to a per profile one would be the same question in two places.

Switched **off** for a profile, it is active only while it is the one that was
selected - through the card, the select entity or `apply_profile`. Anything
else is custom, even when the values happen to match a profile exactly. The
comparison still runs, but only against the selected profile: as soon as the
state no longer holds it, the state is custom.

The description under the switch says so, because the name only describes what
stops happening:

> Off: only what you select counts as active. If the state deviates from it, it
> is custom.

**The selection survives a restart.** It is kept in the integration's own
storage, not in the config entry's options - writing options on every profile
change would run the options listener each time, which is the path that can
reload the entry. After a restart the selection counts only while its values
still hold; a device that moved in the meantime leaves the card on custom
rather than claiming a profile that stopped applying hours ago.

### What a change by hand does - per profile

Not a device-wide switch but a field on every profile, with three answers: ask
before storing (the default), store automatically, write protected.

It replaces the write protection checkbox, because both answer the same
question. As two settings in two places they could contradict each other -
"capture automatically" on the device and "protected" on the profile - and the
reader would have to guess which wins.

Three rules, each of them deliberate:

- **It stores what the button would have stored.** Values the profile defines
  are updated, and a value adjusted on top is taken into it - the profile grows
  by what was deliberately changed, exactly like the manual capture.
- **Every change counts, wherever it was made** - this card, another card, a
  script, the thermostat's own buttons. The first attempt counted only changes
  through this integration, which looked principled and was useless: a value
  set on another card never reached the profile, and that is the normal way to
  use Home Assistant. Home Assistant cannot tell a hand on the device from the
  device changing a value by itself, so the line is drawn by time instead: the
  window right after a profile was applied belongs to that profile, and what
  happens in it is the device's answer rather than somebody's decision. A value
  the device drops much later is stored like any other change - visible in the
  profile, and correctable there.
- **Never into a write protected profile.** Protection already means "not over
  the quick path", and this is the quickest path there is.

Writing waits until the state has been quiet for a moment, so moving a slider
in steps does not store every step on the way.

## What happens when the state deviates

Unchanged from today, and the same with either option: the state is custom, and
the card offers to capture the change into the profile it came from or to save
it as a new one. If that profile is write protected, there is no offer - just
custom. The offer expires a minute after the last change.

## What this does not decide

- Whether the select entity should show the selected profile while the state
  deviates from it. Today it mirrors the sensor, which means custom.
- Whether automatic capture should also trigger on `apply_profile` of another
  profile - it does not; applying is choosing, not changing.
