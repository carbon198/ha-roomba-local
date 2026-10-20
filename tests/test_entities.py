"""Entity registry, real platform lifecycle, services and reported-only behavior."""

from copy import deepcopy
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.exceptions import HomeAssistantError
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.components.vacuum.const import VacuumEntityFeature
from homeassistant.components.repairs import issue_handler
from homeassistant.helpers import device_registry as dr, entity_registry as er, issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roomba_local.api import CannotConnect, InvalidAuth
from custom_components.roomba_local.diagnostics import async_get_config_entry_diagnostics
from custom_components.roomba_local.models import Telemetry
from custom_components.roomba_local.repairs import async_create_fix_flow
from custom_components.roomba_local.const import DOMAIN
from custom_components.roomba_local.entity import LocalEntity, device_info
from custom_components.roomba_local.image import LocalMapImage
from custom_components.roomba_local.map_labels import update_map_numbers

from .conftest import ROBOT, TOKEN


def entity_id(hass, entry, domain, suffix):
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, entry.unique_id + "_" + suffix)


def entity(hass, identifier):
    return hass.data["entity_components"][identifier.split(".")[0]].get_entity(identifier)


async def test_setup_and_device_identity(hass, setup_entry, document):
    entry = setup_entry
    registry = dr.async_get(hass)
    device = registry.async_get_device_by_identifier((DOMAIN, entry.unique_id), entry.entry_id)
    assert (device.manufacturer, device.model, device.sw_version, device.serial_number) == (
        "iRobot",
        "N186020",
        "test",
        "TEST",
    )
    battery = hass.states.get(entity_id(hass, entry, "sensor", "battery"))
    assert battery.state == "75"
    assert battery.attributes["unit_of_measurement"] == "%"
    assert battery.attributes["friendly_name"] == "Roomba downstairs Battery"
    vacuum_id = entity_id(hass, entry, "vacuum", "vacuum")
    assert hass.states.get(vacuum_id).state == "docked"
    assert hass.states.get(vacuum_id).attributes["friendly_name"] == "Roomba downstairs"
    assert entity_id(hass, entry, "sensor", "mission_cycle") is None
    assert hass.states.get(entity_id(hass, entry, "sensor", "mission_phase")).state == "charge"
    assert hass.states.get(entity_id(hass, entry, "sensor", "mission_error")).state == "code_0"
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert TOKEN not in str(data)
    assert ROBOT not in str(data)
    assert "TEST" not in str(data)
    assert data["map_count"] == 1
    updated = Telemetry.parse(document | {"device": {"sw_version": "new"}}, ROBOT)
    entry.runtime_data._async_metadata(updated)
    entry.runtime_data.async_set_updated_data(updated)
    assert registry.async_get(device.id).sw_version == "new"


async def test_availability_and_recovery(hass, setup_entry, document):
    entry = setup_entry
    coordinator = entry.runtime_data
    ids = [entity_id(hass, entry, "sensor", "battery"), entity_id(hass, entry, "vacuum", "vacuum")]
    coordinator.async_set_update_error(UpdateFailed("disconnected"))
    await hass.async_block_till_done()
    assert all(hass.states.get(identifier).state == "unavailable" for identifier in ids)
    updated = Telemetry.parse(
        document
        | {"online": False, "values": document["values"] | {"robot_mqtt_connection": False}},
        ROBOT,
    )
    coordinator.async_set_updated_data(updated)
    await hass.async_block_till_done()
    assert hass.states.get(ids[0]).state == "75"
    assert hass.states.get(ids[1]).state == "unavailable"
    coordinator.async_set_updated_data(Telemetry.parse(document, ROBOT))
    await hass.async_block_till_done()
    assert hass.states.get(ids[1]).state == "docked"
    updated.available["battery"] = False
    coordinator.async_set_updated_data(updated)
    await hass.async_block_till_done()
    assert hass.states.get(ids[0]).state == "unavailable"


