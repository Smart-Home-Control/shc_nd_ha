"""Fixtures comuns."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.shc_nd.const import CONF_INTERFACE, DOMAIN

from .sim import FakeTransport, SimDevice


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Carrega custom_components/ nos testes."""


@pytest.fixture
def sim_devices() -> Generator[list[SimDevice]]:
    FakeTransport.instances = []
    FakeTransport.devices = []
    with patch("custom_components.shc_nd.hub.NdTransport", FakeTransport):
        yield FakeTransport.devices


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    config_entry = MockConfigEntry(
        domain=DOMAIN, title="SHC NDv2", data={CONF_INTERFACE: "0.0.0.0"}
    )
    config_entry.add_to_hass(hass)
    return config_entry


def transport() -> FakeTransport:
    return FakeTransport.instances[-1]
