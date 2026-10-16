"""One live cleaning image per map, updated by mission-scoped position pushes."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import CannotConnect, InvalidAuth
from .const import DOMAIN
from .map_labels import map_number
from .entity import device_info
from .coordinator import LocalCoordinator
from .models import MapOverlay, Position
from .errors import error

if TYPE_CHECKING:
    from . import LocalConfigEntry

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: "LocalConfigEntry",
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    known: set[str] = set()

    def discover() -> None:
        if not coordinator.last_update_success:
            return
        inventory = coordinator.data.map_inventory
        if inventory is not None:
            known.intersection_update(inventory)
            registry = er.async_get(hass)
            prefix = f"{entry.unique_id}_map_"
            for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
                if (
                    entity.platform != DOMAIN
                    or entity.domain != "image"
                    or not entity.unique_id.startswith(prefix)
                ):
                    continue
                identifier, separator, kind = entity.unique_id[len(prefix) :].rpartition("_")
                if separator and kind in ("live", "room") and identifier not in inventory:
                    registry.async_remove(entity.entity_id)
        entities = []
        for item in coordinator.data.maps:
            if inventory is not None and item["id"] not in inventory:
                continue
            if item["id"] not in known:
                entities.append(LocalMapImage(hass, coordinator, item["id"], "live"))
                known.add(item["id"])
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class LocalMapImage(CoordinatorEntity[LocalCoordinator], ImageEntity):
    _attr_has_entity_name = True
    _attr_content_type = "image/png"
    _attr_icon = "mdi:floor-plan"

    def __init__(
        self, hass: HomeAssistant, coordinator: LocalCoordinator, map_id: str, kind: str
    ) -> None:
        ImageEntity.__init__(self, hass)
        CoordinatorEntity.__init__(self, coordinator)
        self.map_id = map_id
        self.kind = kind
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}_map_{map_id}_{kind}"
        self._attr_translation_key = "room_map" if kind == "room" else "live_map"
        self._attr_translation_placeholders = {
            "number": str(map_number(coordinator.config_entry, map_id))
        }
        self._revision = self.image_revision
        self._image: bytes | None = None
        self._attr_image_last_updated = datetime.now(timezone.utc)

    @property
    def device_info(self) -> DeviceInfo:
        return device_info(self.coordinator)

    @property
    def descriptor(self) -> dict[str, str] | None:
        inventory = self.coordinator.data.map_inventory
        if inventory is not None and self.map_id not in inventory:
            return None
        return next(
            (item for item in self.coordinator.data.maps if item["id"] == self.map_id), None
        )

    @property
    def available(self) -> bool:
        return super().available and self.descriptor is not None

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        item = self.descriptor
        attrs: dict[str, object] = {
            "map_id": self.map_id,
            "map_version": item["version"] if item else None,
        }
        overlay = self.overlay
        if self.kind == "live":
            attrs["position_status"] = (
                overlay["status"] if overlay else ("live" if self.position else "unavailable")
            )
            if overlay:
                attrs["trail_points"] = overlay["point_count"]
                attrs["trail_truncated"] = overlay["truncated"]
        return attrs

    @property
    def position(self) -> Position | None:
        pose = self.coordinator.data.position
        return pose if pose and pose["map_id"] == self.map_id else None

    @property
    def image_revision(self) -> tuple[dict[str, str] | None, Position | None, MapOverlay | None]:
        return (self.descriptor, self.position, self.overlay)

    @property
    def overlay(self) -> MapOverlay | None:
        return next(
            (item for item in self.coordinator.data.map_overlays if item["map_id"] == self.map_id),
            None,
        )

    def _handle_coordinator_update(self) -> None:
        if self.image_revision != self._revision:
            self._revision = self.image_revision
            self._image = None
            self._attr_image_last_updated = datetime.now(timezone.utc)
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        item = self.descriptor
        revision = self.image_revision
        if not self.available or item is None:
            return None
        if self._image is not None:
            return self._image
        try:
            image = await self.coordinator.api.map_image(item, self.kind)
        except InvalidAuth as exc:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise error("invalid_auth") from exc
        except CannotConnect as exc:
            raise error("image_failed") from exc
        # A push may replace/remove the map while the HTTP request is pending.
        if self.image_revision != revision:
            return None
        self._image = image
        return image
