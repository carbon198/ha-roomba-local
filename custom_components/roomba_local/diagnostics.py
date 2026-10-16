from typing import TYPE_CHECKING

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .const import CONF_API_URL, CONF_BEARER_TOKEN, CONF_ROBOT_ID

if TYPE_CHECKING:
    from . import LocalConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: "LocalConfigEntry",
) -> dict[str, object]:
    diagnostics: dict[str, object] = {
        "config": async_redact_data(
            dict(entry.data), {CONF_BEARER_TOKEN, CONF_ROBOT_ID, CONF_API_URL}
        ),
        "entry_state": entry.state.value,
        "runtime_available": entry.state is ConfigEntryState.LOADED,
    }
    if entry.state is ConfigEntryState.LOADED:
        coordinator = entry.runtime_data
        diagnostics.update(
            {
                "api_reachable": coordinator.last_update_success,
                "robot_reporting": coordinator.data.online,
                "field_count": len(coordinator.data.fields),
                "settings_count": len(coordinator.data.settings),
                "map_count": len(coordinator.data.maps),
                "segment_count": len(coordinator.data.segments),
                "stream_running": coordinator.stream_running,
            }
        )
    return diagnostics
