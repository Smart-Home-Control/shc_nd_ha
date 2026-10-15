"""Frame ND: `$ID>path@proto?query<seed#`.

Puro: sem rede, sem Home Assistant. Monta o que sai e valida o que chega.
Tudo que vem da rede é tratado como entrada não confiável: o frame só é aceito
se casar com a gramática, couber no tamanho e tiver um ID de 4 hex.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import secrets
from urllib.parse import quote, unquote

from .const import MAX_FRAME_LEN, MAX_STATE_FRAME_LEN

PROTO_SET_DATA = 0
PROTO_DESCRIPTION = 9

_FRAME_RE = re.compile(
    r"^\$(?P<id>[0-9A-Fa-f]{4})>(?P<path>[^@#\s]*)@(?P<proto>\d)\?"
    r"(?P<query>[^#]*)<(?P<seed>\d{1,10})#$"
)
_PATH_RE = re.compile(r"^(/[A-Za-z0-9]+)+$|^/\*$")
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$")


@dataclass(frozen=True, slots=True)
class Frame:
    """Um frame ND já validado."""

    device_id: str
    path: str
    proto: int
    query: str
    seed: int
    params: dict[str, str] = field(default_factory=dict)

    @property
    def code(self) -> str | None:
        """Resultado da operação (`code=`), quando o frame o traz."""
        return self.params.get("code")

    @property
    def ok(self) -> bool:
        """Primeiro dígito `1` = sucesso; `0` = recusado, vazio ou fim de lista."""
        code = self.code
        return code is not None and code.startswith("1")


class FrameError(ValueError):
    """Frame fora da gramática ou de um tamanho plausível."""


def new_seed() -> int:
    """Seed aleatório de 32 bits; nunca 0 (0 desliga a deduplicação do firmware)."""
    return secrets.randbelow(0xFFFFFFFF) + 1


def build_frame(
    device_id: str,
    path: str,
    params: dict[str, str] | None = None,
    *,
    proto: int = PROTO_SET_DATA,
    seed: int,
) -> str:
    """Monta um frame. Valores são codificados: `&`, `#` e `<` não quebram o frame."""
    if not re.fullmatch(r"[0-9A-F]{4}", device_id):
        raise FrameError(f"invalid device id {device_id!r}")
    if not _PATH_RE.match(path):
        raise FrameError(f"invalid path {path!r}")
    if proto not in (0, 1, 6, 8, 9):
        raise FrameError(f"invalid protocol {proto}")
    if not 0 < seed <= 0xFFFFFFFF:
        raise FrameError("invalid seed")
    parts = []
    for key, value in (params or {}).items():
        if not _KEY_RE.match(key):
            raise FrameError(f"invalid param {key!r}")
        parts.append(f"{key}={quote(str(value), safe='')}")
    return f"${device_id}>{path}@{proto}?{'&'.join(parts)}<{seed}#"


def parse_frame(raw: str) -> Frame:
    """Valida e desmonta um frame recebido."""
    raw = raw.strip()
    if len(raw) > MAX_FRAME_LEN:
        raise FrameError("frame too long")
    match = _FRAME_RE.match(raw)
    if match is None:
        raise FrameError("malformed frame")
    proto = int(match["proto"])
    path = match["path"]
    query = match["query"]
    if not _PATH_RE.match(path):
        raise FrameError("invalid path")
    if proto != PROTO_DESCRIPTION and len(raw) > MAX_STATE_FRAME_LEN:
        raise FrameError("state frame too long")
    # A describe leva JSON (com espaço) na query; os demais não.
    if proto != PROTO_DESCRIPTION and any(c in query for c in " \t\r\n<>$"):
        raise FrameError("invalid characters in query")
    params = parse_query(query) if proto != PROTO_DESCRIPTION else {}
    return Frame(
        device_id=match["id"].upper(),
        path=path,
        proto=proto,
        query=query,
        seed=int(match["seed"]),
        params=params,
    )


def parse_query(query: str) -> dict[str, str]:
    """`a=1&b=x%20y` → `{"a": "1", "b": "x y"}`. Chave fora do formato é descartada."""
    out: dict[str, str] = {}
    if not query:
        return out
    for pair in query.split("&"):
        key, sep, value = pair.partition("=")
        if not sep or not _KEY_RE.match(key):
            continue
        out[key] = unquote(value)
    return out


def split_stream(buffer: str) -> tuple[list[str], str]:
    """Separa frames completos (`$…#`) de um fluxo TCP; devolve o resto pendente.

    O TCP do ND não tem delimitador de linha nem prefixo de tamanho: o frame vai
    do `$` ao primeiro `#`; o firmware nunca emite `#` no conteúdo, porque
    fecharia o frame.
    """
    frames: list[str] = []
    while True:
        start = buffer.find("$")
        if start < 0:
            return frames, ""
        end = buffer.find("#", start)
        if end < 0:
            rest = buffer[start:]
            # Lixo sem fim: não deixa o buffer crescer sem limite.
            return frames, rest if len(rest) <= MAX_FRAME_LEN else ""
        frames.append(buffer[start : end + 1])
        buffer = buffer[end + 1 :]


def is_on(value: str | None) -> bool | None:
    """Valor booleano do firmware; `None` quando não é liga/desliga."""
    if value is None:
        return None
    if value in ("on", "ON", "1", "true"):
        return True
    if value in ("off", "OFF", "0", "false"):
        return False
    return None
