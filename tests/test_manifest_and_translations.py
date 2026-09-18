"""Guards for the files Home Assistant reads but Python never imports."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from custom_components.climate_profiles.const import (
    CLIMATE_KEYS,
    DOMAIN,
    SERVICE_APPLY_PROFILE,
    SERVICE_CAPTURE_PROFILE,
    SERVICE_SAVE_AS_PROFILE,
    SERVICE_SET_VALUE,
)

COMPONENT = (
    Path(__file__).resolve().parents[1] / "custom_components" / "climate_profiles"
)


def load_json(name: str) -> dict:
    """Return a JSON file of the integration."""
    return json.loads((COMPONENT / name).read_text(encoding="utf-8"))


def flat_keys(data, prefix: str = "") -> set[str]:
    """Return every leaf path of a nested mapping."""
    keys: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys |= flat_keys(value, path)
        else:
            keys.add(path)
    return keys


def test_manifest_is_complete():
    manifest = load_json("manifest.json")
    assert manifest["domain"] == DOMAIN
    assert manifest["config_flow"] is True
    assert manifest["version"], "HACS refuses an integration without a version"
    assert manifest["documentation"].startswith("http")
    # The integration works without a frontend, so it must not hard depend on
    # one - see the frontend registration in __init__.py.
    assert "frontend" not in manifest["dependencies"]
    assert "frontend" in manifest["after_dependencies"]


def test_no_placeholders_are_left():
    """A placeholder URL passes hassfest but sends users nowhere."""
    manifest = load_json("manifest.json")
    assert manifest["codeowners"], "HACS shows the codeowner as the maintainer"
    card = (COMPONENT / "frontend" / "climate-profile-card.js").read_text(
        encoding="utf-8"
    )
    for text in (json.dumps(manifest), card):
        assert "CHANGEME" not in text

    # The card's link and the manifest's must not drift apart.
    link = re.search(r'documentationURL:\s*"([^"]+)"', card)
    assert link is not None
    assert link.group(1) == manifest["documentation"]
    assert manifest["issue_tracker"].startswith(manifest["documentation"])


def test_services_match_the_code():
    services = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))
    assert set(services) == {
        SERVICE_APPLY_PROFILE,
        SERVICE_SET_VALUE,
        SERVICE_CAPTURE_PROFILE,
        SERVICE_SAVE_AS_PROFILE,
    }
    # Only the climate keys are documented: an additional value is named by
    # the user, so it cannot appear in a static service definition.
    assert set(services[SERVICE_SET_VALUE]["fields"]) == set(CLIMATE_KEYS)
    assert services[SERVICE_APPLY_PROFILE]["fields"]["profile"]["required"] is True


def test_every_service_field_is_documented():
    strings = load_json("strings.json")
    services = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))
    for service, definition in services.items():
        documented = strings["services"][service]["fields"]
        assert set(documented) == set(definition.get("fields", {})), service


def test_translations_cover_the_same_keys():
    strings = flat_keys(load_json("strings.json"))
    for language in ("en", "de"):
        translation = flat_keys(load_json(f"translations/{language}.json"))
        missing = sorted(strings - translation)
        extra = sorted(translation - strings)
        assert translation == strings, (
            f"{language}.json differs: missing {missing}, extra {extra}"
        )


def test_config_and_options_steps_are_translated():
    strings = load_json("strings.json")
    config_steps = {"user", "profiles"}
    assert config_steps <= set(strings["config"]["step"])

    options_steps = {
        "init",
        "add_value",
        "edit_value",
        "edit_value_form",
        "reorder_values",
        "delete_value",
        "add_profile",
        "edit_profile",
        "edit_values",
        "delete_profile",
        "reorder",
        "custom_name",
    }
    assert options_steps <= set(strings["options"]["step"])
    # The menu offers exactly the steps that exist.
    menu = set(strings["options"]["step"]["init"]["menu_options"])
    assert menu <= options_steps


def test_the_card_is_shipped():
    card = COMPONENT / "frontend" / "climate-profile-card.js"
    assert card.is_file()
    source = card.read_text(encoding="utf-8")
    assert 'customElements.define("climate-profile-card"' in source
    assert f'"{DOMAIN}"' in source, "the card must call this integration's services"
