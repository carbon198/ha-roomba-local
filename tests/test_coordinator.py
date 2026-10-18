"""Setup retries, stream reconnects, authentication and background task cleanup."""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.helpers import entity_registry as er

from custom_components.roomba_local.api import CannotConnect, InvalidAuth
from custom_components.roomba_local.coordinator import LocalCoordinator
from custom_components.roomba_local.models import Telemetry
from custom_components.roomba_local import async_unload_entry

from .conftest import ROBOT
from .test_entities import entity_id

START = LocalCoordinator.async_start


def offline_snapshot(data):
    return replace(
        data,
        online=False,
        values=data.values | {"robot_mqtt_connection": False},
    )


async def test_short_mqtt_disconnect_preserves_sensors_and_recovers(hass, setup_entry):
    coordinator = setup_entry.runtime_data
    original = coordinator.data
    offline = replace(
        offline_snapshot(original),
        values={"robot_mqtt_connection": False},
        available={key: key == "robot_mqtt_connection" for key in original.available},
    )
    with patch.object(hass.loop, "call_later") as timer:
        coordinator.async_set_updated_data(coordinator._async_debounce_disconnect(offline))
    timer.assert_called_once_with(10, coordinator._async_confirm_disconnect)
    assert coordinator.data.online
    assert coordinator.data.values["robot_mqtt_connection"] is True
    assert coordinator.data.values["battery"] == original.values["battery"]
    assert coordinator.data.available["battery"]
    coordinator.async_set_updated_data(coordinator._async_debounce_disconnect(original))
    timer.return_value.cancel.assert_called_once()
    assert coordinator.data.online
    assert coordinator._pending_offline is None


async def test_long_mqtt_disconnect_uses_latest_snapshot_without_extending_deadline(
    hass, setup_entry
):
    coordinator = setup_entry.runtime_data
    offline = offline_snapshot(coordinator.data)
    with patch.object(hass.loop, "call_later") as timer:
        coordinator.async_set_updated_data(coordinator._async_debounce_disconnect(offline))
        updated = replace(offline, values=offline.values | {"battery": 23})
        coordinator.async_set_updated_data(coordinator._async_debounce_disconnect(updated))
    timer.assert_called_once()
    timer.call_args.args[1]()
    assert not coordinator.data.online
    assert coordinator.data.values["robot_mqtt_connection"] is False
    assert coordinator.data.values["battery"] == 23
    with patch.object(hass.loop, "call_later") as timer:
        assert coordinator._async_debounce_disconnect(offline) is offline
    timer.assert_not_called()
    online = replace(offline, online=True, values=offline.values | {"robot_mqtt_connection": True})
    coordinator.async_set_updated_data(coordinator._async_debounce_disconnect(online))
    with patch.object(hass.loop, "call_later") as timer:
        coordinator.async_set_updated_data(coordinator._async_debounce_disconnect(offline))
    timer.assert_called_once()
    await coordinator.async_shutdown()
    timer.return_value.cancel.assert_called_once()


async def test_initially_offline_robot_has_no_grace(hass, setup_entry):
    coordinator = setup_entry.runtime_data
    offline = offline_snapshot(coordinator.data)
    coordinator.async_set_updated_data(offline)
    with patch.object(hass.loop, "call_later") as timer:
        assert coordinator._async_debounce_disconnect(offline) is offline
    timer.assert_not_called()


async def test_refresh_applies_disconnect_grace(hass, setup_entry, api):
    coordinator = setup_entry.runtime_data
    api["telemetry"].side_effect = None
    api["telemetry"].return_value = offline_snapshot(coordinator.data)
    with patch.object(hass.loop, "call_later") as timer:
        data = await coordinator._async_update_data()
    assert data.online
    assert data.values["robot_mqtt_connection"] is True
    await coordinator.async_shutdown()
    timer.return_value.cancel.assert_called_once()


async def test_disconnect_changes_ha_state_only_after_ten_seconds(hass, setup_entry):
    coordinator = setup_entry.runtime_data
    connection = entity_id(hass, setup_entry, "binary_sensor", "robot_mqtt_connection")
    coordinator.async_set_updated_data(
        coordinator._async_debounce_disconnect(offline_snapshot(coordinator.data))
    )
    await asyncio.sleep(9)
    assert hass.states.get(connection).state == "on"
    assert coordinator.data.online
    await asyncio.sleep(1.1)
    await hass.async_block_till_done()
    assert hass.states.get(connection).state == "off"
    assert not coordinator.data.online


async def test_stream_applies_and_cancels_disconnect_grace(hass, setup_entry):
    coordinator = setup_entry.runtime_data
    online = coordinator.data

    async def stream():
        yield offline_snapshot(online)
        assert coordinator.data.online
        assert coordinator.data.values["robot_mqtt_connection"] is True
        yield online
        assert coordinator._pending_offline is None
        raise InvalidAuth()

    with (
        patch.object(coordinator.api, "events", stream),
        patch.object(hass.loop, "call_later") as timer,
    ):
        await coordinator._async_listen()
    timer.return_value.cancel.assert_called_once()
    assert not coordinator.last_update_success


@pytest.mark.parametrize("failure", [CannotConnect(), InvalidAuth()])
async def test_api_failure_cancels_pending_disconnect(hass, setup_entry, api, failure):
    coordinator = setup_entry.runtime_data
    with patch.object(hass.loop, "call_later") as timer:
        coordinator.async_set_updated_data(
            coordinator._async_debounce_disconnect(offline_snapshot(coordinator.data))
        )
    api["telemetry"].side_effect = failure
    with pytest.raises((UpdateFailed, ConfigEntryAuthFailed)):
        await coordinator._async_update_data()
    timer.return_value.cancel.assert_called_once()
    assert coordinator._pending_offline is None


