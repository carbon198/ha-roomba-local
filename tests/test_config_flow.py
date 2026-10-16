"""Exercise HA's flow manager, validation, reload and duplicate handling."""

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roomba_local.api import CannotConnect, InvalidAuth
from custom_components.roomba_local.const import DOMAIN
from custom_components.roomba_local.config_flow import LocalConfigFlow, robot_identity

from .conftest import ROBOT, TOKEN, URL


async def test_user_flow(hass, api):
    with (
        patch(
            "custom_components.roomba_local.api.LocalAPI.robots",
            AsyncMock(return_value=[{"robot_id": ROBOT, "sku": "N186020", "ip": "192.0.2.1"}]),
        ),
        patch("custom_components.roomba_local.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_url": URL + "/", "bearer_token": TOKEN}
        )
        assert result["step_id"] == "robot"
        with pytest.raises(InvalidData):
            await hass.config_entries.flow.async_configure(
                result["flow_id"], {"robot_id": "b" * 32}
            )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"robot_id": ROBOT}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == robot_identity(URL, ROBOT)
        assert result["data"]["api_url"] == URL
        await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (InvalidAuth(), "invalid_auth"),
        (CannotConnect(), "cannot_connect"),
        (ValueError(), "invalid_input"),
        (None, "no_robots"),
    ],
)
async def test_inventory_failures(hass, failure, error):
    with patch(
        "custom_components.roomba_local.api.LocalAPI.robots",
        AsyncMock(side_effect=failure, return_value=[]),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_url": URL, "bearer_token": TOKEN}
        )
        assert result["errors"] == {"base": error}


async def test_existing_robot_hidden(hass, entry):
    with patch(
        "custom_components.roomba_local.api.LocalAPI.robots",
        AsyncMock(return_value=[{"robot_id": ROBOT}]),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_url": URL, "bearer_token": TOKEN}
        )
        assert result["reason"] == "all_robots_configured"


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        (InvalidAuth(), "invalid_auth"),
        (CannotConnect(), "cannot_connect"),
        (ValueError(), "invalid_input"),
    ],
)
async def test_robot_validation_errors(hass, api, failure, error):
    api["telemetry"].side_effect = failure
    with patch(
        "custom_components.roomba_local.api.LocalAPI.robots",
        AsyncMock(return_value=[{"robot_id": ROBOT}]),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_url": URL, "bearer_token": TOKEN}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"robot_id": ROBOT}
        )
        assert result["errors"] == {"base": error}


@pytest.mark.parametrize("source", [SOURCE_REAUTH, SOURCE_RECONFIGURE])
async def test_replace_credentials(hass, entry, api, source):
    old_id = entry.unique_id
    with patch.object(hass.config_entries, "async_reload", return_value=True) as reload:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": source, "entry_id": entry.entry_id},
            data=entry.data if source == SOURCE_REAUTH else None,
        )
        api["telemetry"].side_effect = InvalidAuth()
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "bearer_token": "b" * 43,
                **({"api_url": "https://new.example.com"} if source == SOURCE_RECONFIGURE else {}),
            },
        )
        assert result["errors"] == {"base": "invalid_auth"}
        api["telemetry"].side_effect = None
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "bearer_token": "b" * 43,
                **({"api_url": "https://new.example.com"} if source == SOURCE_RECONFIGURE else {}),
            },
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == source + "_successful"
        await hass.async_block_till_done()
        assert entry.data["bearer_token"] == "b" * 43
        assert entry.unique_id == old_id
        reload.assert_awaited_once_with(entry.entry_id)


async def test_reconfigure_duplicate(hass, entry, api):
    MockConfigEntry(
        domain=DOMAIN,
        unique_id="different",
        data={**entry.data, "api_url": "https://new.example.com"},
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"api_url": "https://new.example.com", "bearer_token": TOKEN}
    )
    assert result["reason"] == "already_configured"


async def test_server_move_still_excludes_configured_robot(hass, entry):
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, "api_url": "https://new.example.com"}
    )
    with patch(
        "custom_components.roomba_local.api.LocalAPI.robots",
        AsyncMock(return_value=[{"robot_id": ROBOT}]),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"api_url": "https://new.example.com", "bearer_token": TOKEN}
        )
        assert result["reason"] == "all_robots_configured"


async def test_robot_step_without_inventory(hass):
    flow = LocalConfigFlow()
    flow.hass = hass
    result = await flow.async_step_robot()
    assert result["step_id"] == "user"
    flow._server_data = {"api_url": URL, "bearer_token": TOKEN}
    flow._robots = {ROBOT: "Test robot"}
    assert (await flow.async_step_robot({"robot_id": "unknown"}))["errors"] == {
        "base": "invalid_input"
    }
