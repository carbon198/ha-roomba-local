import asyncio
from asyncio import sleep
from contextlib import suppress
from dataclasses import replace
import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir

from .api import CannotConnect, InvalidAuth, LocalAPI
from .const import DOMAIN, CONF_CLEANING_MODE, DEFAULT_CLEANING_MODE
from .models import Telemetry
from .map_labels import update_map_numbers

_LOGGER = logging.getLogger(__name__)


class LocalCoordinator(DataUpdateCoordinator[Telemetry]):
    config_entry: ConfigEntry["LocalCoordinator"]

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry[LocalCoordinator], api: LocalAPI
    ) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry, update_interval=None)
        self.api = api
        self._stream_task: asyncio.Task[None] | None = None
        self._position_task: asyncio.Task[None] | None = None
        self._position_failed = False
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._pending_offline: Telemetry | None = None
        self._offline_confirmed = False

    @callback
    def _async_cancel_disconnect(self) -> None:
        if self._disconnect_timer is not None:
            self._disconnect_timer.cancel()
            self._disconnect_timer = None
        self._pending_offline = None

    @callback
    def _async_confirm_disconnect(self) -> None:
        data = self._pending_offline
        self._disconnect_timer = None
        self._pending_offline = None
        self._offline_confirmed = True
        if data is not None:
            self.async_set_updated_data(data)

    @callback
    def _async_debounce_disconnect(self, data: Telemetry) -> Telemetry:
        """Hold established MQTT connectivity for ten seconds, not API failures.

        Keep the last reported sensor values available during a brief reconnect.
        The emulator still authoritatively rejects commands without a live session.
        Repeated offline reports update the pending snapshot, not the deadline.
        """
        if data.online:
            self._async_cancel_disconnect()
            self._offline_confirmed = False
        elif (
            not self._offline_confirmed
            and self.last_update_success
            and self.data is not None
            and self.data.online
        ):
            self._pending_offline = data
            if self._disconnect_timer is None:
                self._disconnect_timer = self.hass.loop.call_later(
                    10, self._async_confirm_disconnect
                )
            return replace(
                data,
                online=True,
                values=self.data.values | data.values | {"robot_mqtt_connection": True},
                available=self.data.available
                | {
                    key: value or self.data.available.get(key, False)
                    for key, value in data.available.items()
                },
            )
        return data

    @property
    def stream_running(self) -> bool:
        return self._stream_task is not None and not self._stream_task.done()

    @callback
    def _async_metadata(self, data: Telemetry) -> None:
        update_map_numbers(self.hass, self.config_entry, data)
        assert self.config_entry.unique_id is not None
        registry = dr.async_get(self.hass)
        device = registry.async_get_device_by_identifier(
            (DOMAIN, self.config_entry.unique_id), self.config_entry.entry_id
        )
        if device is not None and data.device:
            registry.async_update_device(device.id, **data.device)
        issue_id = f"cleaning_mode_{self.config_entry.entry_id}"
        mode = self.config_entry.options.get(CONF_CLEANING_MODE, DEFAULT_CLEANING_MODE)
        if data.cleaning_modes and (type(mode) is not int or mode not in data.cleaning_modes):
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="cleaning_mode",
                translation_placeholders={"robot": self.config_entry.title},
                data={"entry_id": self.config_entry.entry_id},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    def async_start(self) -> None:
        if self._stream_task is None:
            self._stream_task = self.config_entry.async_create_background_task(
                self.hass, self._async_listen(), "Roomba local telemetry stream"
            )
            self._position_task = self.config_entry.async_create_background_task(
                self.hass, self._async_positions(), "Roomba live map telemetry renewal"
            )

    async def async_shutdown(self) -> None:
        self._async_cancel_disconnect()
        if self._position_task is not None:
            self._position_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._position_task
            self._position_task = None
        if self._stream_task is not None:
            self._stream_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._stream_task
            self._stream_task = None
        await super().async_shutdown()

    async def _async_positions(self) -> None:
        next_request = 0.0
        while True:
            data = self.data
            active = (
                data is not None
                and self.last_update_success
                and data.online
                and data.maps
                and data.values.get("mission_phase")
                in (
                    "run",
                    "resume",
                    "hmUsrDock",
                    "hmUsrChrg",
                    "hmMidMsn",
                    "hmPostMsn",
                    "pause",
                    "stop",
                    "stuck",
                    "error",
                    "room",
                    "zone",
                    "polygon",
                    "oClean",
                    "travel",
                    "traversal",
                    "reloc",
                    "explore",
                    "plan",
                )
            )
            now = time.time()
            expiry = data.position["expires_at"] if data is not None and data.position else 0
            if active and now >= next_request and expiry - now <= 15:
                next_request = now + 40
                try:
                    await self.api.command("live_map")
                    self._position_failed = False
                except InvalidAuth:
                    self.config_entry.async_start_reauth(self.hass)
                    return
                except CannotConnect as exc:
                    if not self._position_failed:
                        _LOGGER.warning("Live position telemetry request failed: %s", exc)
                    self._position_failed = True
            await sleep(5)

    async def _async_listen(self) -> None:
        delay = 1
        while True:
            try:
                async for data in self.api.events():
                    self._async_metadata(data)
                    self.async_set_updated_data(self._async_debounce_disconnect(data))
                    delay = 1
            except InvalidAuth:
                self._async_cancel_disconnect()
                self.async_set_update_error(
                    ConfigEntryAuthFailed(translation_domain=DOMAIN, translation_key="invalid_auth")
                )
                self.config_entry.async_start_reauth(self.hass)
                return
            except CannotConnect:
                self._async_cancel_disconnect()
                self.async_set_update_error(
                    UpdateFailed(translation_domain=DOMAIN, translation_key="cannot_connect")
                )
            await sleep(delay)
            delay = min(delay * 2, 30)

    async def _async_update_data(self) -> Telemetry:
        try:
            data = await self.api.telemetry()
            self._async_metadata(data)
            return self._async_debounce_disconnect(data)
        except InvalidAuth as exc:
            self._async_cancel_disconnect()
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from exc
        except CannotConnect as exc:
            self._async_cancel_disconnect()
            raise UpdateFailed(translation_domain=DOMAIN, translation_key="cannot_connect") from exc
