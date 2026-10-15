"""O coração da integração: descoberta, estado, eventos e comandos.

Fluxo:
- Escuta o multicast. Todo equipamento publica ali as respostas e as mudanças
  de estado, e o keypad publica o gesto de cada botão (`/ac/bt`).
- Descobre com `$0000>/if/device` ao iniciar e a cada minuto. Um ID ainda
  desconhecido que aparece no multicast é sondado na hora.
- Para cada equipamento NDv2 novo, lê a describe (`/*@9`) uma vez por
  modelo + versão e cria as entidades a partir dela.
- Consulta o estado ao iniciar, quando um equipamento volta a responder e numa
  reconciliação periódica de baixa frequência. Não há polling contínuo.
- Comando: frame com seed fixo, reenviado até a resposta de estado confirmar
  (o firmware descarta o repetido pelo seed).

A identidade é o ID do equipamento (4 hex), nunca o IP: trocar de IP por DHCP
só atualiza o endereço guardado.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import (
    BROADCAST_ID,
    COMMAND_ATTEMPTS,
    COMMAND_TIMEOUT_S,
    CONF_INTERFACE,
    CONF_RECONCILE_MINUTES,
    DEDUP_TTL_S,
    DEFAULT_INTERFACE,
    DEFAULT_RECONCILE_MINUTES,
    DISCOVERY_INTERVAL_S,
    DOMAIN,
    EVENT_BUTTON,
    GESTURES,
    OFFLINE_AFTER_S,
    PROBE_COOLDOWN_S,
    SIGNAL_BUTTON,
    SIGNAL_DEVICE_READY,
    SIGNAL_DEVICE_UPDATE,
    STORAGE_VERSION,
    SUPPORTED_TYPE,
    UDP_DESCRIBE_WINDOW_S,
)
from .describe import (
    PATH_BUTTON_EVENT,
    PATH_COVERS,
    PATH_RELAYS,
    Capabilities,
    capabilities,
    parse_descriptor,
)
from .protocol import PROTO_DESCRIPTION, PROTO_SET_DATA, Frame, build_frame, new_seed
from .transport import NdTransport

_LOGGER = logging.getLogger(__name__)

_STATE_PATHS = (PATH_RELAYS, PATH_COVERS)
_IGNORED_RETRY_S = 3600
_DESCRIBE_RETRY_S = 60
_MAX_NAC = 200


@dataclass(slots=True)
class NdDevice:
    """Um equipamento NDv2 conhecido."""

    device_id: str
    model: str
    version: str
    name: str
    nac: int
    ip: str | None = None
    caps: Capabilities | None = None
    available: bool = False
    last_seen: float = 0.0
    state: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def describe_key(self) -> str:
        return f"{self.model}|{self.version}|{self.nac}"


@dataclass(slots=True)
class _Waiter:
    device_id: str
    path: str
    expect: dict[str, str] | None
    future: asyncio.Future[None]


class NdHub:
    """Estado compartilhado por todas as plataformas de uma entrada."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        transport_factory: Callable[..., NdTransport] | None = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.devices: dict[str, NdDevice] = {}
        self._transport = (transport_factory or NdTransport)(
            entry.data.get(CONF_INTERFACE, DEFAULT_INTERFACE), self._on_frame
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._describe_cache: dict[str, dict[str, dict[str, Any]]] = {}
        self._dedup: dict[tuple[str, int, str, str], float] = {}
        self._probed: dict[str, float] = {}
        self._ignored: dict[str, float] = {}
        self._describing: set[str] = set()
        self._describe_failed: dict[str, float] = {}
        self._collectors: dict[str, list[Frame]] = {}
        self._waiters: list[_Waiter] = []
        self._ready: set[str] = set()
        self._platforms_ready = False
        self._unsubs: list[Callable[[], None]] = []
        self._tasks: set[asyncio.Task[Any]] = set()

    # ── ciclo de vida ────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        stored = await self._store.async_load() or {}
        self._describe_cache = stored.get("describe", {})
        for device_id, data in stored.get("devices", {}).items():
            try:
                device = NdDevice(
                    device_id=device_id,
                    model=str(data["model"]),
                    version=str(data["version"]),
                    name=str(data["name"]),
                    nac=int(data["nac"]),
                    ip=data.get("ip"),
                )
            except (KeyError, TypeError, ValueError):
                continue
            descriptors = self._describe_cache.get(device.describe_key)
            if descriptors:
                device.caps = capabilities(descriptors)
            self.devices[device_id] = device

        await self._transport.async_start()

        minutes = self.entry.options.get(CONF_RECONCILE_MINUTES, DEFAULT_RECONCILE_MINUTES)
        self._unsubs += [
            async_track_time_interval(
                self.hass, self._discovery_tick, timedelta(seconds=DISCOVERY_INTERVAL_S)
            ),
            async_track_time_interval(self.hass, self._availability_tick, timedelta(seconds=30)),
            async_track_time_interval(
                self.hass, self._reconcile_tick, timedelta(minutes=minutes)
            ),
        ]
        self._spawn(self.async_discover())

    @callback
    def async_start_platforms(self) -> None:
        """Anuncia às plataformas os equipamentos já conhecidos (após um restart).

        Eles nascem indisponíveis e ficam disponíveis quando responderem. Uma
        describe que termine antes deste ponto também é anunciada aqui.
        """
        self._platforms_ready = True
        for device in self.devices.values():
            if device.caps is not None:
                self._announce(device)

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for task in list(self._tasks):
            task.cancel()
        for waiter in self._waiters:
            if not waiter.future.done():
                waiter.future.cancel()
        await self._transport.async_stop()
        await self._async_save()

    def _spawn(self, coro: Any) -> None:
        task = self.entry.async_create_background_task(self.hass, coro, f"{DOMAIN} task")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "devices": {
                    d.device_id: {
                        "model": d.model,
                        "version": d.version,
                        "name": d.name,
                        "nac": d.nac,
                        "ip": d.ip,
                    }
                    for d in self.devices.values()
                },
                "describe": self._describe_cache,
            }
        )

    # ── recepção ─────────────────────────────────────────────────────────────

    @callback
    def _on_frame(self, frame: Frame, source_ip: str) -> None:
        if frame.device_id == BROADCAST_ID:
            return
        now = time.monotonic()
        key = (frame.device_id, frame.seed, frame.path, frame.query)
        if (seen := self._dedup.get(key)) is not None and now - seen < DEDUP_TTL_S:
            return
        _LOGGER.debug(
            "RX %s %s@%d?%s<%d from %s",
            frame.device_id,
            frame.path,
            frame.proto,
            frame.query[:200],
            frame.seed,
            source_ip,
        )
        self._dedup[key] = now
        if len(self._dedup) > 512:
            self._dedup = {k: t for k, t in self._dedup.items() if now - t < DEDUP_TTL_S}

        if frame.path == "/if/device" and frame.proto == PROTO_SET_DATA:
            if frame.ok:
                self._handle_info(frame, source_ip)
            return

        device = self.devices.get(frame.device_id)
        if device is None:
            # Frame com `code` só vem do próprio equipamento; sem `code` é a
            # intenção de outro (cena de keypad, comando do Studio).
            if frame.code is not None:
                self._probe(frame.device_id)
            return

        if frame.code is not None:
            self._mark_seen(device)

        if frame.proto == PROTO_DESCRIPTION:
            if (collector := self._collectors.get(frame.device_id)) is not None:
                collector.append(frame)
            return

        if frame.proto != PROTO_SET_DATA:
            return
        if frame.path in _STATE_PATHS and frame.ok:
            self._handle_state(device, frame)
        elif frame.path == PATH_BUTTON_EVENT:
            self._handle_button(device, frame)

    @callback
    def _handle_info(self, frame: Frame, source_ip: str) -> None:
        params = frame.params
        if params.get("id", frame.device_id).upper() != frame.device_id:
            return
        if params.get("type") != SUPPORTED_TYPE:
            if frame.device_id not in self._ignored:
                _LOGGER.info(
                    "Ignoring %s %s (type=%s, version=%s): only NDv2 firmware is supported",
                    params.get("model"),
                    frame.device_id,
                    params.get("type"),
                    params.get("version"),
                )
            self._ignored[frame.device_id] = time.monotonic()
            return
        try:
            nac = max(0, min(int(params.get("nAC", "0")), _MAX_NAC))
        except ValueError:
            nac = 0
        model = params.get("model", "")[:32] or "NDV2"
        version = params.get("version", "")[:16]
        name = params.get("deviceName", "")[:64] or f"{model}-{frame.device_id}"

        device = self.devices.get(frame.device_id)
        if device is None:
            device = NdDevice(frame.device_id, model, version, name, nac, ip=source_ip)
            self.devices[frame.device_id] = device
            _LOGGER.info("Discovered %s %s at %s", model, frame.device_id, source_ip)
            self._spawn(self._async_save())
        else:
            if device.ip != source_ip:
                _LOGGER.info(
                    "%s %s moved from %s to %s", model, frame.device_id, device.ip, source_ip
                )
                device.ip = source_ip
                self._spawn(self._async_save())
            if (device.model, device.version, device.nac) != (model, version, nac):
                device.model, device.version, device.nac = model, version, nac
                device.caps = None
                self._spawn(self._async_save())
        self._mark_seen(device)
        if device.caps is None:
            self._maybe_describe(device)

    @callback
    def _handle_state(self, device: NdDevice, frame: Frame) -> None:
        values = {k: v for k, v in frame.params.items() if k != "code" and not k.startswith("_")}
        current = device.state.setdefault(frame.path, {})
        current.update(values)
        for waiter in self._waiters:
            if (
                not waiter.future.done()
                and waiter.device_id == device.device_id
                and waiter.path == frame.path
                and (
                    waiter.expect is None
                    or all(values.get(k) == v for k, v in waiter.expect.items())
                )
            ):
                waiter.future.set_result(None)
        self._notify(device)

    @callback
    def _handle_button(self, device: NdDevice, frame: Frame) -> None:
        gesture = GESTURES.get(frame.params.get("s", ""))
        try:
            button = int(frame.params.get("b", ""))
            duration = int(frame.params.get("t", "0") or 0)
        except ValueError:
            return
        if gesture is None or not 0 <= button <= 64 or not 0 <= duration <= 65535:
            return
        async_dispatcher_send(
            self.hass,
            SIGNAL_BUTTON.format(entry_id=self.entry.entry_id, device_id=device.device_id),
            button,
            gesture,
            duration,
        )
        registry_device = dr.async_get(self.hass).async_get_device(
            identifiers={(DOMAIN, device.device_id)}
        )
        self.hass.bus.async_fire(
            EVENT_BUTTON,
            {
                "device_id": registry_device.id if registry_device else None,
                "nd_id": device.device_id,
                "button": button,
                "gesture": gesture,
                "duration": duration,
            },
        )

    @callback
    def _mark_seen(self, device: NdDevice) -> None:
        device.last_seen = time.monotonic()
        if not device.available:
            device.available = True
            self._notify(device)
            # Voltou (ou acabou de ligar): o estado pode ter mudado enquanto
            # estava fora ou um pacote pode ter se perdido. Relê tudo.
            if device.caps is not None:
                self._spawn(self.async_refresh_state(device))

    @callback
    def _notify(self, device: NdDevice) -> None:
        async_dispatcher_send(
            self.hass,
            SIGNAL_DEVICE_UPDATE.format(entry_id=self.entry.entry_id, device_id=device.device_id),
        )

    @callback
    def _announce(self, device: NdDevice) -> None:
        if not self._platforms_ready or device.device_id in self._ready:
            return
        self._ready.add(device.device_id)
        async_dispatcher_send(
            self.hass, SIGNAL_DEVICE_READY.format(entry_id=self.entry.entry_id), device
        )

    # ── descoberta e describe ────────────────────────────────────────────────

    async def async_discover(self) -> None:
        """`$0000>/if/device`: todo equipamento responde com o próprio ID."""
        await self._send(build_frame(BROADCAST_ID, "/if/device", seed=new_seed()))

    @callback
    def _probe(self, device_id: str) -> None:
        now = time.monotonic()
        if (ignored := self._ignored.get(device_id)) and now - ignored < _IGNORED_RETRY_S:
            return
        if (probed := self._probed.get(device_id)) and now - probed < PROBE_COOLDOWN_S:
            return
        self._probed[device_id] = now
        self._spawn(self._send(build_frame(device_id, "/if/device", seed=new_seed())))

    @callback
    def _maybe_describe(self, device: NdDevice) -> None:
        if device.device_id in self._describing:
            return
        failed = self._describe_failed.get(device.device_id)
        if failed and time.monotonic() - failed < _DESCRIBE_RETRY_S:
            return
        self._describing.add(device.device_id)
        self._spawn(self._async_describe(device))

    async def _async_describe(self, device: NdDevice) -> None:
        try:
            descriptors = self._describe_cache.get(device.describe_key)
            if descriptors is None:
                descriptors = await self._async_fetch_descriptors(device)
                if descriptors is None:
                    self._describe_failed[device.device_id] = time.monotonic()
                    _LOGGER.warning(
                        "Could not read the description of %s %s; will retry",
                        device.model,
                        device.device_id,
                    )
                    return
            caps = capabilities(descriptors)
            previous = device.caps
            device.caps = caps
            await self._async_save()
            if device.device_id in self._ready and previous != caps:
                # Firmware novo com outras capacidades: recria as entidades.
                self.hass.config_entries.async_schedule_reload(self.entry.entry_id)
                return
            self._announce(device)
            await self.async_refresh_state(device)
        finally:
            self._describing.discard(device.device_id)

    async def _async_fetch_descriptors(self, device: NdDevice) -> dict[str, dict[str, Any]] | None:
        frame = build_frame(device.device_id, "/*", proto=PROTO_DESCRIPTION, seed=new_seed())

        def accept(f: Frame) -> bool:
            return f.proto == PROTO_DESCRIPTION and f.path != "/*"

        frames: list[Frame] = []
        if device.ip:
            try:
                frames = await self._transport.async_tcp_request(
                    device.device_id, device.ip, frame, device.nac, accept
                )
            except (OSError, TimeoutError) as err:
                _LOGGER.debug("TCP describe of %s failed: %s", device.device_id, err)
        descriptors = self._descriptors_from(frames)
        complete = device.nac > 0 and len(descriptors) >= device.nac

        if not complete:
            # Fallback: o mesmo pedido por UDP; as respostas vêm pelo multicast.
            collector: list[Frame] = []
            self._collectors[device.device_id] = collector
            try:
                await self._send(frame, device.ip)
                deadline = time.monotonic() + UDP_DESCRIBE_WINDOW_S
                while time.monotonic() < deadline:
                    await asyncio.sleep(0.25)
                    if device.nac and len(self._descriptors_from(collector)) >= device.nac:
                        break
            finally:
                self._collectors.pop(device.device_id, None)
            descriptors.update(self._descriptors_from([f for f in collector if accept(f)]))
            complete = device.nac > 0 and len(descriptors) >= device.nac

        if not descriptors:
            return None
        if complete:
            self._describe_cache[device.describe_key] = descriptors
        return descriptors

    @staticmethod
    def _descriptors_from(frames: list[Frame]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for frame in frames:
            if frame.path == "/*":
                continue
            descriptor = parse_descriptor(frame.query)
            if descriptor is not None and descriptor.get("path") == frame.path:
                out[frame.path] = descriptor
        return out

    # ── estado e comandos ────────────────────────────────────────────────────

    async def async_refresh_state(self, device: NdDevice) -> None:
        """Lê o estado: query vazia devolve todas as cargas da rota."""
        if device.caps is None:
            return
        for path in device.caps.state_paths:
            await self._send(
                build_frame(device.device_id, path, seed=new_seed()), device.ip, multicast=False
            )

    async def async_command(
        self,
        device: NdDevice,
        path: str,
        params: dict[str, str],
        expect: dict[str, str] | None,
    ) -> None:
        """Envia e só retorna quando a resposta do equipamento confirmar.

        As retransmissões usam o MESMO frame (mesmo seed): se a primeira cópia
        chegou e só a resposta se perdeu, o firmware descarta a repetida e a
        ação não é executada duas vezes. Os valores enviados são sempre
        explícitos (`on`/`off`), nunca `toggle`.
        """
        frame = build_frame(device.device_id, path, params, seed=new_seed())
        loop = asyncio.get_running_loop()
        for attempt in range(1, COMMAND_ATTEMPTS + 1):
            waiter = _Waiter(device.device_id, path, expect, loop.create_future())
            self._waiters.append(waiter)
            try:
                # 1ª tentativa só por unicast: a cópia multicast seria mais um
                # frame para TODOS os equipamentos processarem. As seguintes
                # vão pelos dois caminhos, caso o IP tenha mudado.
                await self._send(frame, device.ip, multicast=attempt > 1)
                await asyncio.wait_for(waiter.future, COMMAND_TIMEOUT_S)
                return
            except TimeoutError:
                _LOGGER.debug(
                    "No confirmation from %s for %s (attempt %d)", device.device_id, path, attempt
                )
            finally:
                self._waiters.remove(waiter)
        # Sem confirmação: não presume sucesso. Relê o estado para a tela
        # mostrar o que o equipamento realmente fez.
        self._spawn(self.async_refresh_state(device))
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_not_confirmed",
            translation_placeholders={"device": device.name},
        )

    async def _send(self, frame: str, ip: str | None = None, *, multicast: bool = True) -> None:
        try:
            await self._transport.async_send(frame, ip, multicast=multicast)
        except OSError as err:
            _LOGGER.debug("Send failed: %s", err)

    # ── tarefas periódicas ───────────────────────────────────────────────────

    async def _discovery_tick(self, _now: Any = None) -> None:
        await self.async_discover()
        for device in self.devices.values():
            if device.caps is None:
                self._maybe_describe(device)

    async def _availability_tick(self, _now: Any = None) -> None:
        now = time.monotonic()
        for device in self.devices.values():
            idle = now - device.last_seen
            if device.available and idle > OFFLINE_AFTER_S:
                _LOGGER.info("%s %s is offline", device.model, device.device_id)
                device.available = False
                self._notify(device)
            elif device.ip and idle > OFFLINE_AFTER_S / 2:
                # Rede que perde multicast: pergunta direto ao último IP.
                await self._send(
                    build_frame(device.device_id, "/if/device", seed=new_seed()), device.ip
                )

    async def _reconcile_tick(self, _now: Any = None) -> None:
        for device in self.devices.values():
            if device.available:
                await self.async_refresh_state(device)
