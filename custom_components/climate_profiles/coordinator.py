"""Coordinator: reads the device states, decides which profile is active.

This is the server side source of truth. Automations, voice assistants, the
developer tools and the Lovelace card all see the same answer because they all
ask this object.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CLIMATE_KINDS,
    CONF_ADDITIONAL,
    CONF_CUSTOM_NAME,
    CONF_PROFILES,
    CONF_VALUE_ORDER,
    CUSTOM_PROFILE_ID,
    DEFAULT_CUSTOM_COLOR,
    DEFAULT_CUSTOM_NAME,
    DOMAIN,
    REACH_MAX_SECONDS,
    REACH_QUIET_SECONDS,
    RECALC_DEBOUNCE_SECONDS,
    VALUE_FAN_MODE,
    VALUE_HVAC_MODE,
    VALUE_SWING_MODE,
    VALUE_TEMPERATURE,
)
from .matching import (
    ApplyPlan,
    build_apply_plan,
    capture_values,
    changed_keys,
    normalise_values,
    resolve_active_profile,
    storage_value,
    values_equal,
)
from .models import (
    AdditionalValueSet,
    Capabilities,
    ClimateProfile,
    EntityMap,
    ProfileError,
    ProfileSet,
    Vocabulary,
    new_profile_id,
    normalise_color,
)

_LOGGER = logging.getLogger(__name__)

type ClimateProfilesConfigEntry = ConfigEntry[ClimateProfilesCoordinator]


@dataclass(frozen=True, slots=True)
class Unreached:
    """A profile that was applied, but that the device did not keep.

    Two values of one profile can contradict each other on a real device - a
    silent mode that forces its own fan speed makes "fan full, silent on"
    impossible. The integration cannot know that, it is device knowledge. It
    can only see the result, and say so instead of ending on a silent "custom".
    """

    profile_id: str
    profile: str
    #: key -> (wanted, actual), both in the form profiles store them.
    values: dict[str, tuple[Any, Any]]

    def as_dict(self) -> dict[str, Any]:
        """Return a representation for the frontend and for automations."""
        return {
            "profile_id": self.profile_id,
            "profile": self.profile,
            "values": {
                key: {"wanted": wanted, "actual": actual}
                for key, (wanted, actual) in self.values.items()
            },
        }


@dataclass(frozen=True, slots=True)
class ProfileState:
    """Everything the entities and the card need to render."""

    active: ClimateProfile | None
    values: dict[str, Any]
    capabilities: Capabilities
    #: What this entry knows: the four climate keys plus the additional
    #: values, with the kind and limits each one is compared against.
    vocabulary: Vocabulary
    available: bool
    applying: bool = False
    #: The profile that matched most recently in this session, and which of
    #: its values have been changed by hand since. Both are runtime only -
    #: after a restart there is no reference point, and "custom" stays custom.
    last_matched: ClimateProfile | None = None
    changed: tuple[str, ...] = ()
    unreached: Unreached | None = None

    @property
    def active_id(self) -> str:
        """Return the id of the active profile, or the custom sentinel."""
        return self.active.id if self.active else CUSTOM_PROFILE_ID


class ClimateProfilesCoordinator(DataUpdateCoordinator[ProfileState]):
    """Keeps the active profile in sync with the underlying entities."""

    config_entry: ClimateProfilesConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ClimateProfilesConfigEntry) -> None:
        """Set up the coordinator for one configured device."""
        super().__init__(
            hass,
            _LOGGER,
            name=entry.title,
            config_entry=entry,
            # No polling: every source is a local push entity. The debouncer
            # collapses the burst of state changes a climate device emits
            # while it works through a profile.
            update_interval=None,
            request_refresh_debouncer=Debouncer(
                hass,
                _LOGGER,
                cooldown=RECALC_DEBOUNCE_SECONDS,
                immediate=False,
            ),
        )
        self.entities = EntityMap.from_config(entry.data, self._read_additional())
        self._apply_task: asyncio.Task[None] | None = None
        #: (profile id, values at the time it became active) - the baseline
        #: "capture" uses to tell a deliberate change from an untouched value.
        self._baseline: tuple[str, dict[str, Any]] | None = None
        #: Set when the next recalculation should start a fresh baseline,
        #: i.e. after we wrote the state ourselves.
        self._renew_baseline = False
        #: The profile last applied, until it is either matched or judged
        #: unreached - and when the device was last touched or last moved.
        self._target: ClimateProfile | None = None
        self._last_call = 0.0
        self._last_change = 0.0
        self._reach_timer: Any = None
        self._unreached: Unreached | None = None

    # -- configuration ------------------------------------------------------

    def _read_additional(self) -> AdditionalValueSet:
        """Return the configured additional values.

        Unlike the climate entity these are preference, not identity, so they
        live in the options - and a change to them has to reload the entry,
        because a different set of entities has to be listened to.
        """
        try:
            return AdditionalValueSet.from_list(
                self.config_entry.options.get(CONF_ADDITIONAL)
            )
        except ProfileError as err:
            _LOGGER.error(
                "Invalid additional values for %s: %s", self.config_entry.title, err
            )
            return AdditionalValueSet()

    @property
    def value_order(self) -> list[str]:
        """Return the configured apply order (without ``hvac_mode``)."""
        return list(self.config_entry.options.get(CONF_VALUE_ORDER) or [])

    @property
    def additional(self) -> AdditionalValueSet:
        """Return the configured additional values."""
        return self.entities.additional

    @property
    def profiles(self) -> ProfileSet:
        """Return the stored profiles, in their configured order."""
        try:
            return ProfileSet.from_list(self.config_entry.options.get(CONF_PROFILES))
        except ProfileError as err:
            _LOGGER.error("Invalid profile configuration for %s: %s", self.name, err)
            return ProfileSet()

    @property
    def custom_name(self) -> str:
        """Return the display name of the virtual "custom" profile."""
        return (
            self.config_entry.options.get(CONF_CUSTOM_NAME) or DEFAULT_CUSTOM_NAME
        ).strip() or DEFAULT_CUSTOM_NAME

    def profile_name(self, profile: ClimateProfile | None) -> str:
        """Return the display name of ``profile`` (custom when ``None``)."""
        if profile is None:
            return self.custom_name
        return self.profiles.display_names().get(profile.id, profile.name)

    def profile_color(self, profile: ClimateProfile | None) -> str:
        """Return the colour of ``profile`` (neutral when custom)."""
        return DEFAULT_CUSTOM_COLOR if profile is None else profile.color

    # -- reading the world --------------------------------------------------

    @callback
    def _read_values(self) -> tuple[dict[str, Any], bool]:
        """Read the current values of all configured entities."""
        values: dict[str, Any] = {}
        climate = self.hass.states.get(self.entities.climate)
        available = climate is not None and climate.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        )

        if climate is not None:
            values[VALUE_HVAC_MODE] = climate.state
            values[VALUE_TEMPERATURE] = climate.attributes.get("temperature")
            values[VALUE_FAN_MODE] = climate.attributes.get("fan_mode")
            values[VALUE_SWING_MODE] = climate.attributes.get("swing_mode")

        for value in self.entities.additional:
            if (state := self.hass.states.get(value.entity)) is not None:
                values[value.id] = state.state

        return values, available

    @callback
    def _read_capabilities(self) -> Capabilities:
        """Read what the devices support - never assume any fixed values."""
        climate = self.hass.states.get(self.entities.climate)
        attrs = climate.attributes if climate else {}

        return Capabilities(
            hvac_modes=tuple(str(mode) for mode in attrs.get("hvac_modes") or ()),
            fan_modes=tuple(str(mode) for mode in attrs.get("fan_modes") or ()),
            swing_modes=tuple(str(mode) for mode in attrs.get("swing_modes") or ()),
            min_temp=_as_float(attrs.get("min_temp")),
            max_temp=_as_float(attrs.get("max_temp")),
            temp_step=_as_float(attrs.get("target_temp_step")) or 0.5,
        )

    @callback
    def _read_additional_specs(self) -> dict[str, dict[str, Any]]:
        """Read what each additional entity says about itself.

        The limits of an additional value are not ours to define: a number
        carries ``min``/``max``/``step``, a select carries ``options``. Read
        here, handed to the vocabulary, never assumed.
        """
        specs: dict[str, dict[str, Any]] = {}
        for value in self.entities.additional:
            state = self.hass.states.get(value.entity)
            if state is None:
                continue
            attrs = state.attributes
            specs[value.id] = {
                "min": _as_float(attrs.get("min")),
                "max": _as_float(attrs.get("max")),
                "step": _as_float(attrs.get("step")) or 1.0,
                "options": tuple(str(option) for option in attrs.get("options") or ()),
            }
        return specs

    @callback
    def _read_vocabulary(self) -> Vocabulary:
        """Return what this entry knows about right now."""
        return Vocabulary.build(
            self.entities,
            self._read_capabilities(),
            additional_specs=self._read_additional_specs(),
            order=self.value_order,
        )

    async def _async_update_data(self) -> ProfileState:
        """Recalculate the active profile from the current states."""
        values, available = self._read_values()
        capabilities = self._read_capabilities()
        vocabulary = Vocabulary.build(
            self.entities,
            capabilities,
            additional_specs=self._read_additional_specs(),
            order=self.value_order,
        )
        profiles = self.profiles
        active = resolve_active_profile(profiles, values, vocabulary)
        applying = self._apply_task is not None and not self._apply_task.done()

        # While an applied profile is still on its way, only that one may take
        # the baseline. Right after the calls the device has not reported yet,
        # so the profile you just left still matches for a moment - letting it
        # take the baseline back would count whatever the device does next as
        # a hand edit of the wrong profile.
        pending = self._target is not None and (
            active is None or active.id != self._target.id
        )
        if (
            active is not None
            and not pending
            and (
                self._renew_baseline
                or self._baseline is None
                or self._baseline[0] != active.id
            )
        ):
            # A new reference point, but only when the profile actually
            # changed or we wrote the state ourselves. A partial profile stays
            # active while you adjust a value it does not define - refreshing
            # the baseline there would forget exactly what you just changed.
            self._baseline = (active.id, dict(values))
        self._renew_baseline = False

        if active is not None:
            # Any profile matching now makes a verdict about an earlier one
            # stale; the applied one matching means it simply took.
            self._unreached = None
            if self._target is not None and self._target.id == active.id:
                self._clear_target()

        last_matched = (
            profiles.get(self._baseline[0]) if self._baseline is not None else None
        )
        # Also reported while a profile is still active: a partial profile
        # keeps matching while you adjust a value it does not define, and that
        # is precisely a change worth offering to capture.
        changed = (
            changed_keys(self._baseline[1], values, vocabulary)
            if self._baseline is not None
            else ()
        )
        return ProfileState(
            active,
            values,
            capabilities,
            vocabulary,
            available,
            applying,
            last_matched,
            changed,
            self._unreached,
        )

    # -- lifecycle ----------------------------------------------------------

    async def async_setup(self) -> None:
        """Start listening to the configured entities."""
        self.config_entry.async_on_unload(
            async_track_state_change_event(
                self.hass, self.entities.all_entities(), self._handle_state_change
            )
        )
        self.config_entry.async_on_unload(self._cancel_running_apply)

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        """Schedule a debounced recalculation."""
        if self._target is not None:
            now = self.hass.loop.time()
            self._last_change = now
            # How long a device takes to report what it did is the one number
            # the reach check depends on, and it differs per device. This line
            # is what the waiting times are set from.
            new_state = event.data.get("new_state")
            _LOGGER.debug(
                "%s: %s is %s, %.2f s after the last call",
                self.name,
                event.data.get("entity_id"),
                new_state.state if new_state is not None else None,
                now - self._last_call,
            )
        self.hass.async_create_task(self.async_request_refresh(), eager_start=True)

    @callback
    def _cancel_running_apply(self) -> None:
        """Cancel an in-flight apply, e.g. when the entry is unloaded."""
        if self._apply_task is not None and not self._apply_task.done():
            self._apply_task.cancel()
        self._clear_target()

    # -- did the profile take? ----------------------------------------------

    @callback
    def _clear_target(self) -> None:
        """Stop waiting for the applied profile."""
        self._target = None
        if self._reach_timer is not None:
            self._reach_timer()
            self._reach_timer = None

    @callback
    def _schedule_reach_check(self, delay: float) -> None:
        """Look at the result once the device has been quiet for a while."""
        if self._reach_timer is not None:
            self._reach_timer()
        self._reach_timer = async_call_later(
            self.hass, max(delay, 0.0), self._reach_timer_fired
        )

    @callback
    def _reach_timer_fired(self, _now: Any) -> None:
        """Start the check on the event loop.

        Marked as a callback on purpose: a plain function handed to
        ``async_call_later`` runs in a worker thread, and creating a task from
        there is not thread safe - Home Assistant refuses it outright.
        """
        self._reach_timer = None
        self.hass.async_create_task(self._async_check_reached())

    async def _async_check_reached(self) -> None:
        """Judge whether the applied profile took, once the device is quiet.

        Quiet means no state change for ``REACH_QUIET_SECONDS``, but never
        later than ``REACH_MAX_SECONDS`` after the last call: a device that
        keeps reporting must not postpone the verdict forever.
        """
        target = self._target
        if target is None:
            return

        now = self.hass.loop.time()
        quiet_for = now - max(self._last_call, self._last_change)
        if (
            quiet_for < REACH_QUIET_SECONDS
            and now - self._last_call < REACH_MAX_SECONDS
        ):
            self._schedule_reach_check(REACH_QUIET_SECONDS - quiet_for)
            return

        await self.async_refresh()
        state = self.data
        if state is None or self._target is None:
            return
        self._target = None
        if state.active is not None and state.active.id == target.id:
            return

        vocab = state.vocabulary
        wanted = normalise_values(vocab, target.values)
        current = normalise_values(vocab, state.values)
        missed = {
            key: (
                storage_value(vocab.get(key), value),
                storage_value(vocab.get(key), current.get(key)),
            )
            for key, value in wanted.items()
            if not values_equal(vocab.get(key), value, current.get(key))
        }
        if not missed:
            return

        self._unreached = Unreached(target.id, target.name, missed)
        _LOGGER.warning(
            "%s: profile %s was applied but did not take - %s. Two of its "
            "values probably contradict each other on this device",
            self.name,
            target.name,
            ", ".join(
                f"{key} is {actual} instead of {wanted}"
                for key, (wanted, actual) in missed.items()
            ),
        )
        self.async_set_updated_data(replace(state, unreached=self._unreached))

    # -- writing ------------------------------------------------------------

    async def async_apply_profile(self, reference: str) -> None:
        """Apply the profile named or identified by ``reference``.

        Only the values the profile defines are written; everything else keeps
        whatever it currently has.
        """
        if _is_custom_reference(reference, self.custom_name):
            # "Custom" is a status, not a preset - it never writes anything.
            _LOGGER.debug("Ignoring request to apply the virtual custom profile")
            await self.async_request_refresh()
            return

        profile = self.profiles.resolve(reference)
        if profile is None:
            known = ", ".join(p.name for p in self.profiles) or "-"
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_profile",
                translation_placeholders={"profile": reference, "known": known},
            )

        # Applying a profile leaves the one you were in. Whatever differs from
        # that one afterwards is not a hand edit of it - without this, a
        # profile the device cannot keep would be offered for capture into the
        # previous profile.
        self._baseline = None
        self._unreached = None
        self._clear_target()
        self._target = profile
        await self._async_run_apply(profile.values, optimistic=profile)

    @callback
    def resolve_value_keys(self, values: Mapping[str, Any]) -> dict[str, Any]:
        """Return ``values`` with every key resolved to what it addresses.

        The four climate keys pass through. Everything else is an additional
        value, addressed by its id or by its name - the same rule profiles
        follow, and the reason ids win: a value literally named like another
        one's id cannot shadow it.
        """
        resolved: dict[str, Any] = {}
        unknown: list[str] = []
        for key, value in values.items():
            if key in CLIMATE_KINDS:
                resolved[key] = value
                continue
            if (found := self.additional.resolve(key)) is not None:
                resolved[found.id] = value
                continue
            unknown.append(key)

        if unknown:
            known = ", ".join([*CLIMATE_KINDS, *(v.name for v in self.additional)])
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_value",
                translation_placeholders={
                    "value": ", ".join(sorted(unknown)),
                    "known": known,
                },
            )
        return resolved

    async def async_set_values(self, values: dict[str, Any]) -> None:
        """Write individual values, then re-evaluate which profile that is."""
        if not values:
            return
        await self._async_run_apply(values, optimistic=None)

    # -- capturing ----------------------------------------------------------

    async def async_capture_into_profile(
        self, reference: str | None = None, keys: list[str] | None = None
    ) -> ClimateProfile:
        """Write the current state into a stored profile.

        Without ``reference`` the profile that matched most recently in this
        session is used - the one you were "in" before adjusting something.
        """
        profiles = self.profiles
        state = self.data or await self._async_update_data()

        target = profiles.resolve(reference) if reference else state.last_matched

        if target is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_capture_target"
                if not reference
                else "unknown_profile",
                translation_placeholders={
                    "profile": reference or "-",
                    "known": ", ".join(p.name for p in profiles) or "-",
                },
            )
        if target.protected:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="profile_protected",
                translation_placeholders={"profile": target.name},
            )

        baseline = (
            self._baseline[1]
            if self._baseline is not None and self._baseline[0] == target.id
            else None
        )
        values = capture_values(
            target.values,
            state.values,
            state.vocabulary,
            baseline=baseline,
            keys=keys,
        )
        updated = target.with_values(values)
        _LOGGER.debug("Captured %s into %s", values, updated.name)
        self._renew_baseline = True
        self._store(profiles.replaced(updated))
        return updated

    async def async_save_as_profile(
        self,
        name: str,
        *,
        color: str | None = None,
        icon: str | None = None,
        keys: list[str] | None = None,
    ) -> ClimateProfile:
        """Store the current state as a new profile.

        A new profile captures everything that is readable, not just what
        changed: it describes the state as a whole, with nothing to inherit.
        """
        name = (name or "").strip()
        if not name:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="profile_needs_a_name"
            )

        state = self.data or await self._async_update_data()
        values = capture_values(
            {},
            state.values,
            state.vocabulary,
            keys=list(keys) if keys else list(state.vocabulary.keys()),
        )
        if not values:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="nothing_to_capture"
            )

        profile = ClimateProfile(
            id=new_profile_id(),
            name=name,
            color=normalise_color(color),
            values=values,
            icon=icon or None,
        )
        _LOGGER.debug("Saved the current state as %s", profile.name)
        self._renew_baseline = True
        self._store(self.profiles.appended(profile))
        return profile

    @callback
    def _store(self, profiles: ProfileSet) -> None:
        """Persist ``profiles`` in the config entry's options."""
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            options={**self.config_entry.options, CONF_PROFILES: profiles.as_list()},
        )

    async def _async_run_apply(
        self, values: dict[str, Any], *, optimistic: ClimateProfile | None
    ) -> None:
        """Run an apply, replacing an already running one.

        Replacing rather than queueing mirrors the ``mode: restart`` of the
        original script: when two users tap two profiles, the second one wins
        instead of the two interleaving.
        """
        await self._async_cancel_apply()

        task = self.config_entry.async_create_task(
            self.hass,
            self._async_apply(values, optimistic),
            name=f"{DOMAIN} apply {self.config_entry.entry_id}",
        )
        self._apply_task = task
        try:
            await task
        except asyncio.CancelledError:
            # Superseded by a newer request - not an error for the caller.
            _LOGGER.debug("Apply for %s was superseded", self.name)

    async def _async_cancel_apply(self) -> None:
        """Wait for a running apply to actually stop."""
        task = self._apply_task
        if task is None or task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _async_apply(
        self, values: dict[str, Any], optimistic: ClimateProfile | None
    ) -> None:
        """Execute the plan for ``values``."""
        state = self.data or await self._async_update_data()
        plan = build_apply_plan(values, state.values, state.vocabulary)
        self._log_plan(plan)

        if optimistic is not None or plan.calls:
            # Show the target immediately; the state updates trickle in later.
            self.async_set_updated_data(
                replace(
                    state,
                    active=optimistic if optimistic is not None else state.active,
                    applying=True,
                )
            )

        try:
            for call in plan.calls:
                _LOGGER.debug(
                    "%s: %s.%s on %s with %s",
                    self.name,
                    call.domain,
                    call.service,
                    call.entity_id,
                    call.data,
                )
                await self.hass.services.async_call(
                    call.domain,
                    call.service,
                    {ATTR_ENTITY_ID: call.entity_id, **call.data},
                    blocking=True,
                )
        except HomeAssistantError as err:
            _LOGGER.error("Applying values to %s failed: %s", self.name, err)
            self._clear_target()
            raise
        finally:
            self._apply_task = None
            self._renew_baseline = True
            await self.async_refresh()

        if optimistic is not None and self._target is optimistic:
            self._last_call = self._last_change = self.hass.loop.time()
            self._schedule_reach_check(REACH_QUIET_SECONDS)

    def _log_plan(self, plan: ApplyPlan) -> None:
        """Tell the user about values that could not be applied cleanly."""
        if plan.unsupported:
            _LOGGER.warning(
                "%s: skipping %s - not supported by the configured entities",
                self.name,
                ", ".join(plan.unsupported),
            )
        if plan.warnings:
            _LOGGER.warning(
                "%s: %s is outside the range the device currently reports",
                self.name,
                ", ".join(plan.warnings),
            )


def _is_custom_reference(reference: str, custom_name: str) -> bool:
    """Return whether ``reference`` points at the virtual custom profile."""
    wanted = (reference or "").strip().casefold()
    return wanted in {
        CUSTOM_PROFILE_ID,
        custom_name.casefold(),
        DEFAULT_CUSTOM_NAME.casefold(),
    }


def _as_float(raw: Any) -> float | None:
    """Return ``raw`` as a float, or ``None``."""
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
