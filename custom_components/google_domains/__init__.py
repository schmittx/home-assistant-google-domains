"""Support for Google Domains."""
import asyncio
from datetime import timedelta
import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DOMAIN,
    CONF_IP_ADDRESS,
    CONF_PASSWORD,
    CONF_TIMEOUT,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .const import (
    CONF_INTERVAL,
    DEFAULT_INTERVAL,
    DEFAULT_TIMEOUT,
    DOMAIN,
    EVENT_GOOGLE_DOMAINS_ENTRY_UPDATED,
    UNDO_UPDATE_INTERVAL,
    UNDO_UPDATE_LISTENER,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up a config entry."""
    hass.data.setdefault(DOMAIN, {})

    domain = config_entry.data[CONF_DOMAIN]
    username = config_entry.data[CONF_USERNAME]
    password = config_entry.data[CONF_PASSWORD]
    interval = config_entry.options.get(CONF_INTERVAL, DEFAULT_INTERVAL)
    timeout = config_entry.options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)

    session = async_get_clientsession(hass)

    async def update_domain_interval(now):
        """Update the Google Domains entry."""
        await _update_google_domains(hass, session, domain, username, password, timeout)

    result = await _update_google_domains(
        hass, session, domain, username, password, timeout
    )

    if not result:
        _LOGGER.warning(f"Timeout from Google Domains API for domain: {domain} during setup, retrying")
        result = async_call_later(hass, 1, update_domain_interval)
        if not result:
            _LOGGER.warning(f"Retry was not successful from Google Domains API for domain: {domain}")
            return False
        _LOGGER.warning(f"Retry successful from Google Domains API for domain: {domain}")

    undo_update_interval = async_track_time_interval(hass, update_domain_interval, timedelta(minutes=interval))
    undo_update_listener = config_entry.add_update_listener(update_listener)

    hass.data[DOMAIN][config_entry.entry_id] = {
        UNDO_UPDATE_INTERVAL: undo_update_interval,
        UNDO_UPDATE_LISTENER: undo_update_listener,
    }

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN][config_entry.entry_id][UNDO_UPDATE_INTERVAL]()
    hass.data[DOMAIN][config_entry.entry_id][UNDO_UPDATE_LISTENER]()
    hass.data[DOMAIN].pop(config_entry.entry_id)

    return True


async def update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(config_entry.entry_id)


async def _update_google_domains(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    domain: str,
    username: str,
    password: str,
    timeout: int,
) -> bool:
    """Update Google Domains."""
    url = f"https://{username}:{password}@domains.google.com/nic/update"
    params = {"hostname": domain}

    try:
        async with asyncio.timeout(timeout):
            response = await session.get(url, params=params)
            body = await response.text()

            if body.startswith("good") or body.startswith("nochg"):
                hass.bus.fire(
                    EVENT_GOOGLE_DOMAINS_ENTRY_UPDATED,
                    {
                        CONF_DOMAIN: domain,
                        CONF_IP_ADDRESS: body.split(" ")[1],
                    },
                )
                return True

            _LOGGER.warning(f"Updating Google Domains failed: {domain} => {body}")

    except aiohttp.ClientError:
        _LOGGER.warning("Can't connect to Google Domains API")

    except TimeoutError:
        _LOGGER.warning(f"Timeout from Google Domains API for domain: {domain}")

    return False
