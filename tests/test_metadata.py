"""Packaging and translation coverage are integration contracts, not HA stubs."""

import json
from pathlib import Path
import struct

from homeassistant.helpers.translation import async_get_translations

from custom_components.roomba_local.presentation import LABELS, TRANSLATED_FIELDS, state_key
from custom_components.roomba_local.models import Telemetry
from custom_components.roomba_local.repairs import async_create_fix_flow
from custom_components.roomba_local.diagnostics import async_get_config_entry_diagnostics

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components/roomba_local"


async def test_translations_loaded_by_ha(hass, setup_entry):
    catalogs = json.loads((COMPONENT / "strings.json").read_text())
    assert catalogs == json.loads((COMPONENT / "translations/en.json").read_text())
    names = {
        key
        for platform in catalogs["entity"].values()
        for key in platform
        if key not in ("live_map", "room_map")
    }
    assert TRANSLATED_FIELDS <= names
    for key, values in LABELS.items():
        if key not in catalogs["entity"]["sensor"]:
            continue
        assert catalogs["entity"]["sensor"][key]["state"] == {
            state_key(raw): label for raw, label in values.items()
        }
    translations = await async_get_translations(hass, "en", "entity", {"roomba_local"})
    assert translations["component.roomba_local.entity.sensor.mission_error.state.code_353"] == (
        "Dust bag full"
    )
    assert (
        translations["component.roomba_local.entity.select.suction_level.state.option_3"]
        == "Normal"
    )
    exceptions = await async_get_translations(hass, "en", "exceptions", {"roomba_local"})
    assert "component.roomba_local.exceptions.delivery_failed.message" in exceptions
    issues = await async_get_translations(hass, "en", "issues", {"roomba_local"})
    assert "component.roomba_local.issues.cleaning_mode.title" in issues


def test_manifest_and_brand_assets():
    manifest = json.loads((COMPONENT / "manifest.json").read_text())
    assert manifest["domain"] == "roomba_local"
    assert manifest["config_flow"]
    assert manifest["iot_class"] == "local_push"
    assert json.loads((ROOT / "hacs.json").read_text())["homeassistant"] == "2026.10.0"
    for name, size in (("icon", 256), ("icon@2x", 512), ("dark_icon", 256), ("dark_icon@2x", 512)):
        image = (COMPONENT / "brand" / (name + ".png")).read_bytes()
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", image[16:24]) == (size, size)


async def test_repair_while_entry_unloaded(hass, entry):
    repair = await async_create_fix_flow(hass, "cleaning_mode", {"entry_id": entry.entry_id})
    repair.hass = hass
    assert (await repair.async_step_init())["reason"] == "entry_not_loaded"
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert not diagnostics["runtime_available"]
    assert "api_reachable" not in diagnostics


def test_additional_parser_and_presentation_boundaries(document):
    document["settings"][2]["value"] = True
    try:
        Telemetry.parse(document, document["robot_id"])
    except ValueError as exc:
        assert "Select requires integer" in str(exc)
    else:
        raise AssertionError("Boolean select value accepted")
