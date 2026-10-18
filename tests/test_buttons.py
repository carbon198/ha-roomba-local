"""Dock buttons fail closed and send each action once without optimistic state."""

from dataclasses import replace
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.roomba_local.api import CannotConnect, InvalidAuth
from .test_entities import entity, entity_id


@pytest.mark.parametrize(
    ("key", "command"),
    [
        ("evacuate_bin", "evac"),
        ("start_pad_drying", "drypad"),
        ("stop_pad_drying", "stoppaddry"),
        ("wash_mop_pad", "washpad"),
    ],
)
async def test_dock_button_press(hass, setup_entry, key, command):
    button = entity(hass, entity_id(hass, setup_entry, "button", key))
    assert button.available
    await button.async_press()
    setup_entry.runtime_data.api.command.assert_awaited_once_with(command)
    assert button.device_info["manufacturer"] == "iRobot"


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"mission_phase": "idle"},
        {"mission_cycle": "clean"},
        {"mission_phase": "pause"},
        {"robot_mqtt_connection": False},
    ],
)
async def test_dock_button_unavailable(hass, setup_entry, values):
    coordinator = setup_entry.runtime_data
    data = coordinator.data
    coordinator.async_set_updated_data(
        replace(data, values={} if not values else data.values | values)
    )
    button = entity(hass, entity_id(hass, setup_entry, "button", "evacuate_bin"))
    assert not button.available
    with pytest.raises(HomeAssistantError):
        await button.async_press()
    coordinator.api.command.assert_not_awaited()


@pytest.mark.parametrize(
    "failure", [CannotConnect("uncertain"), InvalidAuth("bad"), ValueError("bad")]
)
async def test_dock_button_errors(hass, setup_entry, failure):
    coordinator = setup_entry.runtime_data
    coordinator.api.command.side_effect = failure
    button = entity(hass, entity_id(hass, setup_entry, "button", "start_pad_drying"))
    with patch.object(setup_entry, "async_start_reauth") as reauth:
        with pytest.raises(HomeAssistantError):
            await button.async_press()
        assert reauth.called == isinstance(failure, InvalidAuth)
    assert coordinator.api.command.await_count == 1


async def test_dock_button_missing_availability(hass, setup_entry):
    coordinator = setup_entry.runtime_data
    coordinator.async_set_updated_data(replace(coordinator.data, available={}))
    button = entity(hass, entity_id(hass, setup_entry, "button", "evacuate_bin"))
    assert not button.available
