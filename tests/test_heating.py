"""The integration must work for any climate entity, not just air conditioners.

A radiator thermostat is the opposite end of the range: no fan modes, no swing
modes, no extra switches, a much wider temperature range and half degree steps.
"""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.climate_profiles.config_flow import build_default_profiles
from custom_components.climate_profiles.const import (
    CONF_ADDITIONAL,
    CONF_CLIMATE_ENTITY,
    DOMAIN,
)
from custom_components.climate_profiles.models import Capabilities

from .conftest import settle
from .test_integration import setup_entry

HEATER = "climate.living_room_radiator"
SENSOR = "sensor.radiator_climate_profile"

HEATING_PROFILES = [
    {"id": "off", "name": "Aus", "color": "#64748b", "values": {"hvac_mode": "off"}},
    {
        "id": "eco",
        "name": "Absenkung",
        "color": "#3b82f6",
        "values": {"hvac_mode": "heat", "temperature": 17},
    },
    {
        "id": "komfort",
        "name": "Komfort",
        "color": "#ef4444",
        "values": {"hvac_mode": "heat", "temperature": 21.5},
    },
]


def set_heater(hass, *, hvac_mode: str = "heat", temperature: float = 21.5) -> None:
    """Put a thermostat that offers nothing but a mode and a target in place."""
    hass.states.async_set(
        HEATER,
        hvac_mode,
        {
            "temperature": temperature,
            "current_temperature": 20.2,
            "hvac_action": "heating" if hvac_mode == "heat" else "off",
            "hvac_modes": ["off", "heat", "auto"],
            "preset_modes": ["eco", "comfort", "boost"],
            "preset_mode": "comfort",
            "min_temp": 5,
            "max_temp": 35,
            "target_temp_step": 0.5,
            # deliberately no fan_modes / swing_modes
        },
    )


async def setup_heater(hass, **kwargs):
    """Set up an entry for the thermostat."""
    kwargs.setdefault("profiles", HEATING_PROFILES)
    kwargs.setdefault("options", {CONF_ADDITIONAL: []})
    return await setup_entry(
        hass, {CONF_CLIMATE_ENTITY: HEATER}, title="Radiator", **kwargs
    )


async def test_a_thermostat_gets_the_same_profiles(hass):
    set_heater(hass)
    await setup_heater(hass)

    state = hass.states.get(SENSOR)
    assert state.state == "Komfort"
    caps = state.attributes["capabilities"]
    # Nothing invented for values the device does not have.
    assert caps["fan_modes"] == []
    assert caps["swing_modes"] == []
    assert (caps["min_temp"], caps["max_temp"], caps["target_temp_step"]) == (
        5,
        35,
        0.5,
    )
    assert state.attributes["entities"] == {"climate": HEATER, "additional": {}}


async def test_half_degree_steps_are_compared_correctly(hass):
    """Tolerance is half the device's step, so 0.5 apart is a different state."""
    set_heater(hass, temperature=21.5)
    await setup_heater(hass)
    assert hass.states.get(SENSOR).state == "Komfort"

    set_heater(hass, temperature=21.0)
    await settle(hass)
    assert hass.states.get(SENSOR).state == "Custom"


async def test_applying_a_heating_profile(hass):
    set_heater(hass, hvac_mode="off")
    await setup_heater(hass)

    mode = async_mock_service(hass, "climate", "set_hvac_mode")
    temp = async_mock_service(hass, "climate", "set_temperature")
    fan = async_mock_service(hass, "climate", "set_fan_mode")

    await hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": SENSOR, "profile": "Absenkung"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert mode[0].data["hvac_mode"] == "heat"
    assert temp[0].data["temperature"] == 17
    assert not fan, "a thermostat has no fan mode to set"


async def test_a_mode_the_thermostat_lacks_is_refused(hass):
    """Cooling on a radiator is reported, not sent and silently ignored."""
    set_heater(hass)
    await setup_heater(
        hass,
        profiles=[
            {
                "id": "x",
                "name": "Kuehlen",
                "color": "#3b82f6",
                "values": {"hvac_mode": "cool", "temperature": 20},
            },
        ],
    )
    mode = async_mock_service(hass, "climate", "set_hvac_mode")
    temp = async_mock_service(hass, "climate", "set_temperature")

    await hass.services.async_call(
        DOMAIN,
        "apply_profile",
        {"entity_id": SENSOR, "profile": "Kuehlen"},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert not mode, "cool is not in hvac_modes, so it must not be sent"
    assert temp[0].data["temperature"] == 20, "the rest of the profile still applies"


def test_starter_profiles_for_a_heating_only_device():
    """The blueprint is cooling shaped - a heater gets what fits, not nonsense."""
    caps = Capabilities(
        hvac_modes=("off", "heat", "auto"), min_temp=5, max_temp=35, temp_step=0.5
    )
    profiles = build_default_profiles(caps)
    assert [p.name for p in profiles] == ["Off"]


# --- known limitations -----------------------------------------------------
#
# These two tests pin down what the integration does NOT cover, so the gap is
# visible instead of surprising. If support is added later, they fail and say
# so.


async def test_preset_mode_is_not_a_profile_value(hass):
    """Many thermostats expose preset_mode (eco/comfort/boost) - not covered.

    Profiles can still set the temperature those presets stand for; they just
    cannot switch the device's own preset.
    """
    set_heater(hass)
    await setup_heater(hass)

    state = hass.states.get(SENSOR)
    assert "preset_mode" not in state.attributes["current_values"]
    assert "preset_mode" not in state.attributes["capabilities"]


async def test_a_range_thermostat_never_matches_a_temperature(hass):
    """Devices in heat_cool report target_temp_low/high instead of temperature.

    The integration reads `temperature`, which such a device leaves empty, so a
    profile defining a temperature can never match - the state stays custom
    rather than claiming a match that is not there.
    """
    hass.states.async_set(
        HEATER,
        "heat_cool",
        {
            "target_temp_low": 19,
            "target_temp_high": 24,
            "current_temperature": 21,
            "hvac_modes": ["off", "heat_cool"],
            "min_temp": 5,
            "max_temp": 35,
            "target_temp_step": 0.5,
        },
    )
    await setup_heater(
        hass,
        profiles=[
            {
                "id": "r",
                "name": "Bereich",
                "color": "#3b82f6",
                "values": {"hvac_mode": "heat_cool", "temperature": 21},
            },
        ],
    )
    assert hass.states.get(SENSOR).state == "Custom"
