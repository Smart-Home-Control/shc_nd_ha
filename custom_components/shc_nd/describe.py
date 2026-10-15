"""Describe (`/*@9`) → o que o equipamento sabe fazer.

Puro. As entidades nascem do que o firmware declara, sem tabela por modelo: um
modelo novo com `/ac/rs` vira luz sem mudar a integração. A describe é fixa
por modelo + versão, por isso é guardada em cache com essa chave.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any
from urllib.parse import unquote

_RELAY_RE = re.compile(r"^r(\d{1,2})$")
_COVER_RE = re.compile(r"^on(\d{1,2})$")
_BUTTON_PATH_RE = re.compile(r"^/cs/bt(\d{1,2})$")
_ARRAY_RE = re.compile(r"^Array\[(\d{1,2})\]:Boolean$")

PATH_RELAYS = "/ac/rs"
PATH_COVERS = "/ac/pers"
PATH_BUTTON_EVENT = "/ac/bt"


def parse_descriptor(query: str) -> dict[str, Any] | None:
    """O JSON do descritor, cru ou URL-encoded, com lixo depois do `}` ignorado."""
    for text in (query, _safe_unquote(query)):
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            continue
        try:
            obj = json.loads(text[start : end + 1])
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("path"), str):
            return obj
    return None


def _safe_unquote(text: str) -> str:
    try:
        return unquote(text)
    except ValueError:
        return text


@dataclass(slots=True)
class Capabilities:
    """O recorte da describe que vira entidade."""

    relays: list[int] = field(default_factory=list)
    covers: list[int] = field(default_factory=list)
    buttons: list[int] = field(default_factory=list)
    button_events: bool = False
    friendly_names: dict[str, str] = field(default_factory=dict)

    @property
    def state_paths(self) -> list[str]:
        """Rotas cujo estado a integração consulta (query vazia = leitura)."""
        paths = []
        if self.relays:
            paths.append(PATH_RELAYS)
        if self.covers:
            paths.append(PATH_COVERS)
        return paths


def capabilities(descriptors: dict[str, dict[str, Any]]) -> Capabilities:
    """Deriva as capacidades a partir dos descritores, indexados por path."""
    caps = Capabilities()

    covers = descriptors.get(PATH_COVERS)
    if covers:
        for param in _params(covers):
            if (m := _COVER_RE.match(param.get("name", ""))) and param.get("type") == "Boolean":
                caps.covers.append(int(m[1]))
                _friendly(caps, PATH_COVERS, param)

    relays = descriptors.get(PATH_RELAYS)
    # Relé de persiana não vira luz: quando o firmware declara `/ac/pers`, os
    # relés são usados aos pares pelo motor (não há modo misto).
    if relays and not caps.covers:
        for param in _params(relays):
            name = param.get("name", "")
            ptype = param.get("type", "")
            if (m := _RELAY_RE.match(name)) and ptype == "Boolean":
                caps.relays.append(int(m[1]))
                _friendly(caps, PATH_RELAYS, param)
            elif name == "r" and (m := _ARRAY_RE.match(ptype)):
                caps.relays.extend(range(int(m[1])))

    for path in descriptors:
        if m := _BUTTON_PATH_RE.match(path):
            caps.buttons.append(int(m[1]))
    # Firmware 3.x publica `/ac/bt` para cada botão com cena (`/cs/btN`),
    # inclusive nas entradas do MRQ10, mesmo sem descrever `/ac/bt` (o 72B0
    # 3.3.0 real não descreve). Basta um dos dois.
    caps.button_events = PATH_BUTTON_EVENT in descriptors or bool(caps.buttons)
    # Keypad que publica /ac/bt mas não descreve /cs/btN: usa o máximo de `b`.
    if caps.button_events and not caps.buttons:
        caps.buttons = list(range(_button_count(descriptors[PATH_BUTTON_EVENT])))

    caps.relays = sorted(set(caps.relays))
    caps.covers = sorted(set(caps.covers))
    caps.buttons = sorted(set(caps.buttons))
    return caps


def _params(descriptor: dict[str, Any]) -> list[dict[str, Any]]:
    params = descriptor.get("params")
    if not isinstance(params, list):
        return []
    return [p for p in params if isinstance(p, dict)]


def _friendly(caps: Capabilities, path: str, param: dict[str, Any]) -> None:
    name = param.get("friendlyName")
    if isinstance(name, str) and 0 < len(name) <= 64:
        caps.friendly_names[f"{path}:{param['name']}"] = name


def _button_count(descriptor: dict[str, Any]) -> int:
    for param in descriptor.get("paramsResponse") or []:
        if isinstance(param, dict) and param.get("name") == "b":
            for constraint in param.get("params") or []:
                if isinstance(constraint, str) and constraint.startswith("$max="):
                    try:
                        return max(0, min(int(constraint[5:]), 32))
                    except ValueError:
                        return 0
    return 0
