"""Validate the versioned telemetry contract without exposing raw response data."""

from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
import math
import re
from urllib.parse import urlsplit
from typing import Any, NotRequired, TypedDict, cast


class FieldDescriptor(TypedDict):
    key: str
    name: str
    kind: NotRequired[str]
    device_class: NotRequired[str]
    unit_of_measurement: NotRequired[str]
    state_class: NotRequired[str]
    entity_category: NotRequired[str]


class SettingDescriptor(TypedDict):
    key: str
    name: str
    kind: str
    value: bool | int
    options: dict[str, str]


class Position(TypedDict):
    map_id: str
    x: float
    y: float
    heading: float
    timestamp: float
    sequence: float
    received_at: float
    expires_at: float


class MapOverlay(TypedDict):
    map_id: str
    revision: int
    status: str
    point_count: int
    truncated: bool


class DeviceMetadata(TypedDict, total=False):
    model: str
    serial_number: str
    sw_version: str


def normalize_url(value: str) -> str:
    url = urlsplit(value.strip())
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.path not in ("", "/")
        or url.query
        or url.fragment
        or url.port == 0
        or any(char.isspace() for char in value)
    ):
        raise ValueError("Expected an HTTPS origin")
    return url._replace(path="", fragment="", query="").geturl().rstrip("/")


def validate_token(token: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token):
        raise ValueError("Invalid token format")


def validate_credentials(token: str, robot_id: str) -> None:
    validate_token(token)
    if not re.fullmatch(r"[0-9A-Fa-f]{32}", robot_id):
        raise ValueError("Invalid robot ID")