async def test_acme_challenge_sensor(hass, setup_entry, document):
    entry = setup_entry
    coordinator = entry.runtime_data
    identifier = entity_id(hass, entry, "sensor", "acme_dns_challenge")
    registry_entry = er.async_get(hass).async_get(identifier)
    assert registry_entry.entity_category.value == "diagnostic"
    assert hass.states.get(identifier).state == "unknown"
    assert hass.states.get(identifier).attributes["friendly_name"] == (
        "Roomba downstairs ACME DNS challenge"
    )
    for value in ("a" * 43, "b" * 43):
        coordinator.async_set_updated_data(
            Telemetry.parse(
                document
                | {
                    "online": False,
                    "acme_dns_challenge": {
                        "name": "_acme-challenge.roomba.example.com",
                        "type": "TXT",
                        "value": value,
                    },
                },
                ROBOT,
            )
        )
        await hass.async_block_till_done()
        state = hass.states.get(identifier)
        assert state.state == value
        assert state.attributes["name"] == "_acme-challenge.roomba.example.com"
        assert state.attributes["type"] == "TXT"
    coordinator.async_set_update_error(UpdateFailed("disconnected"))
    await hass.async_block_till_done()
    assert hass.states.get(identifier).state == "unavailable"
    coordinator.async_set_updated_data(
        Telemetry.parse(document | {"acme_dns_challenge": None}, ROBOT)
    )
    await hass.async_block_till_done()
    state = hass.states.get(identifier)
    assert state.state == "unknown"
    assert "name" not in state.attributes
    assert "type" not in state.attributes


@pytest.mark.parametrize(
    ("phase", "cycle", "expected"),
    [
        ("stuck", "clean", "error"),
        ("chargingError", "none", "error"),
        ("hmPostMsn", "clean", "returning"),
        ("idle", "none", "idle"),
        ("pause", "clean", "paused"),
        ("run", "clean", "cleaning"),
        ("stop", "none", "idle"),
        ("unknown", "none", None),
    ],
)
async def test_vacuum_activity(hass, setup_entry, document, phase, cycle, expected):
    coordinator = setup_entry.runtime_data
    updated = Telemetry.parse(
        document
        | {"values": document["values"] | {"mission_phase": phase, "mission_cycle": cycle}},
        ROBOT,
    )
    coordinator.async_set_updated_data(updated)
    vacuum = entity(hass, entity_id(hass, setup_entry, "vacuum", "vacuum"))
    assert vacuum.activity == expected
    coordinator.async_set_updated_data(replace(updated, values={}))
    assert vacuum.activity is None


async def test_vacuum_services_reported_only(hass, setup_entry, api):
    identifier = entity_id(hass, setup_entry, "vacuum", "vacuum")
    for service, command in (
        ("start", "start"),
        ("pause", "pause"),
        ("stop", "stop"),
        ("return_to_base", "dock"),
        ("locate", "find"),
    ):
        await hass.services.async_call("vacuum", service, {"entity_id": identifier}, blocking=True)
        assert api["command"].call_args.args[0] == command
        assert hass.states.get(identifier).state == "docked"
    vacuum = entity(hass, identifier)
    segments = await vacuum.async_get_segments()
    assert segments[0].name == "Kitchen (Blue)"
    assert segments[0].group == "Map 1"
    await vacuum.async_clean_segments(["one:1:1"])
    api["command"].assert_awaited_with("clean_segments", ["one:1:1"], operating_mode=6)
    for selection in ([], ["bad"], ["one:1:1", "one:1:1"]):
        with pytest.raises(HomeAssistantError) as exc:
            await vacuum.async_clean_segments(selection)
        assert exc.value.translation_key == "invalid_segments"
    with patch.object(vacuum.coordinator.api, "command", AsyncMock(side_effect=ValueError())):
        with pytest.raises(HomeAssistantError) as exc:
            await vacuum._command("find", ["one:1:1"])
        assert exc.value.translation_key == "invalid_command"


@pytest.mark.parametrize(
    ("failure", "key"),
    [
        (InvalidAuth(), "invalid_auth"),
        (CannotConnect(), "delivery_failed"),
    ],
)
async def test_command_errors(hass, setup_entry, api, failure, key):
    vacuum = entity(hass, entity_id(hass, setup_entry, "vacuum", "vacuum"))
    api["command"].side_effect = failure
    with pytest.raises(HomeAssistantError) as exc:
        await vacuum.async_start()
    assert exc.value.translation_key == key
    if key == "invalid_auth":
        await hass.async_block_till_done()
        assert any(
            flow["context"]["source"] == "reauth"
            for flow in hass.config_entries.flow.async_progress()
        )
    vacuum.coordinator.async_set_update_error(UpdateFailed("offline"))
    with pytest.raises(HomeAssistantError) as exc:
        await vacuum.async_pause()
    assert exc.value.translation_key == "unavailable"


