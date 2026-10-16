"""Translated user-facing errors; never include response bodies or credentials."""

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN


def error(key: str) -> HomeAssistantError:
    return HomeAssistantError(translation_domain=DOMAIN, translation_key=key)
