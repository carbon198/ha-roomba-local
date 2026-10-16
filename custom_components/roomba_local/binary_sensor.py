from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import LocalEntity
from .presentation import expose_field
from .models import FieldDescriptor
from .coordinator import LocalCoordinator

if TYPE_CHECKING:
    from . import LocalConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: "LocalConfigEntry",
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        LocalBinarySensor(coordinator, field)
        for field in coordinator.data.fields
        if field["kind"] == "binary_sensor" and expose_field(field)
    )


class LocalBinarySensor(LocalEntity, BinarySensorEntity):
    def __init__(self, coordinator: LocalCoordinator, field: FieldDescriptor) -> None:
        super().__init__(coordinator, field)
        device_class = field.get("device_class")
        self._attr_device_class = BinarySensorDeviceClass(device_class) if device_class else None

    @property
    def is_on(self) -> bool | None:
        value = self.coordinator.data.values.get(self.key)
        return value if isinstance(value, bool) else None
