"""Transporte: espaçamento por destino (o equipamento perde frame em rajada)."""

from __future__ import annotations

import asyncio
import time

from custom_components.shc_nd.const import MULTICAST_GROUP, UDP_SPACING_S
from custom_components.shc_nd.transport import NdTransport


class _Recorder:
    def __init__(self) -> None:
        self.sent: list[tuple[float, str]] = []

    def sendto(self, data: bytes, addr: tuple[str, int]) -> None:
        self.sent.append((time.monotonic(), addr[0]))


def _transport() -> tuple[NdTransport, _Recorder]:
    transport = NdTransport("0.0.0.0", lambda frame, ip: None)
    recorder = _Recorder()
    transport._transport = recorder  # type: ignore[assignment]
    return transport, recorder


async def test_unicast_only_when_asked() -> None:
    transport, recorder = _transport()
    await transport.async_send("$72B0>/ac/rs@0?r0=on<1#", "192.168.1.7", multicast=False)
    assert [ip for _, ip in recorder.sent] == ["192.168.1.7"]


async def test_without_ip_always_multicast() -> None:
    transport, recorder = _transport()
    await transport.async_send("$0000>/if/device@0?<1#", None, multicast=False)
    assert [ip for _, ip in recorder.sent] == [MULTICAST_GROUP]


async def test_same_device_is_spaced() -> None:
    transport, recorder = _transport()
    await transport.async_send("$72B0>/ac/rs@0?r0=on<1#", "192.168.1.7", multicast=False)
    await transport.async_send("$72B0>/ac/rs@0?r1=on<2#", "192.168.1.7", multicast=False)
    (t1, _), (t2, _) = recorder.sent
    assert t2 - t1 >= UDP_SPACING_S * 0.95


async def test_other_device_is_not_delayed() -> None:
    transport, recorder = _transport()
    await transport.async_send("$72B0>/ac/rs@0?r0=on<1#", "192.168.1.7", multicast=False)
    await transport.async_send("$B000>/ac/rs@0?r0=on<2#", "192.168.1.9", multicast=False)
    (t1, _), (t2, _) = recorder.sent
    assert t2 - t1 < UDP_SPACING_S / 2


async def test_multicast_counts_for_every_device() -> None:
    transport, recorder = _transport()
    await transport.async_send("$72B0>/ac/rs@0?r0=on<1#", "192.168.1.7")
    (t_uni, ip1), (t_multi, ip2) = recorder.sent
    assert (ip1, ip2) == ("192.168.1.7", MULTICAST_GROUP)
    assert t_multi - t_uni >= UDP_SPACING_S * 0.95
    await transport.async_send("$B000>/ac/rs@0?r0=on<2#", "192.168.1.9", multicast=False)
    assert recorder.sent[-1][0] - t_multi >= UDP_SPACING_S * 0.95


async def test_waits_for_network_quiet() -> None:
    transport, recorder = _transport()
    transport._mark_rx()
    start = time.monotonic()
    await transport.async_send("$72B0>/ac/rs@0?r0=on<1#", "192.168.1.7", multicast=False)
    assert recorder.sent[0][0] - start >= 0.14


async def test_quiet_wait_is_capped() -> None:
    from custom_components.shc_nd.const import RX_QUIET_MAX_WAIT_S

    transport, recorder = _transport()
    start = time.monotonic()

    async def chatter() -> None:
        while time.monotonic() - start < 2:
            transport._mark_rx()
            await asyncio.sleep(0.02)

    task = asyncio.create_task(chatter())
    await transport.async_send("$72B0>/ac/rs@0?r0=on<1#", "192.168.1.7", multicast=False)
    task.cancel()
    assert recorder.sent[0][0] - start < RX_QUIET_MAX_WAIT_S + 0.2
