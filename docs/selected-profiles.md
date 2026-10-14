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

A field on every profile, default **on**, which is today's behaviour. (Since
2.1 a new profile starts with it off; stored profiles keep it on. A profile is
usually something you choose, and before Home Assistant 2026.10 a new row
showed the switch off anyway while storing it on.) Per profile rather than per
device: recognition can be off for the named targets of
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

Not a device-wide switch but a field on every profile. It started with three
answers - ask before storing (the default), store automatically, write
protected - and since 2.1 has two: a profile takes the change, or it is
**write protected** and keeps it out. Taking it is the default.

It replaced the write protection checkbox, because both answer the same
question. As two settings in two places they could contradict each other -
"capture automatically" on the device and "protected" on the profile - and the
reader would have to guess which wins. With two answers left it is a checkbox
again, but still the only one: there is nothing it could contradict.

"Ask" went because asking had a price nobody paid twice. The card had to show
an offer, the offer had to expire, it needed a × to dismiss it and a service
behind the ×, and a second route to save the state as a new profile with a
name field inside the card - all to answer a question whose answer was nearly
always the same. A profile now either takes changes or does not, and which one
is visible and switchable: the profile's switch entity, its row in the options,
and the lock on the card.

Three rules, each of them deliberate:

- **It stores what `capture_profile` stores.** Values the profile defines are
  updated, and a value adjusted on top is taken into it - the profile grows by
  what was deliberately changed.
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
- **Never into a write protected profile** - not automatically, and not through
  `capture_profile` either. Protection guards against changes made by hand;
  the options flow stays open for deliberate edits.

Writing waits until the state has been quiet for a moment, so moving a slider
in steps does not store every step on the way.

**Lifting the protection is not retroactive.** What is stored is measured
against the moment the profile became active. Kept across a protected stretch,
that moment would hand the first change after lifting the protection
everything that differs since - hours of it, perhaps. So lifting it starts the
measurement over, and a profile that is not active at that moment takes
nothing until it matches again.

## What happens when the state deviates

With a profile that takes changes: the profile stays active, and a few seconds
later the change is in it and it matches again by itself. In between it is
held - custom for those seconds would be a flap, not a fact. A change to a value a
write protected profile defines makes the state custom; the profile stays as it
was. Nothing is offered, and nothing expires.

## What this does not decide

- Whether the select entity should show the selected profile while the state
  deviates from it. Today it mirrors the sensor, which means custom.
- Whether automatic capture should also trigger on `apply_profile` of another
  profile - it does not; applying is choosing, not changing.