async def test_settings_and_modes(hass, setup_entry, api, document):
    entry = setup_entry
    for key in ("child_lock", "pad_dry_allowed"):
        identifier = entity_id(hass, entry, "switch", "setting_" + key)
        for service in ("turn_on", "turn_off"):
            await hass.services.async_call(
                "switch", service, {"entity_id": identifier}, blocking=True
            )
        assert hass.states.get(identifier).state == ("off" if key == "child_lock" else "on")
    setting_id = entity_id(hass, entry, "select", "setting_suction_level")
    await hass.services.async_call(
        "select", "select_option", {"entity_id": setting_id, "option": "option_4"}, blocking=True
    )
    api["setting"].assert_awaited_with("suction_level", 4)
    assert hass.states.get(setting_id).state == "option_3"
    mode_id = entity_id(hass, entry, "select", "cleaning_mode")
    await hass.services.async_call(
        "select", "select_option", {"entity_id": mode_id, "option": "vacuum_only"}, blocking=True
    )
    assert entry.options["cleaning_mode"] == 2
    api["command"].assert_not_awaited()
    select = entity(hass, setting_id)
    with pytest.raises(HomeAssistantError):
        await select.async_select_option("invalid")
    with pytest.raises(HomeAssistantError):
        await entity(hass, mode_id).async_select_option("invalid")
    for failure, key in (
        (InvalidAuth(), "invalid_auth"),
        (CannotConnect(), "delivery_failed"),
        (ValueError(), "delivery_failed"),
    ):
        api["setting"].side_effect = failure
        with pytest.raises(HomeAssistantError) as exc:
            await select.async_select_option("option_2")
        assert exc.value.translation_key == key
    entry.runtime_data.async_set_updated_data(replace(entry.runtime_data.data, settings=[]))
    await hass.async_block_till_done()
    assert not select.available
    assert select.options == []
    assert select.current_option is None
    switch = entity(hass, entity_id(hass, entry, "switch", "setting_child_lock"))
    assert switch.is_on is None
    with pytest.raises(HomeAssistantError):
        await switch.async_turn_on()
    updated = Telemetry.parse(document, ROBOT)
    updated.settings.append(
        {
            "key": "two_pass",
            "name": "Two-pass cleaning",
            "kind": "switch",
            "value": True,
            "options": {},
        }
    )
    entry.runtime_data.async_set_updated_data(updated)
    await hass.async_block_till_done()
    assert entity_id(hass, entry, "switch", "setting_two_pass")


async def test_unsupported_mode_repair(hass, setup_entry, document):
    entry = setup_entry
    coordinator = entry.runtime_data
    updated = Telemetry.parse(document | {"cleaning_modes": [2]}, ROBOT)
    coordinator._async_metadata(updated)
    coordinator.async_set_updated_data(updated)
    issue_id = f"cleaning_mode_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    vacuum = entity(hass, entity_id(hass, entry, "vacuum", "vacuum"))
    with pytest.raises(HomeAssistantError) as exc:
        await vacuum.async_start()
    assert exc.value.translation_key == "unsupported_mode"
    repair = await async_create_fix_flow(hass, issue_id, {"entry_id": entry.entry_id})
    repair.hass = hass
    assert (await repair.async_step_init())["step_id"] == "confirm"
    assert (await repair.async_step_confirm({"cleaning_mode": 6}))["errors"]
    assert (await repair.async_step_confirm({"cleaning_mode": 2}))["type"] == "create_entry"
    assert entry.options["cleaning_mode"] == 2
    assert not ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    coordinator.async_set_updated_data(replace(updated, cleaning_modes=[]))
    assert (await repair.async_step_confirm())["reason"] == "no_modes"
    repair.entry_id = "missing"
    assert (await repair.async_step_confirm())["reason"] == "entry_removed"


async def test_repair_through_real_flow_manager(hass, setup_entry, api):
    hass.data["repairs"] = {}
    issue_handler.async_setup(hass)
    coordinator = setup_entry.runtime_data
    coordinator.async_set_updated_data(replace(coordinator.data, cleaning_modes=[2]))
    coordinator._async_metadata(coordinator.data)
    issue_id = f"cleaning_mode_{setup_entry.entry_id}"
    manager = hass.data["repairs"]["flow_manager"]
    result = await manager.async_init(DOMAIN, context={"issue_id": issue_id})
    assert result["step_id"] == "confirm"
    result = await manager.async_configure(result["flow_id"], {"cleaning_mode": 2})
    assert result["type"] == "create_entry"
    assert setup_entry.options["cleaning_mode"] == 2
    assert not ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    api["command"].assert_not_awaited()


