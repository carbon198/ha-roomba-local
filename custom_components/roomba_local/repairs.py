"""Repair an unsupported saved cleaning preference without commanding the robot."""

from typing import Any

import probatio as vol

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult as FlowResult
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntryState

from .const import CONF_CLEANING_MODE, DOMAIN


class CleaningModeRepair(RepairsFlow):
    def __init__(self, entry_id: str) -> None:
        self.entry_id = entry_id

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entry = self.hass.config_entries.async_get_entry(self.entry_id)
        if entry is None or entry.domain != DOMAIN:
            return self.async_abort(reason="entry_removed")
        if entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="entry_not_loaded")
        modes = entry.runtime_data.data.cleaning_modes
        if not modes:
            return self.async_abort(reason="no_modes")
        if user_input is not None:
            mode = user_input[CONF_CLEANING_MODE]
            if type(mode) is int and mode in modes:
                self.hass.config_entries.async_update_entry(
                    entry, options={**entry.options, CONF_CLEANING_MODE: mode}
                )
                entry.runtime_data._async_metadata(entry.runtime_data.data)
                entry.runtime_data.async_update_listeners()
                return self.async_create_entry(data={})
        return self.async_show_form(
            step_id="confirm",
            errors={"base": "unsupported_mode"} if user_input is not None else {},
            data_schema=vol.Schema({vol.Required(CONF_CLEANING_MODE): vol.In(modes)}),
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    assert data is not None
    return CleaningModeRepair(data["entry_id"])
