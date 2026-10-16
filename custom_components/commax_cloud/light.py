"""On/off light entities backed by COMMAX's official app command path."""

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import LightChannel
from .const import DOMAIN
from .coordinator import CommaxCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: CommaxCoordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def discover() -> None:
        entities = []
        for unique_id, channel in (coordinator.data or {}).items():
            if unique_id not in known:
                known.add(unique_id)
                entities.append(CommaxLight(coordinator, channel))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class CommaxLight(CoordinatorEntity[CommaxCoordinator], LightEntity):
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF
    _attr_has_entity_name = True

    def __init__(self, coordinator: CommaxCoordinator, channel: LightChannel) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = channel.unique_id
        self._attr_name = channel.name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, channel.gateway_no)},
            name=f"COMMAX {channel.model}",
            manufacturer="COMMAX",
            model=channel.model,
        )

    @property
    def available(self) -> bool:
        channel = (self.coordinator.data or {}).get(self._attr_unique_id)
        return super().available and channel is not None and channel.state is not None

    @property
    def is_on(self) -> bool | None:
        channel = (self.coordinator.data or {}).get(self._attr_unique_id)
        return channel.state if channel else None

    @callback
    def _handle_coordinator_update(self) -> None:
        channel = (self.coordinator.data or {}).get(self._attr_unique_id)
        if channel:
            self._attr_name = channel.name
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set(self._attr_unique_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set(self._attr_unique_id, False)