@pytest.mark.parametrize(
    ("failure", "state"),
    [
        (CannotConnect("offline"), ConfigEntryState.SETUP_RETRY),
        (InvalidAuth(), ConfigEntryState.SETUP_ERROR),
    ],
)
async def test_initial_setup_failure(hass, entry, api, failure, state):
    api["telemetry"].side_effect = failure
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is state


async def test_coordinator_refresh_failure(hass, setup_entry, api):
    api["telemetry"].side_effect = CannotConnect()
    with pytest.raises(UpdateFailed):
        await setup_entry.runtime_data._async_update_data()
    api["telemetry"].side_effect = InvalidAuth()
    with pytest.raises(ConfigEntryAuthFailed):
        await setup_entry.runtime_data._async_update_data()


async def test_stream_recovery_and_backoff(hass, setup_entry, document):
    coordinator = setup_entry.runtime_data
    counts = []
    calls = 0

    async def stream():
        nonlocal calls
        calls += 1
        if calls <= 6:
            raise CannotConnect("offline")
        yield Telemetry.parse(document | {"values": document["values"] | {"battery": 80}}, ROBOT)
        raise InvalidAuth()

    async def sleep(delay):
        counts.append(delay)
        assert not coordinator.last_update_success

    with (
        patch.object(coordinator.api, "events", stream),
        patch("custom_components.roomba_local.coordinator.sleep", sleep),
    ):
        await coordinator._async_listen()
    assert counts == [1, 2, 4, 8, 16, 30]
    assert coordinator.data.values["battery"] == 80
    assert not coordinator.last_update_success
    await hass.async_block_till_done()
    assert any(
        flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress()
    )


async def test_stream_end_reconnects_and_resets_delay(hass, setup_entry):
    coordinator = setup_entry.runtime_data
    counts = []

    async def stream():
        yield coordinator.data

    async def sleep(delay):
        counts.append(delay)
        if len(counts) == 2:
            raise asyncio.CancelledError

    with (
        patch.object(coordinator.api, "events", stream),
        patch("custom_components.roomba_local.coordinator.sleep", sleep),
    ):
        with pytest.raises(asyncio.CancelledError):
            await coordinator._async_listen()
    assert counts == [1, 1]


async def test_owned_tasks_cancel_on_unload_and_reload(hass, setup_entry, api):
    coordinator = setup_entry.runtime_data
    entered = asyncio.Event()

    async def stream():
        entered.set()
        await asyncio.Event().wait()
        yield coordinator.data

    with patch.object(coordinator.api, "events", stream):
        START(coordinator)
        START(coordinator)
        await entered.wait()
        stream_task, position_task = coordinator._stream_task, coordinator._position_task
        assert coordinator.stream_running
        assert await hass.config_entries.async_unload(setup_entry.entry_id)
        await hass.async_block_till_done()
        assert stream_task.done() and position_task.done()
        assert not coordinator.stream_running
        assert not coordinator.async_update_listeners()
        assert await hass.config_entries.async_setup(setup_entry.entry_id)
        await hass.async_block_till_done()
        assert setup_entry.runtime_data is not coordinator


@pytest.mark.parametrize("failure", [None, CannotConnect("offline"), InvalidAuth()])
async def test_position_renewal(hass, setup_entry, document, failure, caplog):
    coordinator = setup_entry.runtime_data
    coordinator.async_set_updated_data(
        replace(coordinator.data, values=coordinator.data.values | {"mission_phase": "run"})
    )
    sleeps = 0

    async def stop(delay):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 2:
            raise asyncio.CancelledError

    with (
        patch.object(coordinator.api, "command", AsyncMock(side_effect=failure)) as command,
        patch("custom_components.roomba_local.coordinator.time.time", side_effect=[1000, 1041]),
        patch("custom_components.roomba_local.coordinator.sleep", stop),
    ):
        if isinstance(failure, InvalidAuth):
            await coordinator._async_positions()
        else:
            with pytest.raises(asyncio.CancelledError):
                await coordinator._async_positions()
        command.assert_awaited()
        assert command.call_args.args == ("live_map",)
    if isinstance(failure, CannotConnect):
        assert caplog.text.count("Live position telemetry request failed") == 1


async def test_no_position_commands_when_inactive(hass, setup_entry, api):
    with patch(
        "custom_components.roomba_local.coordinator.sleep",
        AsyncMock(side_effect=asyncio.CancelledError),
    ):
        with pytest.raises(asyncio.CancelledError):
            await setup_entry.runtime_data._async_positions()
    api["command"].assert_not_awaited()


async def test_unload_failure_preserves_runtime(hass, setup_entry):
    with patch.object(hass.config_entries, "async_unload_platforms", return_value=False):
        assert not await async_unload_entry(hass, setup_entry)


async def test_registry_migration(hass, entry, api):
    registry = er.async_get(hass)
    for domain, suffix in (("sensor", "reporting"), ("image", "map_one_room")):
        registry.async_get_or_create(
            domain, "roomba_local", entry.unique_id + "_" + suffix, config_entry=entry
        )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert (
        registry.async_get_entity_id("sensor", "roomba_local", entry.unique_id + "_reporting")
        is None
    )
    assert (
        registry.async_get_entity_id("image", "roomba_local", entry.unique_id + "_map_one_room")
        is None
    )
    await hass.config_entries.async_unload(entry.entry_id)
