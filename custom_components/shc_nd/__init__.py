"""Integração local do protocolo NDv2 (Smart Home Control) com o Home Assistant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .hub import NdHub

PLATFORMS: list[Platform] = [Platform.COVER, Platform.EVENT, Platform.LIGHT]

type NdConfigEntry = ConfigEntry[NdHub]


async def async_setup_entry(hass: HomeAssistant, entry: NdConfigEntry) -> bool:
    hub = NdHub(hass, entry)
    try:
        await hub.async_setup()
    except OSError as err:
        await hub.async_shutdown()
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_bind",
            translation_placeholders={"error": str(err)},
        ) from err
    entry.runtime_data = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hub.async_start_platforms()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NdConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: NdConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
