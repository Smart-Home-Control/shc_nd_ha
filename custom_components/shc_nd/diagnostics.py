"""Diagnóstico: o que a integração sabe de cada equipamento (sem segredos)."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.core import HomeAssistant

from . import NdConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NdConfigEntry
) -> dict[str, Any]:
    hub = entry.runtime_data
    now = time.monotonic()
    return {
        "options": dict(entry.options),
        "data": dict(entry.data),
        "devices": [
            {
                "id": d.device_id,
                "model": d.model,
                "version": d.version,
                "name": d.name,
                "nac": d.nac,
                "ip": d.ip,
                "available": d.available,
                "seconds_since_seen": round(now - d.last_seen) if d.last_seen else None,
                "relays": d.caps.relays if d.caps else None,
                "covers": d.caps.covers if d.caps else None,
                "buttons": d.caps.buttons if d.caps else None,
                "button_events": d.caps.button_events if d.caps else None,
                "state": d.state,
            }
            for d in hub.devices.values()
        ],
    }