async def test_images_and_authoritative_removal(hass, setup_entry, document, api):
    entry = setup_entry
    identifier = entity_id(hass, entry, "image", "map_one_live")
    image = entity(hass, identifier)
    api["image"].return_value = b"png"
    assert await image.async_image() == b"png"
    assert await image.async_image() == b"png"
    api["image"].assert_awaited_once()
    assert image.extra_state_attributes["trail_points"] == 1
    coordinator = entry.runtime_data
    changed = deepcopy(document)
    changed["map_overlays"][0]["revision"] = 2
    coordinator.async_set_updated_data(Telemetry.parse(changed, ROBOT))
    await hass.async_block_till_done()
    assert image._image is None
    for failure, key in ((InvalidAuth(), "invalid_auth"), (CannotConnect(), "image_failed")):
        api["image"].side_effect = failure
        with pytest.raises(HomeAssistantError) as exc:
            await image.async_image()
        assert exc.value.translation_key == key

    async def changed_during_request(*args):
        coordinator.async_set_updated_data(replace(coordinator.data, position=None))
        return b"png"

    api["image"].side_effect = changed_during_request
    assert await image.async_image() is None
    coordinator.async_set_updated_data(replace(coordinator.data, maps=[], map_inventory=None))
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(identifier)
    assert not image.available
    assert await image.async_image() is None
    coordinator.async_set_updated_data(replace(coordinator.data, map_inventory=[]))
    await hass.async_block_till_done()
    assert er.async_get(hass).async_get(identifier) is None
    coordinator.async_set_updated_data(Telemetry.parse(document, ROBOT))
    await hass.async_block_till_done()
    assert entity_id(hass, entry, "image", "map_one_live")


async def test_timestamp_throttle_and_missing_values(hass, setup_entry):
    coordinator = setup_entry.runtime_data
    identifier = entity_id(hass, setup_entry, "sensor", "last_data_received")
    sensor = entity(hass, identifier)
    assert sensor.native_value.tzinfo is not None
    with patch(
        "custom_components.roomba_local.sensor.monotonic",
        return_value=sensor._last_data_updated + 31,
    ):
        sensor._handle_coordinator_update()
    localized = entity(hass, entity_id(hass, setup_entry, "sensor", "localized_map"))
    assert localized.native_value == "Map 1"
    assert localized.extra_state_attributes == {"map_id": "one"}
    coordinator.async_set_updated_data(replace(coordinator.data, values={}))
    await hass.async_block_till_done()
    assert localized.native_value is None


@pytest.mark.parametrize("complete", [True, False])
async def test_segment_version_migration_preserves_area_mapping(hass, setup_entry, complete):
    entry = setup_entry
    vacuum_id = entity_id(hass, entry, "vacuum", "vacuum")
    vacuum = entity(hass, vacuum_id)
    registry = er.async_get(hass)
    registry.async_update_entity_options(
        vacuum_id,
        "vacuum",
        {
            "last_seen_segments": [
                {"id": "one:old:1", "name": "Kitchen (Blue)", "group": "Map one"}
            ],
            "area_mapping": {"kitchen": ["one:old:1"]},
        },
    )
    await hass.async_block_till_done()
    data = replace(entry.runtime_data.data, segment_catalog_complete=complete)
    entry.runtime_data.async_set_updated_data(data)
    await hass.async_block_till_done()
    vacuum._sync_segments()
    options = registry.async_get(vacuum_id).options["vacuum"]
    assert options["area_mapping"] == {"kitchen": ["one:1:1"]}
    assert options["last_seen_segments"][0]["group"] == "Map 1"
    assert options["last_seen_segments"][0]["name"] == "Kitchen (Blue)"
    assert not ir.async_get(hass).async_get_issue(
        "vacuum", f"segments_changed_{vacuum.registry_entry.id}"
    )
    entry.runtime_data.async_set_updated_data(
        replace(data, segments=[{"id": "one:1:1", "name": "Changed room", "group": "Map one"}])
    )
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(
        "vacuum", f"segments_changed_{vacuum.registry_entry.id}"
    )


async def test_segment_partial_catalog_preserves_missing_map(hass, setup_entry):
    entry = setup_entry
    vacuum_id = entity_id(hass, entry, "vacuum", "vacuum")
    vacuum = entity(hass, vacuum_id)
    registry = er.async_get(hass)
    registry.async_update_entity_options(
        vacuum_id,
        "vacuum",
        {
            "last_seen_segments": [
                {"id": "one:old:1", "name": "Kitchen", "group": "Map 1"},
                {"id": "two:old:1", "name": "Upstairs", "group": "Map 2"},
            ],
        },
    )
    await hass.async_block_till_done()
    data = replace(entry.runtime_data.data, segment_catalog_complete=False, segment_colors={})
    entry.runtime_data.async_set_updated_data(data)
    await hass.async_block_till_done()
    vacuum._sync_segments()
    options = registry.async_get(vacuum_id).options["vacuum"]
    assert len(options["last_seen_segments"]) == 2
    assert options["last_seen_segments"][1]["id"] == "two:old:1"
    entry.runtime_data.async_set_updated_data(replace(data, segment_catalog_complete=True))
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(
        "vacuum", f"segments_changed_{vacuum.registry_entry.id}"
    )
    entry.runtime_data.async_set_updated_data(replace(data, segments=[]))
    assert not vacuum.supported_features & VacuumEntityFeature.CLEAN_AREA


