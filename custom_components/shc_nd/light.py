"""Relés (`/ac/rs`) como luzes liga/desliga."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NdConfigEntry
from .describe import PATH_RELAYS
from .entity import NdEntity, setup_platform_listener
from .hub import NdDevice, NdHub
from .protocol import is_on


async def async_setup_entry(
    hass: HomeAssistant, entry: NdConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def factory(hub: NdHub, device: NdDevice) -> list:
        assert device.caps is not None
        return [NdRelayLight(hub, device, index) for index in device.caps.relays]

    entry.async_on_unload(
        setup_platform_listener(hass, entry.runtime_data, async_add_entities, factory)
    )


class NdRelayLight(NdEntity, LightEntity):
    """Um relé do equipamento."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_translation_key = "relay"

    def __init__(self, hub: NdHub, device: NdDevice, index: int) -> None:
        super().__init__(hub, device, f"ac_rs_r{index}")
        self._param = f"r{index}"
        assert device.caps is not None
        friendly = device.caps.friendly_names.get(f"{PATH_RELAYS}:{self._param}")
        if friendly:
            self._attr_name = friendly
        else:
            self._attr_translation_placeholders = {"number": str(index + 1)}

    @property
    def is_on(self) -> bool | None:
        return is_on(self._device.state.get(PATH_RELAYS, {}).get(self._param))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set("on")

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set("off")

    async def _set(self, value: str) -> None:
        await self._hub.async_command(
            self._device, PATH_RELAYS, {self._param: value}, {self._param: value}
        )
