from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .setting_entity import LocalSetting, setup_settings
from .entity import LocalEntity
from .const import CLEANING_MODES, CONF_CLEANING_MODE, DEFAULT_CLEANING_MODE
from homeassistant.const import EntityCategory
from .coordinator import LocalCoordinator
from .errors import error

if TYPE_CHECKING:
    from . import LocalConfigEntry

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: "LocalConfigEntry",
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_settings(entry, async_add_entities, "select", LocalSettingSelect)
    async_add_entities([CleaningModeSelect(entry.runtime_data)])


class CleaningModeSelect(LocalEntity, SelectEntity):
    """A persisted local command preference, not robot-reported mission state."""

    def __init__(self, coordinator: LocalCoordinator) -> None:
        super().__init__(coordinator, {"key": "cleaning_mode", "name": "Cleaning mode"})
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_icon = "mdi:robot-vacuum"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def options(self) -> list[str]:
        return [
            name
            for mode, name in CLEANING_MODES.items()
            if mode in self.coordinator.data.cleaning_modes
        ]

    @property
    def current_option(self) -> str | None:
        mode = self.coordinator.config_entry.options.get(CONF_CLEANING_MODE, DEFAULT_CLEANING_MODE)
        return (
            CLEANING_MODES.get(mode)
            if type(mode) is int and mode in self.coordinator.data.cleaning_modes
            else None
        )

    async def async_select_option(self, option: str) -> None:
        if option not in self.options:
            raise error("unsupported_mode")
        options = dict(self.coordinator.config_entry.options)
        options[CONF_CLEANING_MODE] = next(
            mode for mode, name in CLEANING_MODES.items() if name == option
        )
        self.hass.config_entries.async_update_entry(self.coordinator.config_entry, options=options)
        self.coordinator._async_metadata(self.coordinator.data)
        self.async_write_ha_state()


class LocalSettingSelect(LocalSetting, SelectEntity):
    @property
    def options(self) -> list[str]:
        setting = self.setting
        return [f"option_{key}" for key in setting["options"]] if setting is not None else []

    @property
    def current_option(self) -> str | None:
        setting = self.setting
        return f"option_{setting['value']}" if setting is not None else None

    async def async_select_option(self, option: str) -> None:
        setting = self.setting
        if setting is None or option not in self.options:
            raise error("unsupported_option")
        value = int(option.removeprefix("option_"))
        await self.async_set_value(value)
