"""Authenticated HTTPS requests to the local emulator."""

import asyncio
from collections.abc import AsyncIterator
import json
import re

import aiohttp
from aiohttp.http_exceptions import HttpProcessingError

from .models import Telemetry, normalize_url, validate_credentials, validate_token


class InvalidAuth(Exception):
    """The server rejected the bearer credential."""


class CannotConnect(Exception):
    """The local service is unreachable or its response is incompatible."""


class LocalAPI:
    @staticmethod
    async def robots(
        session: aiohttp.ClientSession,
        url: str,
        token: str,
        allow_invalid_certificate: bool = False,
    ) -> list[dict[str, str]]:
        url = normalize_url(url)
        validate_token(token)
        try:
            async with session.get(
                f"{url}/v1/customer/robots",
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=False,
                ssl=not allow_invalid_certificate,
            ) as response:
                if response.status == 401:
                    raise InvalidAuth("Local bearer token rejected")
                if response.status != 200:
                    raise CannotConnect(f"Local inventory API returned HTTP {response.status}")
                document = await response.json()
            if not isinstance(document, dict) or not isinstance(document.get("robots"), list):
                raise ValueError("Invalid robot inventory")
            robots = []
            ids = set()
            for item in document["robots"]:
                if not isinstance(item, dict) or not isinstance(item.get("robot_id"), str):
                    raise ValueError("Invalid robot inventory")
                robot_id = item["robot_id"]
                validate_credentials(token, robot_id)
                if robot_id in ids:
                    raise ValueError("Duplicate robot in inventory")
                ids.add(robot_id)
                robot = {"robot_id": robot_id}
                for key in ("sku", "ip"):
                    value = item.get(key)
                    if value is not None:
                        if not isinstance(value, str) or not 1 <= len(value) <= 256:
                            raise ValueError("Invalid robot inventory metadata")
                        robot[key] = value
                robots.append(robot)
            return robots
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise CannotConnect(
                "Cannot read robot inventory; check HTTPS and emulator version"
            ) from exc

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        token: str,
        robot_id: str,
        allow_invalid_certificate: bool = False,
    ):
        self.url = normalize_url(url)
        validate_credentials(token, robot_id)
        self.robot_id = robot_id
        self._session = session
        self._token = token
        self._allow_invalid_certificate = allow_invalid_certificate

    @property
    def allow_invalid_certificate(self) -> bool:
        return self._allow_invalid_certificate

    async def set_setting(self, key: str, value: bool | int) -> None:
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[a-z][a-z_]{0,63}", key)
            or type(value) not in (bool, int)
        ):
            raise ValueError("Invalid setting key or value")
        await self._deliver(f"settings/{key}", {"value": value})

    async def command(
        self, command: str, segment_ids: list[str] | None = None, operating_mode: int | None = None
    ) -> None:
        if command not in {
            "find",
            "start",
            "pause",
            "stop",
            "dock",
            "clean_segments",
            "live_map",
            "evac",
            "drypad",
            "stoppaddry",
            "washpad",
        }:
            raise ValueError("Unsupported robot command")
        if command == "clean_segments":
            if (
                not segment_ids
                or len(segment_ids) > 100
                or len(set(segment_ids)) != len(segment_ids)
            ):
                raise ValueError("Select one or more distinct segments")
        elif segment_ids is not None:
            raise ValueError("Segments require room cleaning")
        suffix = "locate" if command == "find" else f"commands/{command}"
        body: dict[str, object] = {"segment_ids": segment_ids} if segment_ids is not None else {}
        if operating_mode is not None:
            if (
                command not in ("start", "clean_segments")
                or type(operating_mode) is not int
                or operating_mode not in (2, 4, 6)
            ):
                raise ValueError("Unsupported cleaning mode")
            body["operating_mode"] = operating_mode
        await self._deliver(suffix, body or None)

    async def _deliver(self, suffix: str, body: dict[str, object] | None) -> None:
        try:
            async with self._session.post(
                f"{self.url}/v1/customer/robots/{self.robot_id}/{suffix}",
                headers={"Authorization": f"Bearer {self._token}"},
                json=body,
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=False,
                ssl=not self._allow_invalid_certificate,
            ) as response:
                if response.status == 401:
                    raise InvalidAuth("Bearer token rejected")
                if response.status != 200:
                    raise CannotConnect(
                        "Command/setting delivery failed; check MQTT connection/subscription and supported values. "
                        "For room cleaning, refresh area mappings and select rooms from one current map. "
                        "Do not retry blindly."
                    )
                if await response.json() != {
                    "delivery": "acknowledged",
                    "execution": "unconfirmed",
                }:
                    raise CannotConnect("Invalid command delivery response")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise CannotConnect("Command delivery uncertain; check robot before retrying") from exc

    async def telemetry(self) -> Telemetry:
        try:
            async with self._session.get(
                f"{self.url}/v1/customer/robots/{self.robot_id}/telemetry",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=aiohttp.ClientTimeout(total=10),
                allow_redirects=False,
                ssl=not self._allow_invalid_certificate,
            ) as response:
                if response.status == 401:
                    raise InvalidAuth("Bearer token rejected")
                if response.status != 200:
                    raise CannotConnect(f"Local telemetry API returned HTTP {response.status}")
                data = await response.json()
            return Telemetry.parse(data, self.robot_id)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise CannotConnect(
                "Cannot read local telemetry; check HTTPS, API and robot ID"
            ) from exc

    async def map_image(self, descriptor: dict[str, str], kind: str) -> bytes:
        if (
            kind not in ("room", "live")
            or any(
                not isinstance(descriptor.get(k), str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", descriptor[k])
                for k in ("id", "version")
            )
            or not isinstance(descriptor.get("revision"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", descriptor["revision"])
        ):
            raise ValueError("Invalid map image request")
        suffix = "/".join(descriptor[k] for k in ("id", "version", "revision"))
        try:
            async with self._session.get(
                f"{self.url}/v1/customer/robots/{self.robot_id}/maps/{suffix}/{kind}.png",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=False,
                ssl=not self._allow_invalid_certificate,
            ) as response:
                if response.status == 401:
                    raise InvalidAuth("Local bearer token rejected")
                if response.status != 200 or response.content_type != "image/png":
                    raise CannotConnect(f"Local map image API returned HTTP {response.status}")
                image = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    image.extend(chunk)
                    if len(image) > 4 * 1024 * 1024:
                        raise CannotConnect("Map image exceeds size limit")
                if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise CannotConnect("Invalid map PNG response")
                return bytes(image)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise CannotConnect("Cannot read local map image") from exc

    async def events(self) -> AsyncIterator[Telemetry]:
        try:
            async with self._session.get(
                f"{self.url}/v1/customer/robots/{self.robot_id}/events",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=45),
                allow_redirects=False,
                read_bufsize=256 * 1024,
                ssl=not self._allow_invalid_certificate,
            ) as response:
                if response.status == 401:
                    raise InvalidAuth("Local bearer token rejected")
                if response.status != 200:
                    raise CannotConnect(f"Local event API returned HTTP {response.status}")
                if response.content_type != "text/event-stream":
                    raise CannotConnect("Invalid telemetry stream content type")
                event = ""
                data = None
                size = 0
                content = response.content
                while True:
                    raw = await content.readline()
                    if not raw:
                        raise CannotConnect("Local telemetry stream closed")
                    size += len(raw)
                    if size > 256 * 1024:
                        raise CannotConnect("Telemetry event exceeds size limit")
                    line = raw.decode("utf-8").rstrip("\r\n")
                    if not line:
                        if event == "telemetry" and data is not None:
                            yield Telemetry.parse(json.loads(data), self.robot_id)
                        event, data, size = "", None, 0
                    elif line.startswith("event:"):
                        event = line[6:].lstrip(" ")
                    elif line.startswith("data:"):
                        if data is not None:
                            raise CannotConnect("Invalid multiline telemetry event")
                        data = line[5:].lstrip(" ")
        except (aiohttp.ClientError, HttpProcessingError, asyncio.TimeoutError, ValueError) as exc:
            raise CannotConnect("Cannot read local telemetry stream; check HTTPS and API") from exc
