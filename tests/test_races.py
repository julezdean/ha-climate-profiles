"""Tests around slow devices and concurrent users."""

from __future__ import annotations

import asyncio

from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.climate_profiles.const import DOMAIN

from .conftest import set_device_state, settle
from .test_integration import SENSOR, setup_entry


def slow_service(
    hass: HomeAssistant, domain: str, service: str, delay: float, log: list
):
    """Register a service that takes its time, like a real air conditioner."""

    async def handler(call: ServiceCall) -> None:
        await asyncio.sleep(delay)
        log.append(call)

    hass.services.async_register(domain, service, handler)
    return log


async def test_the_second_request_wins(hass, entry_data):
    """Two users tapping two profiles must not interleave into a third state."""
    set_device_state(hass, temperature=26)
    await setup_entry(hass, entry_data)

    log: list[ServiceCall] = []
    slow_service(hass, "climate", "set_temperature", 0.15, log)

    first = hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": SENSOR, "profile": "Komfort"},
        blocking=True,
    )
    await asyncio.sleep(0.02)
    second = hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": SENSOR, "profile": "Kuehlung"},
        blocking=True,
    )

    # Neither caller sees an error, even though the first one was superseded.
    await asyncio.gather(first, second)
    await settle(hass)

    assert log, "no temperature was written at all"
    assert log[-1].data["temperature"] == 22  # the profile asked for last


async def test_the_card_sees_the_target_while_the_device_catches_up(hass, entry_data):
    """The sensor shows the applied profile immediately, not after the device."""
    set_device_state(hass, temperature=26)
    await setup_entry(hass, entry_data)

    log: list[ServiceCall] = []
    slow_service(hass, "climate", "set_temperature", 0.3, log)

    task = hass.async_create_task(
        hass.services.async_call(
            DOMAIN,
            "apply_profile",
            {"entity_id": SENSOR, "profile": "Komfort"},
            blocking=True,
        )
    )
    await asyncio.sleep(0.1)

    state = hass.states.get(SENSOR)
    assert state.state == "Komfort"
    assert state.attributes["applying"] is True

    await task
    await settle(hass)
    # The device never actually moved, so the optimistic value is given up.
    assert hass.states.get(SENSOR).state == "Benutzerdefiniert"


async def test_a_burst_of_state_changes_is_collapsed(hass, entry_data):
    """Half applied intermediate states must not flicker through the sensor."""
    set_device_state(hass, hvac_mode="off")
    await setup_entry(hass, entry_data)
    await settle(hass)

    seen: list[str] = []
    hass.bus.async_listen(
        "state_changed",
        lambda event: (
            seen.append(event.data["new_state"].state)
            if event.data["entity_id"] == SENSOR
            else None
        ),
    )

    # The device reports its new values one attribute at a time.
    set_device_state(hass, hvac_mode="cool", temperature=26, fan_mode="high")
    set_device_state(hass, hvac_mode="cool", temperature=24, fan_mode="high")
    set_device_state(hass, hvac_mode="cool", temperature=24, fan_mode="auto")
    await settle(hass)

    assert hass.states.get(SENSOR).state == "Komfort"
    assert seen == ["Komfort"], f"sensor flickered through {seen}"


async def test_unloading_during_an_apply_is_clean(hass, entry_data):
    set_device_state(hass, temperature=26)
    entry = await setup_entry(hass, entry_data)

    slow_service(hass, "climate", "set_temperature", 0.3, [])
    task = hass.async_create_task(
        hass.services.async_call(
            DOMAIN,
            "apply_profile",
            {"entity_id": SENSOR, "profile": "Komfort"},
            blocking=True,
        )
    )
    await asyncio.sleep(0.05)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await task  # the caller is not left hanging
