"""One-shot dock operations; no automatic retry or optimistic state changes."""

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import CannotConnect, InvalidAuth
from .coordinator import LocalCoordinator
from .entity import device_info
from .errors import error

if TYPE_CHECKING:
    from . import LocalConfigEntry

PARALLEL_UPDATES = 1
COMMANDS = {
    "evacuate_bin": ("evac", "mdi:delete-empty"),
    "start_pad_drying": ("drypad", "mdi:weather-sunny"),
    "stop_pad_drying": ("stoppaddry", "mdi:stop"),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: "LocalConfigEntry",
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(LocalDockButton(entry.runtime_data, key) for key in COMMANDS)


class LocalDockButton(CoordinatorEntity[LocalCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: LocalCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self.command, self._attr_icon = COMMANDS[key]
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{key}"
        self._attr_device_info = device_info(coordinator)

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (
            super().available
            and data.values.get("robot_mqtt_connection") is True
            and data.available.get("mission_phase", False)
            and data.available.get("mission_cycle", False)
            and data.values.get("mission_phase") == "charge"
            and data.values.get("mission_cycle") == "none"
        )

    async def async_press(self) -> None:
        if not self.available:
            raise error("dock_required")
        try:
            await self.coordinator.api.command(self.command)
        except InvalidAuth as exc:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise error("invalid_auth") from exc
        except CannotConnect as exc:
            raise error("delivery_failed") from exc
        except ValueError as exc:
            raise error("invalid_command") from exc
