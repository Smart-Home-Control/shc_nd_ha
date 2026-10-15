"""Rede: UDP multicast 239.5.0.2:5202 (escuta e envio) e TCP 5203 (describe).

O TCP do equipamento atende UM cliente por vez e não derruba cliente ocioso
rapidamente: a integração nunca mantém conexão aberta. Conecta, envia, lê,
fecha — e só para a describe. Estado e comandos andam por UDP, como no Studio.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import socket
import struct
import time

from .const import (
    MAX_FRAME_LEN,
    MULTICAST_GROUP,
    TCP_CONNECT_TIMEOUT_S,
    TCP_IDLE_TIMEOUT_S,
    TCP_PORT,
    TCP_TOTAL_TIMEOUT_S,
    UDP_PORT,
    UDP_SPACING_S,
)
from .protocol import Frame, FrameError, parse_frame, split_stream

_LOGGER = logging.getLogger(__name__)

FrameCallback = Callable[[Frame, str], None]


def _make_socket(interface: str) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    sock.bind(("", UDP_PORT))
    mreq = struct.pack("4s4s", socket.inet_aton(MULTICAST_GROUP), socket.inet_aton(interface))
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    if interface != "0.0.0.0":
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface))
    # Fica na LAN: o protocolo não tem por que atravessar roteador.
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    sock.setblocking(False)
    return sock


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_frame: FrameCallback) -> None:
        self._on_frame = on_frame

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) > MAX_FRAME_LEN:
            return
        text = data.decode("utf-8", errors="replace")
        frames, _ = split_stream(text)
        for raw in frames:
            try:
                frame = parse_frame(raw)
            except FrameError:
                _LOGGER.debug("Discarding malformed frame from %s", addr[0])
                continue
            self._on_frame(frame, addr[0])

    def error_received(self, exc: Exception) -> None:
        _LOGGER.debug("UDP error: %s", exc)


class NdTransport:
    """Socket UDP compartilhado (multicast + unicast) e pedidos TCP pontuais."""

    def __init__(self, interface: str, on_frame: FrameCallback) -> None:
        self._interface = interface
        self._on_frame = on_frame
        self._transport: asyncio.DatagramTransport | None = None
        self._send_lock = asyncio.Lock()
        self._last_send = 0.0
        self._tcp_locks: dict[str, asyncio.Lock] = {}

    async def async_start(self) -> None:
        """Abre o socket. Levanta OSError se a porta não puder ser usada."""
        loop = asyncio.get_running_loop()
        sock = _make_socket(self._interface)
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _UdpProtocol(self._on_frame), sock=sock
        )

    async def async_stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    async def async_send(self, frame: str, ip: str | None = None) -> None:
        """Envia por unicast (quando o IP é conhecido) e pelo multicast.

        Os dois caminhos levam o MESMO frame e o MESMO seed: o firmware
        processa o primeiro e descarta o outro.
        """
        if self._transport is None:
            raise OSError("transport not started")
        data = frame.encode("ascii")
        async with self._send_lock:
            for target in ([ip] if ip else []) + [MULTICAST_GROUP]:
                wait = self._last_send + UDP_SPACING_S - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                self._transport.sendto(data, (target, UDP_PORT))
                self._last_send = time.monotonic()

    async def async_tcp_request(
        self,
        device_id: str,
        ip: str,
        frame: str,
        expected: int,
        accept: Callable[[Frame], bool],
    ) -> list[Frame]:
        """Pedido de várias respostas por TCP (a describe).

        Lê até `expected` frames do equipamento ou até o silêncio, e fecha.
        Um lock por equipamento garante uma conexão nossa por vez.
        """
        lock = self._tcp_locks.setdefault(device_id, asyncio.Lock())
        async with lock:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, TCP_PORT), TCP_CONNECT_TIMEOUT_S
            )
            frames: list[Frame] = []
            try:
                writer.write(frame.encode("ascii"))
                await writer.drain()
                buffer = ""
                deadline = time.monotonic() + TCP_TOTAL_TIMEOUT_S
                while len(frames) < expected and time.monotonic() < deadline:
                    try:
                        chunk = await asyncio.wait_for(reader.read(4096), TCP_IDLE_TIMEOUT_S)
                    except TimeoutError:
                        break
                    if not chunk:
                        break
                    buffer += chunk.decode("utf-8", errors="replace")
                    raws, buffer = split_stream(buffer)
                    for raw in raws:
                        try:
                            parsed = parse_frame(raw)
                        except FrameError:
                            continue
                        if parsed.device_id == device_id and accept(parsed):
                            frames.append(parsed)
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass
            return frames
