"""Stable local display numbers, independent of map IDs and versions."""

from typing import TYPE_CHECKING, cast

from homeassistant.core import HomeAssistant

from .models import Telemetry

if TYPE_CHECKING:
    from . import LocalConfigEntry

MAP_NUMBERS = "map_numbers"


def update_map_numbers(hass: HomeAssistant, entry: "LocalConfigEntry", data: Telemetry) -> None:
    stored = entry.options.get(MAP_NUMBERS, {})
    if (
        not isinstance(stored, dict)
        or any(
            not isinstance(key, str) or type(value) is not int or value < 1
            for key, value in stored.items()
        )
        or len(set(stored.values())) != len(stored)
    ):
        raise ValueError("Invalid saved map display numbers")
    numbers = dict(stored)
    identifiers = {item["id"] for item in data.maps}
    identifiers.update(data.map_inventory or [])
    localized = data.values.get("localized_map")
    if isinstance(localized, str) and localized:
        identifiers.add(localized)
    identifiers.update(segment["id"].split(":")[0] for segment in data.segments)
    for identifier in sorted(identifiers):
        if identifier not in numbers:
            numbers[identifier] = max(numbers.values(), default=0) + 1
    if numbers != stored:
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, MAP_NUMBERS: numbers}
        )


def map_number(entry: "LocalConfigEntry", identifier: str) -> int:
    return cast(dict[str, int], entry.options[MAP_NUMBERS])[identifier]


def display_segments(
    entry: "LocalConfigEntry", segments: list[dict[str, str]], colors: dict[str, str]
) -> list[dict[str, str]]:
    return [
        {
            **segment,
            "group": f"Map {map_number(entry, segment['id'].split(':')[0])}",
            "name": f"{segment['name']} ({colors[segment['id']]})"
            if segment["id"] in colors
            else segment["name"],
        }
        for segment in segments
    ]
