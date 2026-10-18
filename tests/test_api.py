"""Network boundary contracts using HA's shared HTTP client and HTTP mocker."""

import asyncio
import json

import aiohttp
import pytest

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.roomba_local.api import CannotConnect, InvalidAuth, LocalAPI

from .conftest import MAP, ROBOT, TOKEN, URL


@pytest.fixture
async def client(hass, aioclient_mock):
    return LocalAPI(async_get_clientsession(hass), URL, TOKEN, ROBOT)


@pytest.mark.parametrize("command", ["evac", "drypad", "stoppaddry", "washpad"])
async def test_dock_commands(client, aioclient_mock, command):
    aioclient_mock.post(
        URL + f"/v1/customer/robots/{ROBOT}/commands/{command}",
        json={"delivery": "acknowledged", "execution": "unconfirmed"},
    )
    await client.command(command)
    assert aioclient_mock.call_count == 1


async def test_inventory(hass, aioclient_mock):
    session = async_get_clientsession(hass)
    aioclient_mock.get(
        URL + "/v1/customer/robots",
        json={"robots": [{"robot_id": ROBOT, "sku": "N186020", "ip": "192.0.2.1"}]},
    )
    robots = await LocalAPI.robots(session, URL, TOKEN)
    assert robots[0]["robot_id"] == ROBOT
    assert aioclient_mock.mock_calls[0][3]["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"robots": None},
        {"robots": [None]},
        {"robots": [{"robot_id": 42}]},
        {"robots": [{"robot_id": "bad"}]},
        {"robots": [{"robot_id": ROBOT}] * 2},
        {"robots": [{"robot_id": ROBOT, "sku": 42}]},
        {"robots": [{"robot_id": ROBOT, "ip": ""}]},
    ],
)
async def test_invalid_inventory(hass, aioclient_mock, payload):
    aioclient_mock.get(URL + "/v1/customer/robots", json=payload)
    with pytest.raises(CannotConnect):
        await LocalAPI.robots(async_get_clientsession(hass), URL, TOKEN)


@pytest.mark.parametrize(
    ("operation", "suffix", "method"),
    [
        ("telemetry", "telemetry", "get"),
        ("events", "events", "get"),
        ("map_image", f"maps/one/1/{'a' * 64}/live.png", "get"),
        ("command", "commands/pause", "post"),
        ("set_setting", "settings/child_lock", "post"),
        ("robots", None, "get"),
    ],
)
@pytest.mark.parametrize("failure", [401, 503, "network", "timeout"])
async def test_network_errors(hass, client, aioclient_mock, operation, suffix, method, failure):
    url = URL + (f"/v1/customer/robots/{ROBOT}/{suffix}" if suffix else "/v1/customer/robots")
    kwargs = (
        {"status": failure}
        if isinstance(failure, int)
        else {
            "exc": aiohttp.ClientConnectionError()
            if failure == "network"
            else asyncio.TimeoutError()
        }
    )
    getattr(aioclient_mock, method)(url, **kwargs)
    expected = InvalidAuth if failure == 401 else CannotConnect
    with pytest.raises(expected):
        if operation == "events":
            await anext(client.events())
        elif operation == "map_image":
            await client.map_image(MAP, "live")
        elif operation == "command":
            await client.command("pause")
        elif operation == "set_setting":
            await client.set_setting("child_lock", True)
        elif operation == "robots":
            await LocalAPI.robots(async_get_clientsession(hass), URL, TOKEN)
        else:
            await client.telemetry()


async def test_telemetry_and_delivery(client, aioclient_mock, document):
    aioclient_mock.get(f"{URL}/v1/customer/robots/{ROBOT}/telemetry", json=document)
    assert (await client.telemetry()).robot_id == ROBOT
    for suffix, action in (
        ("locate", lambda: client.command("find")),
        ("commands/start", lambda: client.command("start", operating_mode=2)),
        ("commands/clean_segments", lambda: client.command("clean_segments", ["one:1:1"], 6)),
        ("settings/child_lock", lambda: client.set_setting("child_lock", True)),
    ):
        aioclient_mock.post(
            f"{URL}/v1/customer/robots/{ROBOT}/{suffix}",
            json={"delivery": "acknowledged", "execution": "unconfirmed"},
        )
        await action()


