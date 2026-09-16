"""Shared fixtures for the Climate Profiles tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_components.climate_profiles.models import (
    Capabilities,
    ClimateProfile,
    EntityMap,
    ProfileSet,
)

CLIMATE = "climate.wohnzimmer"
FAN = "number.wohnzimmer_luftergeschwindigkeit"
DISPLAY = "switch.wohnzimmer_gerateanzeige"
SILENT = "switch.wohnzimmer_flustermodus"


@pytest.fixture
def entities() -> EntityMap:
    """Return a fully equipped device."""
    return EntityMap(climate=CLIMATE, fan=FAN, display=DISPLAY, silent=SILENT)


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
        fan_min=1.0,
        fan_max=100.0,
        fan_step=1.0,
    )


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
    from custom_components.climate_profiles.const import (
        CONF_CLIMATE_ENTITY,
        CONF_DISPLAY_ENTITY,
        CONF_FAN_ENTITY,
        CONF_SILENT_ENTITY,
    )

    return {
        CONF_CLIMATE_ENTITY: CLIMATE,
        CONF_FAN_ENTITY: FAN,
        CONF_DISPLAY_ENTITY: DISPLAY,
        CONF_SILENT_ENTITY: SILENT,
    }


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
