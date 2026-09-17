"""Shared fixtures for the Climate Profiles tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.climate_profiles.models import (
    AdditionalValue,
    AdditionalValueSet,
    Capabilities,
    ClimateProfile,
    EntityMap,
    ProfileSet,
    Vocabulary,
)

CLIMATE = "climate.living_room"
FAN = "number.living_room_fan_speed"
DISPLAY = "switch.living_room_display"
SILENT = "switch.living_room_silent"

#: Ids of the additional values used throughout the tests. Production hands out
#: uuids; an id is just a string, so the tests use speaking ones and stay
#: readable.
FAN_ID = "fan"
DISPLAY_ID = "display"
SILENT_ID = "silent"


@pytest.fixture
def additional() -> AdditionalValueSet:
    """Return the three additional values of the reference device."""
    return AdditionalValueSet(
        (
            AdditionalValue(id=FAN_ID, name="Fan speed", entity=FAN, order=0),
            AdditionalValue(id=DISPLAY_ID, name="Display", entity=DISPLAY, order=1),
            AdditionalValue(id=SILENT_ID, name="Silent", entity=SILENT, order=2),
        )
    )


@pytest.fixture
def entities(additional: AdditionalValueSet) -> EntityMap:
    """Return a fully equipped device."""
    return EntityMap(climate=CLIMATE, additional=additional)


@pytest.fixture
def bare_entities() -> EntityMap:
    """Return a device with nothing but a climate entity."""
    return EntityMap(climate=CLIMATE)


@pytest.fixture
def caps() -> Capabilities:
    """Return capabilities modelled after the Midea PortaSplit reference."""
    return Capabilities(
        hvac_modes=("off", "cool", "dry", "fan_only", "heat", "auto"),
        fan_modes=("auto", "silent", "low", "medium", "high", "full"),
        swing_modes=("off", "vertical", "horizontal", "both"),
        min_temp=16.0,
        max_temp=30.0,
        temp_step=1.0,
    )


#: What the additional entities say about themselves - the coordinator reads
#: this from their states.
ADDITIONAL_SPECS = {FAN_ID: {"min": 1.0, "max": 100.0, "step": 1.0}}


@pytest.fixture
def vocab(entities: EntityMap, caps: Capabilities) -> Vocabulary:
    """Return the vocabulary of a fully equipped device."""
    return Vocabulary.build(entities, caps, additional_specs=ADDITIONAL_SPECS)


@pytest.fixture
def bare_vocab(bare_entities: EntityMap, caps: Capabilities) -> Vocabulary:
    """Return the vocabulary of a device with only a climate entity."""
    return Vocabulary.build(bare_entities, caps)


def profile(name: str, values: dict, profile_id: str | None = None) -> ClimateProfile:
    """Build a profile without going through the config flow."""
    return ClimateProfile(id=profile_id or name.lower(), name=name, values=values)


@pytest.fixture
def profiles() -> ProfileSet:
    """Return the profile set from the original YAML package."""
    return ProfileSet(
        (
            profile("Aus", {"hvac_mode": "off"}),
            profile(
                "Away",
                {
                    "hvac_mode": "cool",
                    "temperature": 26,
                    "swing_mode": "off",
                    "fan_mode": "auto",
                    "display": "off",
                    "silent": "off",
                },
            ),
            profile(
                "Komfort",
                {
                    "hvac_mode": "cool",
                    "temperature": 24,
                    "swing_mode": "off",
                    "fan_mode": "auto",
                    "display": "off",
                    "silent": "off",
                },
            ),
            profile(
                "Nacht",
                {
                    "hvac_mode": "cool",
                    "temperature": 26,
                    "swing_mode": "off",
                    "display": "off",
                    "silent": "on",
                },
            ),
            profile(
                "Max",
                {
                    "hvac_mode": "cool",
                    "temperature": 16,
                    "swing_mode": "vertical",
                    "fan": 100,
                    "display": "off",
                    "silent": "off",
                },
            ),
        )
    )


@pytest.fixture
def komfort_state() -> dict:
    """Return current values that match the "Komfort" profile."""
    return {
        "hvac_mode": "cool",
        "temperature": 24.0,
        "swing_mode": "off",
        "fan_mode": "auto",
        "fan": 42,
        "display": "off",
        "silent": "off",
    }


# ---------------------------------------------------------------------------
# Home Assistant fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""
    return


@pytest.fixture
def entry_data() -> dict:
    """Config entry data for a fully equipped device."""
    from custom_components.climate_profiles.const import CONF_CLIMATE_ENTITY

    return {CONF_CLIMATE_ENTITY: CLIMATE}


def additional_option() -> list[dict]:
    """Return the additional values as a config entry stores them."""
    return [
        {"id": FAN_ID, "name": "Fan speed", "entity": FAN, "order": 0},
        {"id": DISPLAY_ID, "name": "Display", "entity": DISPLAY, "order": 1},
        {"id": SILENT_ID, "name": "Silent", "entity": SILENT, "order": 2},
    ]


def set_device_state(
    hass,
    *,
    hvac_mode: str = "cool",
    temperature: float = 24,
    fan_mode: str = "auto",
    swing_mode: str = "off",
    fan: float = 42,
    display: str = "off",
    silent: str = "off",
) -> None:
    """Put the mocked device into a defined state."""
    hass.states.async_set(
        CLIMATE,
        hvac_mode,
        {
            "temperature": temperature,
            "current_temperature": 25.4,
            "fan_mode": fan_mode,
            "swing_mode": swing_mode,
            "hvac_modes": ["off", "cool", "dry", "fan_only", "heat", "auto"],
            "fan_modes": ["auto", "silent", "low", "medium", "high", "full"],
            "swing_modes": ["off", "vertical", "horizontal", "both"],
            "min_temp": 16,
            "max_temp": 30,
            "target_temp_step": 1,
        },
    )
    hass.states.async_set(FAN, str(fan), {"min": 1, "max": 100, "step": 1})
    hass.states.async_set(DISPLAY, display)
    hass.states.async_set(SILENT, silent)


async def settle(hass) -> None:
    """Wait out the coordinator's debounce and let the updates land.

    The debouncer schedules through ``loop.call_later``, so freezing time does
    not help here - the test really has to wait the cooldown out.
    """
    import asyncio

    from custom_components.climate_profiles.const import RECALC_DEBOUNCE_SECONDS

    await hass.async_block_till_done()
    await asyncio.sleep(RECALC_DEBOUNCE_SECONDS + 0.2)
    await hass.async_block_till_done()
