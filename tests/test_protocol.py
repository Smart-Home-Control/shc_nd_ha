"""Frame ND e describe: puros, com frames reais da bancada."""

from __future__ import annotations

import pytest

from custom_components.shc_nd.describe import capabilities, parse_descriptor
from custom_components.shc_nd.protocol import (
    FrameError,
    build_frame,
    is_on,
    new_seed,
    parse_frame,
    split_stream,
)

from .sim import BT_DESCRIPTOR, LB_DEVICE, cs_descriptor, pers_descriptor, rs_descriptor

# Capturados no PacketSender em 15/10/2026.
REAL_STATE = "$E4FB>/ac/rs@0?code=11110&r0=on&r1=on&r2=on&r3=on&r4=on&r5=on&r6=on&r7=on&r8=on&r9=on<2001000#"
REAL_BUTTON = "$73B4>/ac/bt@0?code=0&s=CL&b=0&t=0<57000#"
REAL_INFO = "$72B0>/if/device@0?code=1001&model=MRQ10&deviceName=MRQ10-72B0&version=3.3.0&serialNumber=000&type=NDV2&id=72B0&date=Aug%2028%202026&nAC=27<2006106#"
REAL_DISCOVERY = "$0000>/if/device@0?n<0#"


def test_parse_real_frames() -> None:
    state = parse_frame(REAL_STATE)
    assert state.device_id == "E4FB"
    assert state.path == "/ac/rs"
    assert state.ok
    assert state.params["r9"] == "on"
    assert state.seed == 2001000

    button = parse_frame(REAL_BUTTON)
    assert button.params == {"code": "0", "s": "CL", "b": "0", "t": "0"}
    assert not button.ok

    info = parse_frame(REAL_INFO)
    assert info.params["type"] == "NDV2"
    assert info.params["date"] == "Aug 28 2026"
    assert info.params["nAC"] == "27"

    assert parse_frame(REAL_DISCOVERY).device_id == "0000"


def test_build_frame_encodes_values() -> None:
    assert build_frame("72B0", "/ac/rs", {"r0": "on"}, seed=123) == "$72B0>/ac/rs@0?r0=on<123#"
    assert build_frame("72B0", "/ac/rs", seed=5) == "$72B0>/ac/rs@0?<5#"
    assert build_frame("72B0", "/*", proto=9, seed=5) == "$72B0>/*@9?<5#"
    # Nada que o usuário digite consegue fechar o frame ou injetar parâmetro.
    frame = build_frame("72B0", "/ac/rs", {"r0": "on&r1=on#<"}, seed=1)
    assert parse_frame(frame).params == {"r0": "on&r1=on#<"}


@pytest.mark.parametrize(
    ("device_id", "path", "params"),
    [
        ("72b0", "/ac/rs", {}),
        ("72B0", "/ac/../lb", {}),
        ("72B0", "/ac/rs#", {}),
        ("72B0", "/ac/rs", {"r 0": "on"}),
    ],
)
def test_build_frame_rejects(device_id: str, path: str, params: dict[str, str]) -> None:
    with pytest.raises(FrameError):
        build_frame(device_id, path, params, seed=1)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "garbage",
        "$72B0>/ac/rs@0?r0=on#",  # sem seed
        "$72B0X>/ac/rs@0?r0=on<1#",  # id inválido
        "$72B0>/ac/rs@0?r0=o n<1#",  # espaço fora da describe
        "$72B0>/ac/rs@0?" + "r0=on&" * 400 + "<1#",  # grande demais
        "$72B0>/ac/rs@7?r0=on<1#".replace("@7", "@x"),
    ],
)
def test_parse_rejects_garbage(raw: str) -> None:
    with pytest.raises(FrameError):
        parse_frame(raw)


def test_split_stream() -> None:
    frames, rest = split_stream("lixo$A>1#$B>2#$C>")
    assert frames == ["$A>1#", "$B>2#"]
    assert rest == "$C>"
    frames, rest = split_stream("x" * 10)
    assert frames == [] and rest == ""


def test_seed_is_never_zero() -> None:
    assert all(0 < new_seed() <= 0xFFFFFFFF for _ in range(1000))


def test_is_on() -> None:
    assert is_on("on") is True
    assert is_on("off") is False
    assert is_on("toggle") is None
    assert is_on(None) is None


def test_capabilities_mrq10() -> None:
    caps = capabilities({"/ac/rs": rs_descriptor(), "/lb/device": LB_DEVICE})
    assert caps.relays == list(range(10))
    assert caps.covers == [] and caps.buttons == []
    assert caps.state_paths == ["/ac/rs"]


# Rotas da describe real do MRQ10 72B0 (fw 3.3.0), lida por TCP em 15/10/2026.
REAL_72B0_PATHS = [
    "/aa/delay", "/aa/tcp", "/aa/udp", "/aa/wol", "/ac/ping", "/ac/rs", "/ac/status",
    "/cl/WifiScan", "/cl/actions", *[f"/cs/bt{i}" for i in range(10)], "/if/checkers",
    "/if/crashlog", "/if/device", "/if/wifi", "/lb/buttons", "/lb/device", "/lb/leds", "/lb/wifi",
]


def test_capabilities_real_72b0() -> None:
    descriptors = {p: {"name": p, "path": p, "params": []} for p in REAL_72B0_PATHS}
    descriptors["/ac/rs"] = rs_descriptor()
    assert len(descriptors) == 27
    caps = capabilities(descriptors)
    assert caps.relays == list(range(10))
    assert caps.buttons == list(range(10))
    assert caps.button_events
    assert caps.covers == []


def test_capabilities_blinds_take_the_relays() -> None:
    caps = capabilities({"/ac/rs": rs_descriptor(), "/ac/pers": pers_descriptor()})
    assert caps.covers == list(range(5))
    assert caps.relays == []


def test_capabilities_keypad() -> None:
    descriptors = {"/ac/bt": BT_DESCRIPTOR} | {f"/cs/bt{i}": cs_descriptor(i) for i in range(8)}
    caps = capabilities(descriptors)
    assert caps.button_events
    assert caps.buttons == list(range(8))


def test_capabilities_legacy_array_and_friendly_name() -> None:
    rs = rs_descriptor(2)
    rs["params"][0]["friendlyName"] = "Sala"
    caps = capabilities({"/ac/rs": rs})
    assert caps.friendly_names == {"/ac/rs:r0": "Sala"}
    array = {"name": "rs", "path": "/ac/rs", "params": [{"name": "r", "type": "Array[4]:Boolean"}]}
    assert capabilities({"/ac/rs": array}).relays == [0, 1, 2, 3]


def test_parse_descriptor_raw_encoded_and_trailing() -> None:
    raw = '{"name":"rs","path":"/ac/rs","params":[]}'
    assert parse_descriptor(raw)["path"] == "/ac/rs"
    assert parse_descriptor("%7B%22path%22%3A%22%2Fac%2Frs%22%7D")["path"] == "/ac/rs"
    assert parse_descriptor(raw + "&_ts=123")["path"] == "/ac/rs"
    assert parse_descriptor("not json") is None
