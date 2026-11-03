# Readable keys, value entities, no custom in automatic mode

The design for 3.0.0, written down before it is built. This is the reasoning,
not a changelog: what was decided, and why the obvious alternative was not.

## What changes

Three things, released together because the first two share the key space and
the third changes what the state means:

- An additional value is addressed by a **readable key** instead of a uuid.
- Every value a profile sets is an **entity** of its own, so a profile can be
  read and changed without opening it in the options.
- In **automatic mode** the state is the profile automatic mode holds. Custom
  does not appear there any more.

## Readable keys

### The id becomes readable, it does not go away

[Additional values](additional-values.md) chose a stable id over a name or an
entity id, because a name changes when the value is renamed and every profile
storing under it would stop matching. That reason still holds. What it did not
weigh is the place where people meet the id: a card configuration.

```yaml
hide:
  - afca532463034037803a1d6049c80653
```

says nothing without the definition list next to it. So the id stays stable
and stays the one thing profiles store under - it is just readable now:

```yaml
hide: [kindersicherung]
```

It is formed once, from the name, when the value is added: Home Assistant's
`slugify`, so "Lüfterstufe" becomes `lufterstufe`. Renaming the value later
does not touch it. That is the split Home Assistant itself makes between an
entity id and a friendly name.

The device's name is left out of it. A name pre-filled from the entity is its
friendly name, and that starts with the device's: "Better Thermostat Bad
Heizung Kindersicherung" would make a key nobody wants to type into `hide`.
The value belongs to this entry's device anyway, so the key is
`kindersicherung`. A name the user typed rarely starts with the device's and
stays whole.

A key that is taken gets a counter (`silent_2`). Taken means another value's
key, one of the four climate keys, or a field of a profile's row - a value
called "Color" would otherwise share its field with the profile's colour.

The key cannot be edited. An editable key is a name again, with every reason
against names. The values step lists the keys, so it is clear what to write
into a card.

### Migration

Stored ids are uuids, and three places hold them: the definitions, the values
of every profile and the apply order. All three are rewritten once, when the
entry is loaded, through Home Assistant's config entry migration (version 1 to
2).

Dashboards cannot be rewritten: they are not the integration's. So each
migrated value remembers its old id, and everything that takes a key - `hide`
on the card, `set_value`, `capture_profile` - accepts it as well. That costs a
field in the options and nothing else, and a dashboard nobody touches keeps
working.

There is no way back. A 2.x installation reading migrated options finds keys
it takes for ids of values that do not exist, and every profile loses its
additional values. Hence a major version, and betas first.

## Value entities

### What they are for

Seeing what a profile sets means opening it in the options, and so does
changing one number. With six profiles that is six forms to compare two
temperatures.

### One entity per value a profile sets

Not per value the entry knows. A profile that does not set the fan has no fan
entity: what is visible on the device page is exactly what each profile does.
A value that is taken out of a profile takes its entity with it; one put in
brings it. Putting values in and taking them out stays in the options -
"not set" has no state an entity could show.

| Value | Entity | Range |
| --- | --- | --- |
| `temperature` | `number` | the climate entity's min, max and step |
| `hvac_mode`, `fan_mode`, `swing_mode` | `select` | what the device offers |
| additional, number domains | `number` | the entity's min, max and step |
| additional, boolean domains | `switch` | - |
| additional, select domains | `select` | the entity's options |

They are named after the profile and the value - "Komfort Temperatur" - and
registered as `{entry}_value_{profile id}_{key}`, so renaming a profile renames
the entity but keeps its entity id. They are enabled and in the configuration
category: on the device page they sit together under Configuration, and they
stay off generated dashboards.

Hidden profiles get them too. Hiding is about what the card offers, not about
what can be edited.

### Writing

A change is stored in the profile. When the profile is the active one, it is
applied as well: a profile whose temperature was just raised is still the
profile, and leaving the device behind would make it custom the moment the
change is stored.

Write protection does not apply. It keeps changes made by hand on the device
out of a profile; an entity that is the profile's value is a deliberate
change, like the options.

A stored value the device no longer offers - an option it dropped, a number
out of its range - is not something to pick. The entity reports `unknown`
rather than a value that cannot be chosen.

## Automatic mode holds, it does not detect

### What happened

With automatic mode on, custom was still the state whenever the device did not
match the profile it was told to hold. In practice that was the moments after
a switch: the sensor names a new profile, the integration writes it, and until
the device has reported every value the state is custom - up to 45 seconds on a
radiator, several times a night as a door opened and closed.

### What the state means now

While automatic mode is on, the active profile is the one it holds:

1. a temporary profile while one runs,
2. otherwise the profile the sensor names,
3. otherwise, while the sensor names none, the one held last,
4. otherwise - nothing held yet, after a restart - `unknown`.

Custom is not among them: not as the state, not as an option of the select.

This turns a rule of the [architecture](architecture.md) around on purpose.
Outside automatic mode the state says what the device is doing, "optimistic,
then honest". In automatic mode the state says what is meant to be: the
automatic mode decides which profile applies, and a state that kept saying
custom about it was answering a question nobody asked.

### A deviation is shown, not hidden and not fought

The device can still differ from the profile held: a write protected profile
and the thermostat's own buttons, a value the device did not keep. That is
reported as the `deviates` attribute, a list of the keys that differ, and the
card puts a dot next to the profile name.

Not while a profile is being applied or a change is on its way into one -
those differences are the next seconds, not a deviation.

The alternative - writing the profile back - was rejected: it fights the
device, and a thermostat's own window detection is exactly what it would
fight.

### After a restart

Automatic mode remembers what it held. The profile it holds is the reference
point for changes made by hand, also right after a restart, where the
integration used to have none and stayed custom.
