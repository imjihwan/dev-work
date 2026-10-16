"""COMMAX Cloud lights integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CommaxApi
from .const import CONF_DEVICE_UUID, CONF_TOKENS, DOMAIN
from .coordinator import CommaxCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.LIGHT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Restore tokens and credentials before the first device query."""
    generation = entry.data.get("auth_generation", 0)

    def persist(tokens: dict) -> None:
        if entry.data.get("auth_generation", 0) != generation:
            return
        hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_TOKENS: tokens})

    client = CommaxApi(
        async_get_clientsession(hass),
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data[CONF_DEVICE_UUID],
        tokens=entry.data.get(CONF_TOKENS),
        on_tokens=persist,
    )
    coordinator = CommaxCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.start_token_maintenance()

    # Token rotation updates data frequently; reload only when options actually change.
    previous_options = dict(entry.options)
    previous_generation = generation

    async def options_changed(hass: HomeAssistant, updated: ConfigEntry) -> None:
        nonlocal previous_options, previous_generation
        if (
            dict(updated.options) != previous_options
            or updated.data.get("auth_generation", 0) != previous_generation
        ):
            previous_options = dict(updated.options)
            previous_generation = updated.data.get("auth_generation", 0)
            await hass.config_entries.async_reload(updated.entry_id)

    entry.async_on_unload(entry.add_update_listener(options_changed))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
