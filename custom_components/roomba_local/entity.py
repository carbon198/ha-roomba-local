from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .presentation import ICONS, NAMES, TRANSLATED_FIELDS, diagnostic
from .models import FieldDescriptor

if TYPE_CHECKING:
    from .coordinator import LocalCoordinator


def device_info(coordinator: LocalCoordinator) -> DeviceInfo:
    """Keep registry identity stable while refreshing reported device details."""
    details = coordinator.data.device.copy()
    firmware = coordinator.data.values.get("firmware_version")
    if "sw_version" not in details and isinstance(firmware, str):
        details["sw_version"] = firmware
    assert coordinator.config_entry.unique_id is not None
    info = DeviceInfo(
        identifiers={(DOMAIN, coordinator.config_entry.unique_id)},
        name=coordinator.config_entry.title,
        manufacturer="iRobot",
    )
    if "model" in details:
        info["model"] = details["model"]
    if "serial_number" in details:
        info["serial_number"] = details["serial_number"]
    if "sw_version" in details:
        info["sw_version"] = details["sw_version"]
    return info


class LocalEntity(CoordinatorEntity["LocalCoordinator"]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: LocalCoordinator, field: FieldDescriptor) -> None:
        super().__init__(coordinator)
        self.field = field
        self.key = field["key"]
        assert coordinator.config_entry.unique_id is not None
        self._attr_unique_id = coordinator.config_entry.unique_id + "_" + self.key
        if self.key not in TRANSLATED_FIELDS and self.key != "vacuum":
            self._attr_name = NAMES.get(self.key, field["name"])
        self._attr_translation_key = self.key
        self._attr_icon = ICONS.get(self.key)
        category = "diagnostic" if diagnostic(self.key) else field.get("entity_category")
        self._attr_entity_category = EntityCategory(category) if category is not None else None
        self._attr_entity_registry_enabled_default = self.key not in (
            "runtime_hours_raw",
            "runtime_minutes_raw",
        )

    @property
    def device_info(self) -> DeviceInfo:
        return device_info(self.coordinator)

    @property
    def available(self) -> bool:
        data = self.coordinator.data
        return super().available and data.available.get(self.key, False)
