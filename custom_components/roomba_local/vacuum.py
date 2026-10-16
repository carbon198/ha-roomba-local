"""Basic Prime mission controls; status is always robot-reported."""

from typing import TYPE_CHECKING, Any

from homeassistant.components.vacuum import Segment, StateVacuumEntity
from homeassistant.components.vacuum.const import VacuumActivity, VacuumEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import CannotConnect, InvalidAuth
from .entity import LocalEntity
from .const import CLEANING_MODES, CONF_CLEANING_MODE, DEFAULT_CLEANING_MODE
from .map_labels import display_segments
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
    async_add_entities([LocalVacuum(entry.runtime_data)])


class LocalVacuum(LocalEntity, StateVacuumEntity):
    _attr_name = None
    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.LOCATE
        | VacuumEntityFeature.STATE
    )

    def __init__(self, coordinator: LocalCoordinator) -> None:
        super().__init__(coordinator, {"key": "vacuum", "name": "Roomba"})
        self._attr_name = None
        self._attr_icon = "mdi:robot-vacuum"

    @property
    def supported_features(self) -> VacuumEntityFeature:
        features = self._attr_supported_features
        if self.coordinator.data.segments:
            features |= VacuumEntityFeature.CLEAN_AREA
        return features

    async def async_get_segments(self) -> list[Segment]:
        return self._display_segments()

    def _display_segments(self) -> list[Segment]:
        return [
            Segment(id=segment["id"], name=segment["name"], group=segment["group"])
            for segment in display_segments(
                self.coordinator.config_entry,
                self.coordinator.data.segments,
                self.coordinator.data.segment_colors,
            )
        ]

    async def async_clean_segments(self, segment_ids: list[str], **kwargs: Any) -> None:
        known = {segment["id"] for segment in self.coordinator.data.segments}
        if (
            not segment_ids
            or any(identifier not in known for identifier in segment_ids)
            or len(set(segment_ids)) != len(segment_ids)
        ):
            raise error("invalid_segments")
        await self._command("clean_segments", segment_ids)

    def _handle_coordinator_update(self) -> None:
        self._sync_segments()
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._sync_segments()

    def _sync_segments(self) -> None:
        if (
            not self.coordinator.last_update_success
            or self.registry_entry is None
            or self.last_seen_segments is None
        ):
            return
        previous = self.last_seen_segments
        current = self._display_segments()

        def identity(segment: Segment) -> tuple[str, str]:
            map_id, _, region_id = segment.id.split(":")
            return map_id, region_id

        old = {identity(segment): segment for segment in previous}
        new = {identity(segment): segment for segment in current}
        present_maps = {map_id for map_id, _ in new}
        compared_old = {
            key: value
            for key, value in old.items()
            if self.coordinator.data.segment_catalog_complete or key[0] in present_maps
        }
        if compared_old.keys() != new.keys() or any(
            (self._base_name(old[key], key), self._base_group(old[key], key))
            != (self._base_name(segment, key), segment.group)
            for key, segment in new.items()
        ):
            self.async_create_segments_issue()
            return
        replacements = {
            old[key].id: segment.id for key, segment in new.items() if old[key].id != segment.id
        }
        if replacements or any(
            (old[key].name, old[key].group) != (segment.name, segment.group)
            for key, segment in new.items()
        ):
            options = dict(self.registry_entry.options.get("vacuum", {}))
            options["last_seen_segments"] = [
                {
                    "id": new[identity(segment)].id,
                    "name": new[identity(segment)].name,
                    "group": new[identity(segment)].group,
                }
                if identity(segment) in new
                else {"id": segment.id, "name": segment.name, "group": segment.group}
                for segment in previous
            ]
            if "area_mapping" in options:
                options["area_mapping"] = {
                    area: [replacements.get(identifier, identifier) for identifier in identifiers]
                    for area, identifiers in options["area_mapping"].items()
                }
            er.async_get(self.hass).async_update_entity_options(self.entity_id, "vacuum", options)
        if self.coordinator.data.segment_catalog_complete or old.keys() == new.keys():
            ir.async_delete_issue(self.hass, "vacuum", f"segments_changed_{self.registry_entry.id}")

    def _base_name(self, segment: Segment, key: tuple[str, str]) -> str:
        current = next(
            (
                item
                for item in self.coordinator.data.segments
                if (item["id"].split(":")[0], item["id"].split(":")[2]) == key
            ),
            None,
        )
        if current is not None:
            if any(
                segment.name == f"{current['name']} ({color})"
                for color in (
                    "Blue",
                    "Magenta",
                    "Cyan",
                    "Green",
                    "Yellow",
                    "Purple",
                    "Orange",
                    "Red",
                    "Rose",
                    "Teal",
                    "Gold",
                    "Brown",
                    "Slate blue",
                )
            ):
                return current["name"]
        return segment.name

    def _base_group(self, segment: Segment, key: tuple[str, str]) -> str | None:
        if segment.group == f"Map {key[0]}":
            return f"Map {self.coordinator.config_entry.options['map_numbers'][key[0]]}"
        return segment.group

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.data.values.get("robot_mqtt_connection") is True
        )

    @property
    def activity(self) -> VacuumActivity | None:
        values = self.coordinator.data.values
        if not values or "mission_phase" not in values:
            return None
        phase = values["mission_phase"]
        if phase in ("stuck", "error", "chargingError", "chgerr", "chargingerror"):
            return VacuumActivity.ERROR
        if phase in ("hmPostMsn", "hmMidMsn", "hmUsrDock", "hmUsrChrg"):
            return VacuumActivity.RETURNING
        if phase in ("charge", "idle") and values.get("mission_cycle") in ("none", None):
            return VacuumActivity.DOCKED if phase == "charge" else VacuumActivity.IDLE
        if phase in ("pause", "stop") and values.get("mission_cycle") not in ("none", None):
            return VacuumActivity.PAUSED
        if phase in (
            "run",
            "resume",
            "room",
            "zone",
            "polygon",
            "oClean",
            "travel",
            "traversal",
            "reloc",
            "explore",
            "plan",
        ):
            return VacuumActivity.CLEANING
        if phase == "stop":
            return VacuumActivity.IDLE
        return None

    async def _command(self, command: str, segment_ids: list[str] | None = None) -> None:
        if not self.available:
            raise error("unavailable")
        try:
            mode = self.coordinator.config_entry.options.get(
                CONF_CLEANING_MODE, DEFAULT_CLEANING_MODE
            )
            if command in ("start", "clean_segments"):
                if (
                    type(mode) is not int
                    or mode not in CLEANING_MODES
                    or mode not in self.coordinator.data.cleaning_modes
                ):
                    raise error("unsupported_mode")
                await self.coordinator.api.command(command, segment_ids, operating_mode=mode)
            elif segment_ids is None:
                await self.coordinator.api.command(command)
            else:
                await self.coordinator.api.command(command, segment_ids)
        except InvalidAuth as exc:
            self.coordinator.config_entry.async_start_reauth(self.hass)
            raise error("invalid_auth") from exc
        except CannotConnect as exc:
            raise error("delivery_failed") from exc
        except ValueError as exc:
            raise error("invalid_command") from exc

    async def async_start(self) -> None:
        await self._command("start")

    async def async_pause(self) -> None:
        await self._command("pause")

    async def async_stop(self, **kwargs: Any) -> None:
        await self._command("stop")

    async def async_return_to_base(self, **kwargs: Any) -> None:
        await self._command("dock")

    async def async_locate(self, **kwargs: Any) -> None:
        await self._command("find")
