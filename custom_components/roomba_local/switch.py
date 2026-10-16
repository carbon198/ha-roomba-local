from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .setting_entity import LocalSetting, setup_settings

if TYPE_CHECKING:
    from . import LocalConfigEntry

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: "LocalConfigEntry",
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    setup_settings(entry, async_add_entities, "switch", LocalSettingSwitch)


class LocalSettingSwitch(LocalSetting, SwitchEntity):
    @property
    def is_on(self) -> bool | None:
        setting = self.setting
        return bool(setting["value"]) if setting is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.async_set_value(1 if self.setting and self.setting["options"] else True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.async_set_value(0 if self.setting and self.setting["options"] else False)
