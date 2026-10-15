"""Persianas (`/ac/pers`): subir, descer e parar, sem posição.

O firmware não informa posição nem percentual, só o sentido em que o motor
está andando (`upN`/`downN`). Por isso a entidade não sabe se está aberta ou
fechada (`is_closed = None`) e não oferece "ir para a posição".
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import CoverDeviceClass, CoverEntity, CoverEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import NdConfigEntry
from .describe import PATH_COVERS
from .entity import NdEntity, setup_platform_listener
from .hub import NdDevice, NdHub
from .protocol import is_on


async def async_setup_entry(
    hass: HomeAssistant, entry: NdConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    def factory(hub: NdHub, device: NdDevice) -> list:
        assert device.caps is not None
        return [NdCover(hub, device, index) for index in device.caps.covers]

    entry.async_on_unload(
        setup_platform_listener(hass, entry.runtime_data, async_add_entities, factory)
    )


class NdCover(NdEntity, CoverEntity):
    """Uma persiana (par de relés com intertravamento no firmware)."""

    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
    )
    _attr_translation_key = "blind"
    _attr_assumed_state = True

    def __init__(self, hub: NdHub, device: NdDevice, index: int) -> None:
        super().__init__(hub, device, f"ac_pers_on{index}")
        self._index = index
        assert device.caps is not None
        friendly = device.caps.friendly_names.get(f"{PATH_COVERS}:on{index}")
        if friendly:
            self._attr_name = friendly
        else:
            self._attr_translation_placeholders = {"number": str(index + 1)}

    def _value(self, prefix: str) -> bool | None:
        return is_on(self._device.state.get(PATH_COVERS, {}).get(f"{prefix}{self._index}"))

    @property
    def is_closed(self) -> bool | None:
        return None

    @property
    def is_opening(self) -> bool:
        return bool(self._value("up"))

    @property
    def is_closing(self) -> bool:
        return bool(self._value("down"))

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self._send("on")

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self._send("off")

    async def async_stop_cover(self, **kwargs: Any) -> None:
        # Parar = comando contrário ao sentido atual (`off` subindo, `on`
        # descendo). Parado, não há o que fazer: não envia nada.
        if self.is_opening:
            await self._send("off")
        elif self.is_closing:
            await self._send("on")

    async def _send(self, value: str) -> None:
        await self._hub.async_command(
            self._device, PATH_COVERS, {f"on{self._index}": value}, None
        )
