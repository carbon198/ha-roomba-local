"""Station maintenance remains a known vacuum activity while MQTT stays online."""

import pytest

from custom_components.roomba_local.models import Telemetry

from .conftest import ROBOT
from .test_entities import entity_id


@pytest.mark.parametrize("phase", ["evac", "padwash"])
@pytest.mark.parametrize("cycle", ["clean", "none", None])
async def test_station_maintenance_is_docked(hass, setup_entry, document, phase, cycle):
    coordinator = setup_entry.runtime_data
    values = document["values"] | {"mission_phase": phase, "mission_cycle": cycle}
    if cycle is None:
        values.pop("mission_cycle")
    coordinator.async_set_updated_data(
        Telemetry.parse(
            document
            | {
                "values": values,
                "available": document["available"] | {"mission_cycle": cycle is not None},
            },
            ROBOT,
        )
    )
    await hass.async_block_till_done()

    assert hass.states.get(entity_id(hass, setup_entry, "vacuum", "vacuum")).state == "docked"
    assert hass.states.get(entity_id(hass, setup_entry, "sensor", "mission_phase")).state == phase
    assert (
        hass.states.get(
            entity_id(hass, setup_entry, "binary_sensor", "robot_mqtt_connection")
        ).state
        == "on"
    )


async def test_post_mission_station_sequence_has_no_unknown_activity(hass, setup_entry, document):
    coordinator = setup_entry.runtime_data
    vacuum_id = entity_id(hass, setup_entry, "vacuum", "vacuum")
    for phase, cycle, expected in (
        ("run", "clean", "cleaning"),
        ("hmPostMsn", "clean", "returning"),
        ("evac", "clean", "docked"),
        ("hmPostMsn", "clean", "returning"),
        ("padwash", "clean", "docked"),
        ("charge", "none", "docked"),
    ):
        coordinator.async_set_updated_data(
            Telemetry.parse(
                document
                | {"values": document["values"] | {"mission_phase": phase, "mission_cycle": cycle}},
                ROBOT,
            )
        )
        await hass.async_block_till_done()
        assert hass.states.get(vacuum_id).state == expected
