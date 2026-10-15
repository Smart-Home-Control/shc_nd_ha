"""Fluxo de configuração e opções."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shc_nd.const import CONF_INTERFACE, CONF_RECONCILE_MINUTES, DOMAIN

PROBE = "custom_components.shc_nd.config_flow.async_probe_network"


async def test_user_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with patch(PROBE, return_value=2), patch(
        "custom_components.shc_nd.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_INTERFACE: "0.0.0.0"}
        )
        assert result["step_id"] == "confirm"
        assert result["description_placeholders"] == {"count": "2"}
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_INTERFACE: "0.0.0.0"}


async def test_invalid_interface(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_INTERFACE: "eth0"}
    )
    assert result["errors"] == {CONF_INTERFACE: "invalid_interface"}


async def test_cannot_bind(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(PROBE, side_effect=OSError("in use")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_INTERFACE: "0.0.0.0"}
        )
    assert result["errors"] == {"base": "cannot_bind"}


async def test_single_instance(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, data={}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_INTERFACE: "0.0.0.0"})
    entry.add_to_hass(hass)
    with patch("custom_components.shc_nd.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_RECONCILE_MINUTES: 10}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_RECONCILE_MINUTES: 10}