async def test_legacy_device_and_unknown_field(hass, setup_entry):
    coordinator = setup_entry.runtime_data
    coordinator.async_set_updated_data(
        replace(coordinator.data, device={}, values={"firmware_version": "legacy"})
    )
    assert device_info(coordinator)["sw_version"] == "legacy"
    assert "model" not in device_info(coordinator)
    coordinator.async_set_updated_data(replace(coordinator.data, values={}))
    assert "sw_version" not in device_info(coordinator)
    unknown = LocalEntity(
        coordinator, {"key": "new_field", "name": "Future field", "entity_category": "config"}
    )
    assert unknown.name == "Future field"


async def test_map_metadata_edge_cases(hass, setup_entry):
    coordinator = setup_entry.runtime_data
    room = LocalMapImage(hass, coordinator, "one", "room")
    assert "position_status" not in room.extra_state_attributes
    live = LocalMapImage(hass, coordinator, "one", "live")
    coordinator.async_set_updated_data(replace(coordinator.data, map_overlays=[]))
    assert live.extra_state_attributes["position_status"] == "live"
    coordinator.async_set_updated_data(replace(coordinator.data, position=None))
    assert live.extra_state_attributes["position_status"] == "unavailable"
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "image", DOMAIN, setup_entry.unique_id + "_map_other_unknown", config_entry=setup_entry
    )
    coordinator.async_set_updated_data(replace(coordinator.data, map_inventory=[]))
    await hass.async_block_till_done()
    assert registry.async_get_entity_id(
        "image", DOMAIN, setup_entry.unique_id + "_map_other_unknown"
    )


async def test_map_number_validation_and_stability(hass, setup_entry):
    entry = setup_entry
    for invalid in ([], {"one": 0}, {"one": 1, "two": 1}):
        hass.config_entries.async_update_entry(entry, options={"map_numbers": invalid})
        with pytest.raises(ValueError, match="Invalid saved map"):
            update_map_numbers(hass, entry, entry.runtime_data.data)
    hass.config_entries.async_update_entry(entry, options={"map_numbers": {"one": 1, "two": 2}})
    update_map_numbers(
        hass,
        entry,
        replace(
            entry.runtime_data.data, maps=[], map_inventory=["two", "three"], values={}, segments=[]
        ),
    )
    assert entry.options["map_numbers"] == {"one": 1, "two": 2, "three": 3}


async def test_two_entries_keep_devices_options_and_state_isolated(
    hass, setup_entry, api, document
):
    first = setup_entry
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Roomba upstairs",
        unique_id="second-robot",
        data={**first.data, "robot_id": "b" * 32},
    )
    second.add_to_hass(hass)
    api["telemetry"].side_effect = lambda: Telemetry.parse(
        document | {"robot_id": "b" * 32, "values": document["values"] | {"battery": 50}}, "b" * 32
    )
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    first_id = entity_id(hass, first, "sensor", "battery")
    second_id = entity_id(hass, second, "sensor", "battery")
    assert first_id != second_id
    assert hass.states.get(first_id).state == "75"
    assert hass.states.get(second_id).state == "50"
    registry = er.async_get(hass)
    assert registry.async_get(first_id).device_id != registry.async_get(second_id).device_id
    mode = entity(hass, entity_id(hass, second, "select", "cleaning_mode"))
    await mode.async_select_option("mop_only")
    assert second.options["cleaning_mode"] == 4
    assert "cleaning_mode" not in first.options
    assert await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(first_id).state == "75"


async def test_reconfiguration_reloads_without_changing_entity_or_device_ids(hass, setup_entry):
    entry = setup_entry
    identifier = entity_id(hass, entry, "sensor", "battery")
    device_id = er.async_get(hass).async_get(identifier).device_id
    coordinator = entry.runtime_data
    options = dict(entry.options)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_url": "https://new.example.com", "bearer_token": "b" * 43}
    )
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.runtime_data is not coordinator
    assert entry.options == options
    assert entity_id(hass, entry, "sensor", "battery") == identifier
    assert er.async_get(hass).async_get(identifier).device_id == device_id
