"""Configuração pela interface: uma entrada por Home Assistant, sem cadastro de equipamento."""

from __future__ import annotations

import asyncio
import ipaddress
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback

from .const import (
    BROADCAST_ID,
    CONF_INTERFACE,
    CONF_RECONCILE_MINUTES,
    DEFAULT_INTERFACE,
    DEFAULT_RECONCILE_MINUTES,
    DOMAIN,
    SUPPORTED_TYPE,
)
from .protocol import Frame, build_frame, new_seed
from .transport import NdTransport

PROBE_SECONDS = 3.0


async def async_probe_network(interface: str) -> int:
    """Abre o socket, pergunta quem está na rede e conta os NDv2 que responderam.

    Levanta OSError se a porta 5202 ou o grupo multicast não puderem ser usados.
    """
    found: set[str] = set()

    def on_frame(frame: Frame, _ip: str) -> None:
        if frame.path == "/if/device" and frame.params.get("type") == SUPPORTED_TYPE:
            found.add(frame.device_id)

    transport = NdTransport(interface, on_frame)
    await transport.async_start()
    try:
        await transport.async_send(build_frame(BROADCAST_ID, "/if/device", seed=new_seed()))
        await asyncio.sleep(PROBE_SECONDS)
    finally:
        await transport.async_stop()
    return len(found)


class NdConfigFlow(ConfigFlow, domain=DOMAIN):
    """Fluxo de configuração."""

    VERSION = 1

    def __init__(self) -> None:
        self._interface = DEFAULT_INTERFACE
        self._found = 0

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            interface = user_input.get(CONF_INTERFACE, DEFAULT_INTERFACE).strip() or DEFAULT_INTERFACE
            try:
                ipaddress.IPv4Address(interface)
            except ValueError:
                errors[CONF_INTERFACE] = "invalid_interface"
            else:
                try:
                    self._found = await async_probe_network(interface)
                except OSError:
                    errors["base"] = "cannot_bind"
                else:
                    self._interface = interface
                    return await self.async_step_confirm()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Optional(CONF_INTERFACE, default=DEFAULT_INTERFACE): str}
            ),
            errors=errors,
        )

    async def async_step_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="SHC NDv2", data={CONF_INTERFACE: self._interface}
            )
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"count": str(self._found)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return NdOptionsFlow()


class NdOptionsFlow(OptionsFlow):
    """Intervalo da reconciliação periódica."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(CONF_RECONCILE_MINUTES, DEFAULT_RECONCILE_MINUTES)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_RECONCILE_MINUTES, default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=60)
                    )
                }
            ),
        )
