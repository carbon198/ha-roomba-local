"""Real HA fixtures with only the emulator network boundary replaced."""

from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roomba_local.api import LocalAPI
from custom_components.roomba_local.config_flow import robot_identity
from custom_components.roomba_local.const import DOMAIN
from custom_components.roomba_local.models import Telemetry

ROBOT = "a" * 32
URL = "https://roomba.example.com"
TOKEN = "a" * 43
MAP = {"id": "one", "version": "1", "revision": "a" * 64}


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def document():
    return {
        "schema_version": 1,
        "robot_id": ROBOT,
        "online": True,
        "reported_at": 1,
        "fields": [
            {
                "key": "battery",
                "name": "Battery",
                "kind": "sensor",
                "device_class": "battery",
                "unit_of_measurement": "%",
                "state_class": "measurement",
            },
            {"key": "mission_phase", "name": "Phase", "kind": "sensor"},
            {"key": "mission_cycle", "name": "Cycle", "kind": "sensor"},
            {
                "key": "robot_mqtt_connection",
                "name": "MQTT",
                "kind": "binary_sensor",
                "device_class": "connectivity",
                "entity_category": "diagnostic",
            },
            {"key": "bin_present", "name": "Bin", "kind": "binary_sensor"},
            {
                "key": "last_data_received",
                "name": "Received",
                "kind": "sensor",
                "device_class": "timestamp",
                "entity_category": "diagnostic",
            },
            {
                "key": "localized_map",
                "name": "Map",
                "kind": "sensor",
                "entity_category": "diagnostic",
            },
            {"key": "mission_error", "name": "Error", "kind": "sensor"},
        ],
        "values": {
            "battery": 75,
            "mission_phase": "charge",
            "mission_cycle": "none",
            "robot_mqtt_connection": True,
            "bin_present": True,
            "last_data_received": "2026-10-16T00:00:00+00:00",
            "localized_map": "one",
            "mission_error": 0,
        },
        "available": {
            key: True
            for key in (
                "battery",
                "mission_phase",
                "mission_cycle",
                "robot_mqtt_connection",
                "bin_present",
                "last_data_received",
                "localized_map",
                "mission_error",
            )
        },
        "segments": [{"id": "one:1:1", "name": "Kitchen", "group": "Map one"}],
        "segment_colors": {"one:1:1": "Blue"},
        "segment_catalog_complete": True,
        "settings": [
            {
                "key": "child_lock",
                "name": "Child lock",
                "kind": "switch",
                "value": False,
                "options": {},
            },
            {
                "key": "pad_dry_allowed",
                "name": "Drying",
                "kind": "switch",
                "value": 1,
                "options": {"0": "Off", "1": "On"},
            },
            {
                "key": "suction_level",
                "name": "Suction",
                "kind": "select",
                "value": 3,
                "options": {"2": "Light", "3": "Normal", "4": "Deep"},
            },
        ],
        "cleaning_modes": [2, 4, 6],
        "maps": [deepcopy(MAP)],
        "map_inventory": ["one"],
        "position": {
            "map_id": "one",
            "x": 1,
            "y": 2,
            "heading": 0,
            "timestamp": 1,
            "sequence": 1,
            "received_at": 1,
            "expires_at": 2,
        },
        "map_overlays": [
            {"map_id": "one", "revision": 1, "status": "live", "point_count": 1, "truncated": False}
        ],
        "device": {"model": "N186020", "serial_number": "TEST", "sw_version": "test"},
    }


@pytest.fixture
def entry(hass: HomeAssistant):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Roomba downstairs",
        unique_id=robot_identity(URL, ROBOT),
        data={"api_url": URL, "bearer_token": TOKEN, "robot_id": ROBOT},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def api(document):
    with (
        patch.object(
            LocalAPI,
            "telemetry",
            AsyncMock(side_effect=lambda: Telemetry.parse(deepcopy(document), ROBOT)),
        ) as telemetry,
        patch.object(LocalAPI, "command", new_callable=AsyncMock) as command,
        patch.object(LocalAPI, "set_setting", new_callable=AsyncMock) as setting,
        patch.object(LocalAPI, "map_image", new_callable=AsyncMock) as image,
        patch("custom_components.roomba_local.coordinator.LocalCoordinator.async_start"),
    ):
        yield {"telemetry": telemetry, "command": command, "setting": setting, "image": image}


@pytest.fixture
async def setup_entry(hass, entry, api):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    yield entry
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
