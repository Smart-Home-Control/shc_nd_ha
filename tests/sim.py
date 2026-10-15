"""Equipamentos ND simulados e um transporte falso que fala com eles.

Os frames seguem as capturas reais da bancada (15/10/2026) e o emulador
MRQ10 NDv2 do Studio, conferido contra o 72B0 real.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import json
from typing import Any

from custom_components.shc_nd.protocol import Frame, build_frame, parse_frame, parse_query


def rs_descriptor(count: int = 10) -> dict[str, Any]:
    return {
        "name": "rs",
        "path": "/ac/rs",
        "params": [
            {"name": f"r{i}", "type": "Boolean", "params": ["toggle", "on", "off"]}
            for i in range(count)
        ],
        "paramsResponse": [],
    }


def pers_descriptor(count: int = 5) -> dict[str, Any]:
    return {
        "name": "pers",
        "path": "/ac/pers",
        "params": [
            {"name": f"on{i}", "type": "Boolean", "params": ["toggle", "on", "off"]}
            for i in range(count)
        ],
        "paramsResponse": [],
    }


BT_DESCRIPTOR = {
    "name": "bt",
    "path": "/ac/bt",
    "params": [],
    "paramsResponse": [
        {"name": "s", "params": ["RE", "PRE", "HO", "HD", "CL"], "type": "Chosen"},
        {"name": "b", "params": ["$max=10"], "type": "Integer"},
        {"name": "t", "params": ["$max=255"], "type": "Integer"},
    ],
}


def cs_descriptor(index: int) -> dict[str, Any]:
    return {
        "name": f"bt{index}",
        "path": f"/cs/bt{index}",
        "params": [{"name": "query", "type": "String", "params": ["$max=256"]}],
        "paramsResponse": [],
    }


LB_DEVICE = {
    "name": "device",
    "path": "/lb/device",
    "params": [{"name": "name", "type": "String", "params": ["$max=50"]}],
    "paramsResponse": [],
}


@dataclass
class SimDevice:
    device_id: str
    ip: str
    model: str
    version: str = "3.3.0"
    fw_type: str = "NDV2"
    descriptors: list[dict[str, Any]] = field(default_factory=list)
    relays: dict[str, str] = field(default_factory=dict)
    covers: dict[str, str] = field(default_factory=dict)
    online: bool = True
    tcp_ok: bool = True
    drop_commands: int = 0
    seen_seeds: set[int] = field(default_factory=set)
    executed: list[str] = field(default_factory=list)
    received: list[Frame] = field(default_factory=list)

    @property
    def nac(self) -> int:
        return len(self.descriptors)

    def info_frame(self, seed: int = 2006106) -> str:
        code = "1001" if self.fw_type == "NDV2" else "1"
        return (
            f"${self.device_id}>/if/device@0?code={code}&model={self.model}"
            f"&deviceName={self.model}-{self.device_id}&version={self.version}"
            f"&serialNumber=000&type={self.fw_type}&id={self.device_id}"
            f"&date=Aug%2028%202026&nAC={self.nac}<{seed}#"
        )

    def describe_frames(self) -> list[str]:
        return [
            f"${self.device_id}>{d['path']}@9?{json.dumps(d, separators=(',', ':'))}<{i + 1}#"
            for i, d in enumerate(self.descriptors)
        ]

    def state_frame(self, path: str, seed: int) -> str:
        values = self.relays if path == "/ac/rs" else self.covers
        query = "&".join(f"{k}={v}" for k, v in values.items())
        return f"${self.device_id}>{path}@0?code=1001&{query}<{seed}#"

    def handle(self, frame: Frame) -> list[str]:
        """Resposta do firmware a um frame recebido."""
        if not self.online:
            return []
        if frame.device_id not in (self.device_id, "0000"):
            return []
        self.received.append(frame)
        if frame.path == "/if/device":
            return [self.info_frame()]
        if self.fw_type != "NDV2":
            return []
        if frame.proto == 9 and frame.path == "/*":
            return self.describe_frames()
        if frame.path in ("/ac/rs", "/ac/pers") and frame.proto == 0:
            values = self.relays if frame.path == "/ac/rs" else self.covers
            params = parse_query(frame.query)
            if params:
                if self.drop_commands > 0:
                    self.drop_commands -= 1
                    return []
                if frame.seed in self.seen_seeds:
                    return [self.state_frame(frame.path, 7777)]
                self.seen_seeds.add(frame.seed)
                self.executed.append(frame.query)
                for key, value in params.items():
                    if key in values:
                        values[key] = value
            return [self.state_frame(frame.path, 4242 + len(self.executed))]
        return []


def mrq10(device_id: str = "72B0", ip: str = "192.168.1.7") -> SimDevice:
    return SimDevice(
        device_id,
        ip,
        "MRQ10",
        descriptors=[rs_descriptor(), LB_DEVICE],
        relays={f"r{i}": "off" for i in range(10)},
    )


def keypad(device_id: str = "CA00", ip: str = "192.168.1.8") -> SimDevice:
    return SimDevice(
        device_id,
        ip,
        "KEYPADWIFI",
        descriptors=[BT_DESCRIPTOR, LB_DEVICE] + [cs_descriptor(i) for i in range(8)],
    )


class FakeTransport:
    """Substitui o NdTransport: entrega os frames aos simulados e devolve as respostas."""

    instances: list[FakeTransport] = []
    devices: list[SimDevice] = []

    def __init__(self, interface: str, on_frame: Callable[[Frame, str], None]) -> None:
        self.interface = interface
        self.on_frame = on_frame
        self.sent: list[tuple[str, str | None]] = []
        self.tcp_requests: list[str] = []
        self.started = False
        FakeTransport.instances.append(self)

    async def async_start(self) -> None:
        self.started = True

    async def async_stop(self) -> None:
        self.started = False

    async def async_send(self, frame: str, ip: str | None = None) -> None:
        self.sent.append((frame, ip))
        parsed = parse_frame(frame)
        loop = asyncio.get_running_loop()
        for device in self.devices:
            for reply in device.handle(parsed):
                loop.call_soon(self.deliver, reply, device.ip)

    async def async_tcp_request(
        self,
        device_id: str,
        ip: str,
        frame: str,
        expected: int,
        accept: Callable[[Frame], bool],
    ) -> list[Frame]:
        self.tcp_requests.append(frame)
        parsed = parse_frame(frame)
        for device in self.devices:
            if device.device_id == device_id and device.ip == ip:
                if not device.tcp_ok:
                    raise OSError("connection refused")
                return [
                    f for f in (parse_frame(r) for r in device.handle(parsed)) if accept(f)
                ]
        raise TimeoutError

    def deliver(self, raw: str, ip: str) -> None:
        if self.started:
            self.on_frame(parse_frame(raw), ip)

    def push(self, device: SimDevice, raw: str) -> None:
        """Frame espontâneo do equipamento (mudança física, botão)."""
        self.deliver(raw, device.ip)


def frame_for(device: SimDevice, path: str, params: dict[str, str], seed: int) -> str:
    return build_frame(device.device_id, path, params, seed=seed)
