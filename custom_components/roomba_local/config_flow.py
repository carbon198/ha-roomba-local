import hashlib
from typing import Any

import probatio as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult as FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .api import CannotConnect, InvalidAuth, LocalAPI
from .const import CONF_API_URL, CONF_BEARER_TOKEN, CONF_ROBOT_ID, DOMAIN
from .models import normalize_url, validate_credentials, validate_token


def token_selector() -> selector.TextSelector:
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )


def robot_identity(url: str, robot_id: str) -> str:
    return hashlib.sha256((url + "\0" + robot_id).encode()).hexdigest()


class LocalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._server_data: dict[str, str] | None = None
        self._robots: dict[str, str] = {}

    async def _validate(self, data: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        try:
            data = dict(data)
            data[CONF_API_URL] = normalize_url(data[CONF_API_URL])
            validate_credentials(data[CONF_BEARER_TOKEN], data[CONF_ROBOT_ID])
            api = LocalAPI(
                async_get_clientsession(self.hass),
                data[CONF_API_URL],
                data[CONF_BEARER_TOKEN],
                data[CONF_ROBOT_ID],
            )
            await api.telemetry()
            return data, None
        except ValueError:
            return None, "invalid_input"
        except InvalidAuth:
            return None, "invalid_auth"
        except CannotConnect:
            return None, "cannot_connect"

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors = {}
        if user_input is not None:
            try:
                url = normalize_url(user_input[CONF_API_URL])
                token = user_input[CONF_BEARER_TOKEN]
                validate_token(token)
                robots = await LocalAPI.robots(async_get_clientsession(self.hass), url, token)
                if robots:
                    self._server_data = {CONF_API_URL: url, CONF_BEARER_TOKEN: token}
                    self._robots = {
                        robot["robot_id"]: " - ".join(
                            [
                                "Roomba " + robot["robot_id"][-6:],
                                *[robot[key] for key in ("sku", "ip") if key in robot],
                            ]
                        )
                        for robot in robots
                    }
                    return await self.async_step_robot()
                errors["base"] = "no_robots"
            except ValueError:
                errors["base"] = "invalid_input"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_URL): str,
                    vol.Required(CONF_BEARER_TOKEN): token_selector(),
                }
            ),
        )

    async def async_step_robot(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if self._server_data is None:
            return await self.async_step_user()
        configured = {
            robot_identity(entry.data[CONF_API_URL], entry.data[CONF_ROBOT_ID])
            for entry in self._async_current_entries()
        }
        self._robots = {
            robot_id: label
            for robot_id, label in self._robots.items()
            if robot_identity(self._server_data[CONF_API_URL], robot_id) not in configured
        }
        if not self._robots:
            return self.async_abort(reason="all_robots_configured")
        errors = {}
        if user_input is not None:
            robot_id = user_input.get(CONF_ROBOT_ID)
            if not isinstance(robot_id, str) or robot_id not in self._robots:
                errors["base"] = "invalid_input"
            else:
                await self.async_set_unique_id(
                    robot_identity(self._server_data[CONF_API_URL], robot_id)
                )
                self._abort_if_unique_id_configured()
                data, error = await self._validate({**self._server_data, CONF_ROBOT_ID: robot_id})
                if error is None:
                    assert data is not None
                    return self.async_create_entry(title="Roomba " + robot_id[-6:], data=data)
                assert error is not None
                errors["base"] = error
        return self.async_show_form(
            step_id="robot",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ROBOT_ID): vol.In(self._robots),
                }
            ),
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._replace_token("reauth_confirm", self._get_reauth_entry(), user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self._replace_token("reconfigure", self._get_reconfigure_entry(), user_input)

    async def _replace_token(
        self, step_id: str, entry: config_entries.ConfigEntry, user_input: dict[str, Any] | None
    ) -> FlowResult:
        errors = {}
        if user_input is not None:
            data, error = await self._validate({**entry.data, **user_input})
            if error is None:
                assert data is not None
                for configured in self._async_current_entries():
                    if (
                        configured.entry_id != entry.entry_id
                        and configured.data[CONF_API_URL] == data[CONF_API_URL]
                        and configured.data[CONF_ROBOT_ID] == data[CONF_ROBOT_ID]
                    ):
                        return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(entry, data_updates=data)
            assert error is not None
            errors["base"] = error
        return self.async_show_form(
            step_id=step_id,
            errors=errors,
            description_placeholders={"server": entry.data[CONF_API_URL]},
            data_schema=vol.Schema(
                {
                    **(
                        {vol.Required(CONF_API_URL, default=entry.data[CONF_API_URL]): str}
                        if step_id == "reconfigure"
                        else {}
                    ),
                    vol.Required(CONF_BEARER_TOKEN): token_selector(),
                }
            ),
        )
