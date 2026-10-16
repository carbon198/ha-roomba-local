"""Shared reported-only settings behavior."""

from collections.abc import Callable
from typing import TYPE_CHECKING

from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import CannotConnect, InvalidAuth
from .entity import LocalEntity
from .coordinator import LocalCoordinator
from .models import SettingDescriptor
from .errors import error

if TYPE_CHECKING:
    from . import LocalConfigEntry


def setup_settings(
    entry: "LocalConfigEntry",
    async_add_entities: AddConfigEntryEntitiesCallback,
    kind: str,
    entity_type: Callable[[LocalCoordinator, SettingDescriptor], LocalSetting],
) -> None:
    coordinator = entry.runtime_data
    added: set[str] = set()

    def discover() -> None:
        if not coordinator.last_update_success:
            return
        new = [
            setting
            for setting in coordinator.data.settings
            if setting["kind"] == kind and setting["key"] not in added
        ]
        if new:
            async_add_entities([entity_type(coordinator, setting) for setting in new])
            added.update(setting["key"] for setting in new)

    entry.async_on_unload(coordinator.async_add_listener(discover))
    discover()


class LocalSetting(LocalEntity):
    def __init__(self, coordinator: LocalCoordinator, setting: SettingDescriptor) -> None:
        super().__init__(coordinator, {"key": setting["key"], "name": setting["name"]})
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_setting_{self.key}"
        self._attr_entity_category = EntityCategory.CONFIG

    @property
    def setting(self) -> SettingDescriptor | None:
        return next(
            (item for item in self.coordinator.data.settings if item["key"] == self.key), None
        )

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.data.values.get("robot_mqtt_connection") is True
            and self.setting is not None
        )

    async def async_set_value(self, value: bool | int) -> None:
        if not self.available:
            raise error("unavailable")
        try:
            await self.coordinator.api.set_setting(self.key, value)
        except InvalidAuth as exc:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise error("invalid_auth") from exc
        except (CannotConnect, ValueError) as exc:
            raise error("delivery_failed") from exc