@dataclass(frozen=True)
class Telemetry:
    robot_id: str
    online: bool
    reported_at: int | None
    fields: list[FieldDescriptor]
    values: dict[str, str | int | bool]
    available: dict[str, bool]
    segments: list[dict[str, str]] = dataclass_field(default_factory=list)
    settings: list[SettingDescriptor] = dataclass_field(default_factory=list)
    cleaning_modes: list[int] = dataclass_field(default_factory=list)
    segment_catalog_complete: bool = False
    maps: list[dict[str, str]] = dataclass_field(default_factory=list)
    position: Position | None = None
    segment_colors: dict[str, str] = dataclass_field(default_factory=dict)
    map_overlays: list[MapOverlay] = dataclass_field(default_factory=list)
    map_inventory: list[str] | None = None
    device: DeviceMetadata = dataclass_field(default_factory=DeviceMetadata)

    @classmethod
    def parse(cls, data: Any, robot_id: str) -> Telemetry:
        if (
            not isinstance(data, dict)
            or type(data.get("schema_version")) is not int
            or data["schema_version"] != 1
            or data.get("robot_id") != robot_id
            or type(data.get("online")) is not bool
            or not isinstance(data.get("fields"), list)
            or not 1 <= len(data["fields"]) <= 100
            or not isinstance(data.get("values"), dict)
            or not isinstance(data.get("available"), dict)
            or (data.get("reported_at") is not None and type(data["reported_at"]) is not int)
        ):
            raise ValueError("Invalid telemetry response")
        keys = set()
        for field in data["fields"]:
            if (
                not isinstance(field, dict)
                or not isinstance(field.get("key"), str)
                or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", field["key"])
                or field["key"] in keys
                or not isinstance(field.get("name"), str)
                or not 1 <= len(field["name"]) <= 128
                or field.get("kind") not in ("sensor", "binary_sensor")
            ):
                raise ValueError("Invalid field descriptor")
            key = field["key"]
            keys.add(key)
            for name in ("device_class", "unit_of_measurement", "state_class", "entity_category"):
                if name in field and (not isinstance(field[name], str) or len(field[name]) > 64):
                    raise ValueError("Invalid field metadata")
            if type(data["available"].get(key)) is not bool:
                raise ValueError("Invalid field availability")
            if key not in data["values"]:
                if data["available"][key]:
                    raise ValueError("Available field has no value")
                continue
            value = data["values"][key]
            if field["kind"] == "binary_sensor":
                valid = type(value) is bool
            else:
                valid = type(value) in (str, int)
                if field.get("device_class") == "timestamp":
                    valid = isinstance(value, str)
                    if valid:
                        parsed = datetime.fromisoformat(value)
                        valid = parsed.tzinfo is not None
            if not valid:
                raise ValueError("Invalid telemetry value")
        if set(data["available"]) != keys or not set(data["values"]) <= keys:
            raise ValueError("Unexpected telemetry fields")
        segments = data.get("segments", [])
        complete = data.get("segment_catalog_complete", False)
        if type(complete) is not bool:
            raise ValueError("Invalid segment catalog completeness")
        if not isinstance(segments, list) or len(segments) > 100:
            raise ValueError("Invalid segment catalog")
        segment_ids = set()
        for segment in segments:
            if (
                not isinstance(segment, dict)
                or set(segment) != {"id", "name", "group"}
                or not isinstance(segment["id"], str)
                or not re.fullmatch(
                    r"[A-Za-z0-9_.-]{1,128}:[A-Za-z0-9_.-]{1,128}:[0-9]{1,10}", segment["id"]
                )
                or segment["id"] in segment_ids
                or any(
                    not isinstance(segment[k], str)
                    or not 1 <= len(segment[k]) <= 160
                    or any(ord(c) < 32 for c in segment[k])
                    for k in ("name", "group")
                )
            ):
                raise ValueError("Invalid segment descriptor")
            segment_ids.add(segment["id"])
        settings = data.get("settings", [])
        cleaning_modes = data.get("cleaning_modes", [])
        if (
            not isinstance(cleaning_modes, list)
            or len(cleaning_modes) > 3
            or any(type(mode) is not int or mode not in (2, 4, 6) for mode in cleaning_modes)
            or len(set(cleaning_modes)) != len(cleaning_modes)
        ):
            raise ValueError("Invalid cleaning modes")
        if not isinstance(settings, list) or len(settings) > 32:
            raise ValueError("Invalid settings list")
        setting_keys = set()
        for setting in settings:
            if (
                not isinstance(setting, dict)
                or set(setting) != {"key", "name", "kind", "value", "options"}
                or not isinstance(setting["key"], str)
                or not re.fullmatch(r"[a-z][a-z_]{0,63}", setting["key"])
                or setting["key"] in setting_keys
                or not isinstance(setting["name"], str)
                or not 1 <= len(setting["name"]) <= 128
                or setting["kind"] not in ("switch", "select")
                or type(setting["value"]) not in (bool, int)
                or not isinstance(setting["options"], dict)
                or len(setting["options"]) > 32
            ):
                raise ValueError("Invalid setting descriptor")
            options = setting["options"]
            if any(
                not isinstance(k, str)
                or not re.fullmatch(r"[0-9]{1,3}", k)
                or not isinstance(v, str)
                or not 1 <= len(v) <= 128
                for k, v in options.items()
            ):
                raise ValueError("Invalid setting options")
            if len(set(options.values())) != len(options):
                raise ValueError("Duplicate setting options")
            if setting["kind"] == "select" and (type(setting["value"]) is not int or not options):
                raise ValueError("Select requires integer options")
            if setting["kind"] == "switch" and (
                (type(setting["value"]) is bool and options)
                or (type(setting["value"]) is int and set(options) != {"0", "1"})
            ):
                raise ValueError("Invalid switch options")
            if options and str(setting["value"]) not in options:
                raise ValueError("Setting value is outside options")
            setting_keys.add(setting["key"])
        maps = data.get("maps", [])
        inventory = data.get("map_inventory")
        if inventory is not None and (
            not isinstance(inventory, list)
            or len(inventory) > 10
            or any(
                not isinstance(identifier, str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", identifier)
                for identifier in inventory
            )
            or len(set(inventory)) != len(inventory)
        ):
            raise ValueError("Invalid robot map inventory")
        if not isinstance(maps, list) or len(maps) > 10:
            raise ValueError("Invalid map image catalog")
        map_ids = set()
        for item in maps:
            if (
                not isinstance(item, dict)
                or set(item) != {"id", "version", "revision"}
                or any(
                    not isinstance(item[k], str)
                    or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", item[k])
                    for k in ("id", "version")
                )
                or not isinstance(item["revision"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", item["revision"])
                or item["id"] in map_ids
            ):
                raise ValueError("Invalid map image descriptor")
            map_ids.add(item["id"])
        position = data.get("position")
        if position is not None:
            if (
                not isinstance(position, dict)
                or set(position)
                != {
                    "map_id",
                    "x",
                    "y",
                    "heading",
                    "timestamp",
                    "sequence",
                    "received_at",
                    "expires_at",
                }
                or not isinstance(position["map_id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", position["map_id"])
                or any(
                    type(position[k]) not in (int, float) or not math.isfinite(position[k])
                    for k in (
                        "x",
                        "y",
                        "heading",
                        "timestamp",
                        "sequence",
                        "received_at",
                        "expires_at",
                    )
                )
            ):
                raise ValueError("Invalid live position")
        segment_colors = data.get("segment_colors", {})
        if (
            not isinstance(segment_colors, dict)
            or not set(segment_colors) <= segment_ids
            or any(
                value
                not in (
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
                for value in segment_colors.values()
            )
        ):
            raise ValueError("Invalid segment colors")
        overlays = data.get("map_overlays", [])
        if not isinstance(overlays, list) or len(overlays) > 10:
            raise ValueError("Invalid map overlays")
        overlay_ids = set()
        for item in overlays:
            if (
                not isinstance(item, dict)
                or set(item) != {"map_id", "revision", "status", "point_count", "truncated"}
                or not isinstance(item["map_id"], str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", item["map_id"])
                or item["map_id"] in overlay_ids
                or type(item["revision"]) is not int
                or item["revision"] < 0
                or type(item["point_count"]) is not int
                or not 0 <= item["point_count"] <= 12000
                or type(item["truncated"]) is not bool
                or item["status"] not in ("live", "last_known", "docked", "unavailable")
            ):
                raise ValueError("Invalid map overlay")
            overlay_ids.add(item["map_id"])
        device = data.get("device", {})
        if (
            not isinstance(device, dict)
            or not set(device) <= {"model", "serial_number", "sw_version"}
            or any(
                not isinstance(value, str)
                or not 1 <= len(value) <= 128
                or any(ord(char) < 32 for char in value)
                for value in device.values()
            )
        ):
            raise ValueError("Invalid device metadata")
        return cls(
            robot_id,
            data["online"],
            data.get("reported_at"),
            cast(list[FieldDescriptor], data["fields"]),
            data["values"],
            data["available"],
            segments,
            cast(list[SettingDescriptor], settings),
            cleaning_modes,
            complete,
            maps,
            cast(Position | None, position),
            segment_colors,
            cast(list[MapOverlay], overlays),
            inventory,
            cast(DeviceMetadata, device),
        )
