"""Botões de keypad como EventEntity (gatilho de automação).

O keypad já publica cada gesto em `/ac/bt` no multicast:
`$73B4>/ac/bt@0?code=0&s=CL&b=0&t=0<57000#`. A integração só escuta; não
registra nada no equipamento e não grava em flash.
"""

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NdConfigEntry
from .const import GESTURES, SIGNAL_BUTTON
from .entity import NdEntity, setup_platform_listener
from .hub import NdDevice, NdHub


async def async_setup_entry(
    hass: HomeAssistant, entry: NdConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def factory(hub: NdHub, device: NdDevice) -> list:
        assert device.caps is not None
        if not device.caps.button_events:
            return []
        return [NdButtonEvent(hub, device, index) for index in device.caps.buttons]

    entry.async_on_unload(
        setup_platform_listener(hass, entry.runtime_data, async_add_entities, factory)
    )


class NdButtonEvent(NdEntity, EventEntity):
    """Um botão físico do keypad."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = list(GESTURES.values())
    _attr_translation_key = "button"

    def __init__(self, hub: NdHub, device: NdDevice, index: int) -> None:
        super().__init__(hub, device, f"ac_bt_b{index}")
        self._index = index
        self._attr_translation_placeholders = {"number": str(index + 1)}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_BUTTON.format(
                    entry_id=self._hub.entry.entry_id, device_id=self._device.device_id
                ),
                self._on_button,
            )
        )

    @callback
    def _on_button(self, button: int, gesture: str, duration: int) -> None:
        if button != self._index:
            return
        self._trigger_event(gesture, {"button": button, "duration": duration})
        self.async_write_ha_state()
