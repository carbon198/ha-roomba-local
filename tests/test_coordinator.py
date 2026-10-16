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

START = LocalCoordinator.async_start


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
