from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    CONF_URL,
    CONF_USERNAME,
    CONF_PASSWORD,
    SERVICE_SEND_MESSAGE,
    SERVICE_UPDATE_ENDPOINTS,
    ATTR_ENDPOINT,
    ATTR_TITLE,
    ATTR_CONTENT,
    ATTR_TYPE,
    ATTR_URL,
)
from .hub import MagicPushHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = []

type MagicPushConfigEntry = ConfigEntry[MagicPushHub]

UPDATE_ENDPOINTS_SCHEMA = vol.Schema({})


def _build_send_message_schema(endpoint_ids: list[str]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(ATTR_ENDPOINT): vol.In(endpoint_ids) if endpoint_ids else str,
            vol.Optional(ATTR_TITLE, default=""): str,
            vol.Required(ATTR_CONTENT): str,
            vol.Optional(ATTR_TYPE, default="text"): vol.In(["text", "markdown", "html"]),
            vol.Optional(ATTR_URL, default=""): str,
        }
    )


def _get_all_endpoint_ids(hass: HomeAssistant) -> list[str]:
    ids: list[str] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        hub: MagicPushHub | None = entry.runtime_data
        if hub is not None:
            ids.extend(hub.endpoints.keys())
    return ids


def _find_endpoint(
    hass: HomeAssistant, endpoint_id: str
) -> tuple[MagicPushHub, dict[str, Any]] | None:
    endpoint_id = str(endpoint_id)
    for entry in hass.config_entries.async_entries(DOMAIN):
        hub: MagicPushHub | None = entry.runtime_data
        if hub is None:
            continue

        if endpoint_id in hub.endpoints:
            return hub, hub.endpoints[endpoint_id]

        for ep in hub.endpoints.values():
            if ep.get("token") == endpoint_id:
                return hub, ep

    return None


async def _register_services(hass: HomeAssistant) -> None:
    endpoint_ids = _get_all_endpoint_ids(hass)

    async def handle_send_message(call: ServiceCall) -> None:
        endpoint_id = call.data[ATTR_ENDPOINT]
        title = call.data.get(ATTR_TITLE, "")
        content = call.data[ATTR_CONTENT]
        msg_type = call.data.get(ATTR_TYPE, "text")
        url = call.data.get(ATTR_URL, "")

        result = _find_endpoint(hass, endpoint_id)
        if result is None:
            _LOGGER.error(
                "Endpoint '%s' not found in any MagicPush entry. Available: %s",
                endpoint_id,
                _get_all_endpoint_ids(hass),
            )
            return

        hub, ep = result
        await hub.send_push(ep["token"], title, content, msg_type, url)

    async def handle_update_endpoints(call: ServiceCall) -> None:
        for entry_item in hass.config_entries.async_entries(DOMAIN):
            h: MagicPushHub = entry_item.runtime_data
            try:
                await h.fetch_endpoints()
            except Exception as e:
                _LOGGER.error("Failed to update endpoints for %s: %s", h.url, e)
        await _register_services(hass)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        handle_send_message,
        schema=_build_send_message_schema(endpoint_ids),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPDATE_ENDPOINTS,
        handle_update_endpoints,
        schema=UPDATE_ENDPOINTS_SCHEMA,
    )


async def async_setup_entry(hass: HomeAssistant, entry: MagicPushConfigEntry) -> bool:
    hub = MagicPushHub(
        hass,
        entry.data[CONF_URL],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )

    try:
        await hub.login()
        await hub.fetch_endpoints()
    except Exception as e:
        _LOGGER.warning("MagicPush initial setup warning for %s: %s", entry.data[CONF_URL], e)

    entry.runtime_data = hub

    await _register_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: MagicPushConfigEntry) -> bool:
    hub = entry.runtime_data
    await hub.cleanup()
    entry.runtime_data = None

    remaining = hass.config_entries.async_entries(DOMAIN)
    active = [e for e in remaining if e.runtime_data is not None]
    if not active:
        hass.services.async_remove(DOMAIN, SERVICE_SEND_MESSAGE)
        hass.services.async_remove(DOMAIN, SERVICE_UPDATE_ENDPOINTS)
    else:
        await _register_services(hass)

    return True