@pytest.mark.parametrize("payload", [{"delivery": "acknowledged"}, [], "not delivery"])
async def test_invalid_delivery(client, aioclient_mock, payload):
    aioclient_mock.post(f"{URL}/v1/customer/robots/{ROBOT}/commands/start", json=payload)
    with pytest.raises(CannotConnect):
        await client.command("start")


async def test_invalid_telemetry(client, aioclient_mock):
    aioclient_mock.get(f"{URL}/v1/customer/robots/{ROBOT}/telemetry", json={})
    with pytest.raises(CannotConnect):
        await client.telemetry()


@pytest.mark.parametrize(
    ("command", "segments", "mode"),
    [
        ("unknown", None, None),
        ("clean_segments", [], None),
        ("clean_segments", ["one"] * 101, None),
        ("clean_segments", ["one", "one"], None),
        ("pause", ["one"], None),
        ("pause", None, 2),
        ("start", None, True),
        ("start", None, 3),
    ],
)
async def test_invalid_commands(client, command, segments, mode):
    with pytest.raises(ValueError):
        await client.command(command, segments, mode)


@pytest.mark.parametrize(("key", "value"), [("Bad", True), ("good", "bad"), (None, 2)])
async def test_invalid_settings(client, key, value):
    with pytest.raises(ValueError):
        await client.set_setting(key, value)


@pytest.mark.parametrize(
    ("descriptor", "kind"),
    [
        ({}, "live"),
        (MAP, "bad"),
        (MAP | {"id": "../bad"}, "live"),
        (MAP | {"version": 1}, "live"),
        (MAP | {"revision": "bad"}, "live"),
    ],
)
async def test_invalid_map_request(client, descriptor, kind):
    with pytest.raises(ValueError):
        await client.map_image(descriptor, kind)


@pytest.mark.parametrize(
    ("content", "content_type", "valid"),
    [
        (b"\x89PNG\r\n\x1a\npayload", "image/png", True),
        (b"not png", "image/png", False),
        (b"png", "text/html", False),
        (None, "image/png", False),
    ],
)
async def test_images(client, aioclient_mock, content, content_type, valid):
    if content is None:
        content = b"\x89PNG\r\n\x1a\n" + b"x" * (4 * 1024 * 1024)
    aioclient_mock.get(
        f"{URL}/v1/customer/robots/{ROBOT}/maps/one/1/{'a' * 64}/live.png",
        content=content,
        headers={"Content-Type": content_type},
    )
    if valid:
        assert await client.map_image(MAP, "live") == content
    else:
        with pytest.raises(CannotConnect):
            await client.map_image(MAP, "live")


async def test_stream(client, aioclient_mock, document):
    body = (
        ": heartbeat\n\n"
        + "event: ignored\ndata: {}\n\n"
        + ("event: telemetry\ndata: " + json.dumps(document) + "\n\n")
    )
    aioclient_mock.get(
        f"{URL}/v1/customer/robots/{ROBOT}/events",
        text=body,
        headers={"Content-Type": "text/event-stream"},
    )
    stream = client.events()
    assert (await anext(stream)).robot_id == ROBOT
    with pytest.raises(CannotConnect, match="closed"):
        await anext(stream)


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        ("event: telemetry\ndata: {}\ndata: {}\n\n", "text/event-stream"),
        (None, "text/event-stream"),
        ("oversized_event", "text/event-stream"),
        ("event: telemetry\ndata: {}\n\n", "text/event-stream"),
        ("event: telemetry\ndata: not json\n\n", "text/event-stream"),
        ("", "text/plain"),
    ],
)
async def test_invalid_stream(client, aioclient_mock, body, content_type):
    if body is None:
        body = "data: " + "x" * (256 * 1024) + "\n"
    elif body == "oversized_event":
        body = (": " + "x" * 100000 + "\n") * 3
    aioclient_mock.get(
        f"{URL}/v1/customer/robots/{ROBOT}/events",
        text=body,
        headers={"Content-Type": content_type},
    )
    with pytest.raises(CannotConnect):
        await anext(client.events())
