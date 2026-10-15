"""Base das entidades: dispositivo, disponibilidade e atualização por sinal."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, SIGNAL_DEVICE_READY, SIGNAL_DEVICE_UPDATE
from .hub import NdDevice, NdHub


class NdEntity(Entity):
    """Entidade ligada a um equipamento ND."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: NdHub, device: NdDevice, key: str) -> None:
        self._hub = hub
        self._device = device
        # Estável: o ID do equipamento e a carga, nunca o IP.
        self._attr_unique_id = f"{device.device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.device_id)},
            manufacturer=MANUFACTURER,
            model=device.model,
            name=device.name,
            sw_version=device.version,
            serial_number=device.device_id,
        )

    @property
    def available(self) -> bool:
        return self._device.available

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_DEVICE_UPDATE.format(
                    entry_id=self._hub.entry.entry_id, device_id=self._device.device_id
                ),
                self.async_write_ha_state,
            )
        )


def setup_platform_listener(
    hass: HomeAssistant,
    hub: NdHub,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[NdHub, NdDevice], list[Entity]],
) -> Callable[[], None]:
    """Cria as entidades de cada equipamento assim que a describe estiver pronta."""

    @callback
    def _ready(device: NdDevice) -> None:
        entities = factory(hub, device)
        if entities:
            async_add_entities(entities)

    return async_dispatcher_connect(
        hass, SIGNAL_DEVICE_READY.format(entry_id=hub.entry.entry_id), _ready
    )
