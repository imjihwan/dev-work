"""Poll confirmed light states and maintain account authentication."""

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CommaxApi, CommaxAuthError, CommaxError, LightChannel
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class CommaxCoordinator(DataUpdateCoordinator[dict[str, LightChannel]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: CommaxApi) -> None:
        self.client = client
        self.entry = entry
        self._operation_lock = asyncio.Lock()
        self._maintenance_task: asyncio.Task | None = None
        self._closing = False
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )

    async def _async_update_data(self) -> dict[str, LightChannel]:
        async with self._operation_lock:
            try:
                return await self.client.async_lights()
            except CommaxAuthError:
                raise ConfigEntryAuthFailed(
                    "COMMAX login rejected; enter account credentials again"
                ) from None
            except CommaxError as error:
                raise UpdateFailed(str(error)) from None

    async def async_set(self, unique_id: str, on: bool) -> None:
        async with self._operation_lock:
            channel = (self.data or {}).get(unique_id)
            if channel is None:
                raise HomeAssistantError("COMMAX light is unavailable")
            try:
                await self.client.async_set_light(channel, on)
                # An acknowledgement is not a new light state; read the actual result.
                await asyncio.sleep(1)
                data = await self.client.async_lights()
            except CommaxAuthError:
                self.entry.async_start_reauth(self.hass)
                raise HomeAssistantError("COMMAX account requires reauthentication") from None
            except CommaxError as error:
                raise HomeAssistantError(str(error)) from None
            self.async_set_updated_data(data)

    def start_token_maintenance(self) -> None:
        """Continue renewing even if all light entities are disabled."""

        async def maintain(_now) -> None:
            if self._closing or self._maintenance_task is not None:
                return
            self._maintenance_task = asyncio.current_task()
            try:
                await self.client.async_ensure_token()
            except CommaxAuthError:
                self.entry.async_start_reauth(self.hass)
            except CommaxError:
                # Polling surfaces connectivity failures; maintenance retries next minute.
                _LOGGER.debug("COMMAX token maintenance deferred until the next check")
            finally:
                self._maintenance_task = None

        unsubscribe = async_track_time_interval(self.hass, maintain, timedelta(minutes=1))

        def stop() -> None:
            self._closing = True
            unsubscribe()
            if self._maintenance_task:
                self._maintenance_task.cancel()

        self.entry.async_on_unload(stop)
