"""Integração inteira contra equipamentos simulados."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.components.light import DOMAIN as LIGHT_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.shc_nd.const import DOMAIN, EVENT_BUTTON, OFFLINE_AFTER_S
from custom_components.shc_nd.protocol import parse_frame

from .conftest import transport
from .sim import SimDevice, keypad, mrq10, pers_descriptor

RELAY0 = "light.mrq10_72b0_relay_1"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _entities(hass: HomeAssistant, entry: MockConfigEntry, domain: str) -> list[str]:
    return sorted(
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain == domain
    )


async def test_discovery_creates_entities_only_for_ndv2(
    hass: HomeAssistant, entry: MockConfigEntry, sim_devices: list[SimDevice]
) -> None:
    legacy = mrq10("E4FB", "192.168.1.5")
    legacy.fw_type = "RELE"
    legacy.version = "2.4.25"
    sim_devices += [mrq10(), keypad(), legacy]

    await _setup(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    lights = _entities(hass, entry, "light")
    assert len(lights) == 10
    assert RELAY0 in lights
    assert len(_entities(hass, entry, "event")) == 8
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert {d.serial_number for d in devices} == {"72B0", "CA00"}
    # O antigo só respondeu à descoberta geral; nada foi endereçado a ele.
    assert all(f.device_id == "0000" for f in legacy.received)
    assert hass.states.get(RELAY0).state == STATE_OFF


async def test_physical_change_updates_state(
    hass: HomeAssistant, entry: MockConfigEntry, sim_devices: list[SimDevice]
) -> None:
    device = mrq10()
    sim_devices.append(device)
    await _setup(hass, entry)

    device.relays["r0"] = "on"
    transport().push(device, device.state_frame("/ac/rs", 99))
    await hass.async_block_till_done()
    assert hass.states.get(RELAY0).state == STATE_ON

    # Intenção de cena de um keypad (sem `code`) não é estado.
    transport().push(device, "$72B0>/ac/rs@0?r0=off<555#")
    await hass.async_block_till_done()
    assert hass.states.get(RELAY0).state == STATE_ON


async def test_turn_on_is_confirmed(
    hass: HomeAssistant, entry: MockConfigEntry, sim_devices: list[SimDevice]
) -> None:
    device = mrq10()
    sim_devices.append(device)
    await _setup(hass, entry)

    await hass.services.async_call(LIGHT_DOMAIN, "turn_on", {ATTR_ENTITY_ID: RELAY0}, blocking=True)
    assert hass.states.get(RELAY0).state == STATE_ON
    assert device.executed == ["r0=on"]
    sent = [f for f, _ in transport().sent if "r0=on" in f]
    assert len(sent) == 1
    # Unicast para o IP conhecido.
    assert [ip for f, ip in transport().sent if "r0=on" in f] == [device.ip]


async def test_lost_command_is_retried_with_same_seed(
    hass: HomeAssistant, entry: MockConfigEntry, sim_devices: list[SimDevice]
) -> None:
    device = mrq10()
    sim_devices.append(device)
    await _setup(hass, entry)

    device.drop_commands = 1
    with patch("custom_components.shc_nd.hub.COMMAND_TIMEOUT_S", 0.05):
        await hass.services.async_call(
            LIGHT_DOMAIN, "turn_on", {ATTR_ENTITY_ID: RELAY0}, blocking=True
        )
    sent = [f for f, _ in transport().sent if "r0=on" in f]
    assert len(sent) == 2
    assert len({parse_frame(f).seed for f in sent}) == 1
    assert device.executed == ["r0=on"]
    assert hass.states.get(RELAY0).state == STATE_ON


async def test_unconfirmed_command_raises_and_rereads(
    hass: HomeAssistant, entry: MockConfigEntry, sim_devices: list[SimDevice]
) -> None:
    device = mrq10()
    sim_devices.append(device)
    await _setup(hass, entry)

    device.drop_commands = 99
    with (
        patch("custom_components.shc_nd.hub.COMMAND_TIMEOUT_S", 0.05),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            LIGHT_DOMAIN, "turn_on", {ATTR_ENTITY_ID: RELAY0}, blocking=True
        )
    await hass.async_block_till_done()
    assert transport().sent[-1][0].startswith("$72B0>/ac/rs@0?<")
    assert hass.states.get(RELAY0).state == STATE_OFF


async def test_button_events(
    hass: HomeAssistant, entry: MockConfigEntry, sim_devices: list[SimDevice]
) -> None:
    device = keypad()
    sim_devices.append(device)
    await _setup(hass, entry)
    events = async_capture_events(hass, EVENT_BUTTON)
    entity_id = "event.keypadwifi_ca00_button_1"

    for raw in (
        "$CA00>/ac/bt@0?code=0&s=PRE&b=0&t=0<2841000#",
        "$CA00>/ac/bt@0?code=0&s=CL&b=0&t=0<57000#",
        "$CA00>/ac/bt@0?code=0&s=CL&b=0&t=0<57000#",  # cópia: descartada
    ):
        transport().push(device, raw)
    await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state.attributes["event_type"] == "click"
    assert [e.data["gesture"] for e in events] == ["press", "click"]
    assert events[0].data["nd_id"] == "CA00"
    assert events[0].data["device_id"] is not None

    transport().push(device, "$CA00>/ac/bt@0?code=0&s=RE&b=0&t=4<3597000#")
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.attributes["event_type"] == "release"
    assert state.attributes["duration"] == 4

    # Gesto desconhecido ou botão fora da faixa: ignorado.
    transport().push(device, "$CA00>/ac/bt@0?code=0&s=XX&b=0&t=0<1#")
    transport().push(device, "$CA00>/ac/bt@0?code=0&s=CL&b=abc&t=0<2#")
    await hass.async_block_till_done()
    assert len(events) == 3


async def test_ip_change_keeps_device(
    hass: HomeAssistant, entry: MockConfigEntry, sim_devices: list[SimDevice]
) -> None:
    device = mrq10()
    sim_devices.append(device)
    await _setup(hass, entry)
    hub = entry.runtime_data

    device.ip = "192.168.1.77"
    transport().push(device, device.info_frame(seed=31337))
    await hass.async_block_till_done()

    assert hub.devices["72B0"].ip == "192.168.1.77"
    assert len(_entities(hass, entry, "light")) == 10
    assert len(dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)) == 1


async def test_offline_and_recovery(
    hass: HomeAssistant, entry: MockConfigEntry, sim_devices: list[SimDevice]
) -> None:
    device = mrq10()
    sim_devices.append(device)
    await _setup(hass, entry)
    hub = entry.runtime_data

    device.online = False
    hub.devices["72B0"].last_seen -= OFFLINE_AFTER_S + 1
    await hub._availability_tick()
    await hass.async_block_till_done()
    assert hass.states.get(RELAY0).state == STATE_UNAVAILABLE

    # Enquanto esteve fora, alguém ligou o relé no quadro.
    device.online = True
    device.relays["r0"] = "on"
    transport().push(device, device.info_frame(seed=8080))
    await hass.async_block_till_done()
    assert hass.states.get(RELAY0).state == STATE_ON


async def test_restart_restores_entities_before_device_answers(
    hass: HomeAssistant, entry: MockConfigEntry, sim_devices: list[SimDevice]
) -> None:
    device = mrq10()
    sim_devices.append(device)
    await _setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    device.online = False
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(RELAY0).state == STATE_UNAVAILABLE
    # A describe veio do cache: nenhum pedido novo.
    assert transport().tcp_requests == []


async def test_tcp_failure_falls_back_to_udp_describe(
    hass: HomeAssistant, entry: MockConfigEntry, sim_devices: list[SimDevice]
) -> None:
    device = mrq10()
    device.tcp_ok = False
    sim_devices.append(device)
    with patch("custom_components.shc_nd.hub.UDP_DESCRIBE_WINDOW_S", 0.5):
        await _setup(hass, entry)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert len(_entities(hass, entry, "light")) == 10


async def test_cover(
    hass: HomeAssistant, entry: MockConfigEntry, sim_devices: list[SimDevice]
) -> None:
    device = mrq10()
    device.descriptors = [pers_descriptor(5)]
    device.covers = {f"on{i}": "off" for i in range(5)} | {f"up{i}": "off" for i in range(5)} | {
        f"down{i}": "off" for i in range(5)
    }
    sim_devices.append(device)
    await _setup(hass, entry)

    assert _entities(hass, entry, "light") == []
    covers = _entities(hass, entry, "cover")
    assert len(covers) == 5
    await hass.services.async_call(
        COVER_DOMAIN, "open_cover", {ATTR_ENTITY_ID: covers[0]}, blocking=True
    )
    assert device.executed == ["on0=on"]

    device.covers["up0"] = "on"
    transport().push(device, device.state_frame("/ac/pers", 1234))
    await hass.async_block_till_done()
    assert hass.states.get(covers[0]).state == "opening"
    await hass.services.async_call(
        COVER_DOMAIN, "stop_cover", {ATTR_ENTITY_ID: covers[0]}, blocking=True
    )
    assert device.executed[-1] == "on0=off"


async def test_never_writes_configuration(
    hass: HomeAssistant, entry: MockConfigEntry, sim_devices: list[SimDevice]
) -> None:
    device = mrq10()
    sim_devices += [device, keypad()]
    await _setup(hass, entry)
    await hass.services.async_call(LIGHT_DOMAIN, "turn_on", {ATTR_ENTITY_ID: RELAY0}, blocking=True)
    await hass.services.async_call(LIGHT_DOMAIN, "turn_off", {ATTR_ENTITY_ID: RELAY0}, blocking=True)

    frames = [parse_frame(f) for f, _ in transport().sent] + [
        parse_frame(f) for f in transport().tcp_requests
    ]
    for frame in frames:
        assert frame.proto in (0, 9)
        assert not frame.path.startswith(("/lb", "/cs", "/cf", "/aa"))
        assert "toggle" not in frame.query
        assert "_to" not in frame.query
        if frame.path not in ("/ac/rs", "/ac/pers"):
            assert frame.query == ""


async def test_unknown_id_is_probed(
    hass: HomeAssistant, entry: MockConfigEntry, sim_devices: list[SimDevice]
) -> None:
    await _setup(hass, entry)
    late = mrq10("B000", "192.168.1.9")
    sim_devices.append(late)
    # Ele aparece no multicast respondendo a outro cliente.
    transport().push(late, late.state_frame("/ac/rs", 4321))
    await hass.async_block_till_done()
    assert "B000" in entry.runtime_data.devices
    assert len(_entities(hass, entry, "light")) == 10


async def test_diagnostics(
    hass: HomeAssistant, entry: MockConfigEntry, sim_devices: list[SimDevice]
) -> None:
    from custom_components.shc_nd.diagnostics import async_get_config_entry_diagnostics

    sim_devices.append(mrq10())
    await _setup(hass, entry)
    data = await async_get_config_entry_diagnostics(hass, entry)
    assert data["devices"][0]["id"] == "72B0"
    assert data["devices"][0]["relays"] == list(range(10))
    assert DOMAIN == "shc_nd"
