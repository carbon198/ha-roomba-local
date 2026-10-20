"""Validate protocol boundaries, including optional older-server extensions."""

from copy import deepcopy

import pytest

from custom_components.roomba_local.models import Telemetry, normalize_url, validate_credentials

from .conftest import ROBOT, TOKEN


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:pass@example.com",
        "https://example.com/path",
        "https://example.com/?query",
        "https://example.com/#fragment",
        "https://example.com:0",
        "https://exa mple.com",
        "https://example.com:invalid",
        "https://",
    ],
)
def test_invalid_urls(url):
    with pytest.raises(ValueError):
        normalize_url(url)


def test_credentials_and_older_server(document):
    assert normalize_url("https://example.com/") == "https://example.com"
    for token, robot in (("short", ROBOT), (TOKEN, "bad")):
        with pytest.raises(ValueError):
            validate_credentials(token, robot)
    minimal = {
        key: value
        for key, value in document.items()
        if key in ("schema_version", "robot_id", "online", "fields", "values", "available")
    }
    data = Telemetry.parse(minimal, ROBOT)
    assert data.device == {}
    assert data.position is None
    assert data.acme_dns_challenge is None
    assert data.map_inventory is None
    assert not data.segment_catalog_complete


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("robot_id", "b" * 32),
        ("online", 1),
        ("fields", []),
        ("fields", None),
        ("values", []),
        ("available", {}),
        ("reported_at", "1"),
        ("segment_catalog_complete", 1),
        ("segments", None),
        ("segments", [{}] * 101),
        ("cleaning_modes", [2, 2]),
        ("cleaning_modes", [True]),
        ("cleaning_modes", [3]),
        ("settings", None),
        ("settings", [{}] * 33),
        ("maps", None),
        ("maps", [{}] * 11),
        ("map_inventory", ["one", "one"]),
        ("map_inventory", [None]),
        ("map_inventory", "one"),
        ("map_inventory", ["bad/id"]),
        ("map_inventory", list(map(str, range(11)))),
        ("position", {}),
        ("position", []),
        ("segment_colors", {"bad": "Blue"}),
        ("segment_colors", {"one:1:1": "Bad"}),
        ("segment_colors", []),
        ("map_overlays", None),
        ("map_overlays", [{}] * 11),
        ("device", None),
        ("device", {"password": "bad"}),
        ("device", {"model": ""}),
        ("device", {"model": 1}),
        ("device", {"serial_number": "bad\nvalue"}),
        ("device", {"sw_version": "x" * 129}),
    ],
)
def test_invalid_document_fields(document, key, bad):
    document[key] = bad
    with pytest.raises(ValueError):
        Telemetry.parse(document, ROBOT)


@pytest.mark.parametrize(
    "challenge",
    [
        [],
        {},
        {"name": "bad", "type": "TXT", "value": "a" * 43},
        {"name": 1, "type": "TXT", "value": "a" * 43},
        {"name": "_acme-challenge." + "a" * 256, "type": "TXT", "value": "a" * 43},
        {"name": "_acme-challenge.example.com", "type": "A", "value": "a" * 43},
        {"name": "_acme-challenge.example.com", "type": "TXT", "value": 1},
        {"name": "_acme-challenge.example.com", "type": "TXT", "value": "short"},
        {"name": "_acme-challenge.example.com", "type": "TXT", "value": "a" * 42 + "\n"},
    ],
)
def test_invalid_acme_challenge(document, challenge):
    with pytest.raises(ValueError, match="Invalid ACME DNS challenge"):
        Telemetry.parse(document | {"acme_dns_challenge": challenge}, ROBOT)


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("key", "Bad key"),
        ("key", 1),
        ("name", ""),
        ("name", 1),
        ("kind", "switch"),
        ("device_class", 42),
        ("state_class", "x" * 65),
    ],
)
def test_invalid_field_descriptors(document, key, bad):
    document["fields"][0][key] = bad
    with pytest.raises(ValueError):
        Telemetry.parse(document, ROBOT)


def test_field_values(document):
    for update in (
        {"fields": document["fields"] * 2},
        {"values": document["values"] | {"battery": None}},
        {"values": document["values"] | {"bin_present": 1}},
        {"values": document["values"] | {"last_data_received": "2026-10-16"}},
        {"values": document["values"] | {"last_data_received": 1}},
        {"values": document["values"] | {"unexpected": "bad"}},
        {"available": document["available"] | {"battery": 1}},
        {"values": {key: value for key, value in document["values"].items() if key != "battery"}},
    ):
        with pytest.raises(ValueError):
            Telemetry.parse(document | update, ROBOT)
    document["values"].pop("battery")
    document["available"]["battery"] = False
    assert "battery" not in Telemetry.parse(document, ROBOT).values
    with pytest.raises(ValueError):
        Telemetry.parse(None, ROBOT)


@pytest.mark.parametrize(
    ("section", "key", "bad"),
    [
        ("segments", "id", "bad"),
        ("segments", "name", "\n"),
        ("segments", "group", ""),
        ("settings", "key", "Bad"),
        ("settings", "name", ""),
        ("settings", "kind", "bad"),
        ("settings", "value", "bad"),
        ("settings", "options", []),
        ("settings", "options", {"bad": "On"}),
        ("settings", "options", {"0": ""}),
        ("settings", "options", {"0": "On", "1": "On"}),
        ("settings", "options", {"0": "Off", "1": "On"}),
        ("maps", "id", "bad/id"),
        ("maps", "version", None),
        ("maps", "revision", "bad"),
        ("map_overlays", "map_id", None),
        ("map_overlays", "revision", -1),
        ("map_overlays", "point_count", 12001),
        ("map_overlays", "truncated", 1),
        ("map_overlays", "status", "bad"),
    ],
)
def test_invalid_catalog_items(document, section, key, bad):
    document[section][0][key] = bad
    with pytest.raises(ValueError):
        Telemetry.parse(document, ROBOT)


def test_catalog_edge_cases(document):
    for section in ("segments", "settings", "maps", "map_overlays"):
        changed = deepcopy(document)
        changed[section] *= 2
        with pytest.raises(ValueError):
            Telemetry.parse(changed, ROBOT)
        changed[section] = [None]
        with pytest.raises(ValueError):
            Telemetry.parse(changed, ROBOT)
    for field, value in (("x", float("nan")), ("map_id", "bad/id"), ("heading", "bad")):
        changed = deepcopy(document)
        changed["position"][field] = value
        with pytest.raises(ValueError):
            Telemetry.parse(changed, ROBOT)
    for update in ({"value": 2}, {"value": 1, "options": {"1": "On"}}, {"kind": "select"}):
        changed = deepcopy(document)
        changed["settings"][0].update(update)
        with pytest.raises(ValueError):
            Telemetry.parse(changed, ROBOT)
