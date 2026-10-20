from datetime import datetime
from time import monotonic
from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import LocalEntity
from .map_labels import map_number
from .presentation import LABELS, expose_field, state_key
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
        [
            LocalSensor(coordinator, field)
            for field in coordinator.data.fields
            if field["kind"] == "sensor" and expose_field(field)
        ]
        + [ACMEDNSChallengeSensor(coordinator)]
    )


class ACMEDNSChallengeSensor(LocalEntity, SensorEntity):
    def __init__(self, coordinator: LocalCoordinator) -> None:
        super().__init__(
            coordinator,
            {
                "key": "acme_dns_challenge",
                "name": "ACME DNS challenge",
                "entity_category": "diagnostic",
            },
        )
        self._attr_icon = "mdi:certificate-outline"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> str | None:
        challenge = self.coordinator.data.acme_dns_challenge
        return challenge["value"] if challenge is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        challenge = self.coordinator.data.acme_dns_challenge
        return {"name": challenge["name"], "type": challenge["type"]} if challenge else {}


class LocalSensor(LocalEntity, SensorEntity):
    def __init__(self, coordinator: LocalCoordinator, field: FieldDescriptor) -> None:
        super().__init__(coordinator, field)
        device_class = field.get("device_class")
        self._attr_device_class = (
            SensorDeviceClass(device_class) if device_class is not None else None
        )
        self._attr_native_unit_of_measurement = field.get("unit_of_measurement")
        state_class = (
            "total_increasing"
            if self.key.endswith("_count")
            and self.key.startswith(("stats_", "charge_", "navigation_"))
            else field.get("state_class")
        )
        self._attr_state_class = SensorStateClass(state_class) if state_class is not None else None
        if self.key in LABELS:
            self._attr_device_class = SensorDeviceClass.ENUM
        self._last_data_value = coordinator.data.values.get(self.key)
        self._last_data_updated = monotonic()
        self._last_data_available = self.available

    def _handle_coordinator_update(self) -> None:
        if self.key == "last_data_received":
            now = monotonic()
            availability = self.available
            if now - self._last_data_updated < 30 and availability == self._last_data_available:
                return
            self._last_data_value = self.coordinator.data.values.get(self.key)
            self._last_data_updated = now
            self._last_data_available = availability
        super()._handle_coordinator_update()

    @property
    def options(self) -> list[str] | None:
        if self.key not in LABELS:
            return None
        options = {state_key(value) for value in LABELS[self.key]}
        current = self.coordinator.data.values.get(self.key)
        if current is not None:
            options.add(state_key(current))
        return sorted(options)

    @property
    def native_value(self) -> str | int | datetime | None:
        value = (
            self._last_data_value
            if self.key == "last_data_received"
            else self.coordinator.data.values.get(self.key)
        )
        if self.key == "localized_map" and isinstance(value, str):
            return f"Map {map_number(self.coordinator.config_entry, value)}"
        if isinstance(value, str) and self.device_class == "timestamp":
            return datetime.fromisoformat(value)
        if value is not None and self.key in LABELS:
            return state_key(value)
        return value

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        if self.key == "localized_map":
            return {"map_id": self.coordinator.data.values.get(self.key)}
        if self.key in LABELS:
            return {"raw_value": self.coordinator.data.values.get(self.key)}
        return {}
