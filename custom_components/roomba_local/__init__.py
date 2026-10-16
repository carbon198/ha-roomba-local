"""Home Assistant telemetry and controls from a local Roomba cloud emulator."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from .api import LocalAPI
from .const import CONF_API_URL, CONF_BEARER_TOKEN, CONF_ROBOT_ID
from .coordinator import LocalCoordinator
from .presentation import retired_unique_ids

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.VACUUM,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.IMAGE,
]
type LocalConfigEntry = ConfigEntry[LocalCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: LocalConfigEntry) -> bool:
    api = LocalAPI(
        async_get_clientsession(hass),
        entry.data[CONF_API_URL],
        entry.data[CONF_BEARER_TOKEN],
        entry.data[CONF_ROBOT_ID],
    )
    coordinator = LocalCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    assert entry.unique_id is not None
    registry = er.async_get(hass)
    obsolete = retired_unique_ids(entry.unique_id, coordinator.data.fields)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id in obsolete and entity.platform == "roomba_local":
            registry.async_remove(entity.entity_id)
        elif (
            entity.platform == "roomba_local"
            and entity.domain == "image"
            and entity.unique_id.startswith(entry.unique_id + "_map_")
            and entity.unique_id.endswith("_room")
        ):
            registry.async_remove(entity.entity_id)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LocalConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    ir.async_delete_issue(hass, "roomba_local", f"cleaning_mode_{entry.entry_id}")
    return True
