"""One-shot dock operations gated by reported capabilities; no automatic retries."""

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
    "wash_mop_pad": ("washpad", "mdi:water"),
}
DOCK_CAPABILITIES: dict[str, tuple[str, frozenset[int]]] = {
    "evacuate_bin": ("dock_cap_evacuate", frozenset({1})),
    "start_pad_drying": ("dock_cap_pad_dry", frozenset({1, 2, 3})),
    "stop_pad_drying": ("dock_cap_pad_dry", frozenset({1, 2, 3})),
    "wash_mop_pad": ("dock_cap_pad_wash", frozenset({1, 2, 3, 4})),
}


def _capability_supported(coordinator: LocalCoordinator, button_key: str) -> bool:
    capability, supported_values = DOCK_CAPABILITIES[button_key]
    data = coordinator.data
    value = data.values.get(capability)
    return (
        data.available.get(capability) is True and type(value) is int and value in supported_values
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: "LocalConfigEntry",
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    added: set[str] = set()

    def discover_supported_buttons() -> None:
        if not coordinator.last_update_success:
            return
        keys = [
            key for key in COMMANDS if key not in added and _capability_supported(coordinator, key)
        ]
        if keys:
            async_add_entities([LocalDockButton(coordinator, key) for key in keys])
            added.update(keys)

    entry.async_on_unload(coordinator.async_add_listener(discover_supported_buttons))
    discover_supported_buttons()


class LocalDockButton(CoordinatorEntity[LocalCoordinator], ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: LocalCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self.key = key
        self.command, self._attr_icon = COMMANDS[key]
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_{key}"
        self._attr_device_info = device_info(coordinator)

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return (
            super().available
            and _capability_supported(self.coordinator, self.key)
            and data.values.get("robot_mqtt_connection") is True
            and data.available.get("mission_phase", False)
            and data.available.get("mission_cycle", False)
            and data.values.get("mission_phase") == "charge"
            and data.values.get("mission_cycle") == "none"
        )

    async def async_press(self) -> None:
        if not _capability_supported(self.coordinator, self.key):
            raise error("unsupported_option")
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
