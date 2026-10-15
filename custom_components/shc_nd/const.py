"""Constantes da integração SHC NDv2."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "shc_nd"

MULTICAST_GROUP: Final = "239.5.0.2"
UDP_PORT: Final = 5202
TCP_PORT: Final = 5203

# Endereço "todos" do protocolo ND: cada equipamento responde com o próprio ID.
BROADCAST_ID: Final = "0000"

# Só a geração NDv2 (firmware 3.x) é suportada. Equipamentos 2.4.x respondem
# `type=RELE`, `type=ND` ou `type=PERSIANA` e são ignorados.
SUPPORTED_TYPE: Final = "NDV2"

CONF_INTERFACE: Final = "interface"
CONF_RECONCILE_MINUTES: Final = "reconcile_minutes"
DEFAULT_INTERFACE: Final = "0.0.0.0"
DEFAULT_RECONCILE_MINUTES: Final = 5

# Descoberta em baixa frequência: um `$0000>/if/device` por minuto. Cada
# equipamento responde com poucas cópias; é o mesmo pedido que o Studio usa
# como keepalive.
DISCOVERY_INTERVAL_S: Final = 60
# Sem nenhum frame com `code` vindo do equipamento nesse tempo, ele fica
# indisponível (mesma janela de 3 min do Studio).
OFFLINE_AFTER_S: Final = 180
# Não sondar o mesmo ID desconhecido mais de uma vez nesse intervalo.
PROBE_COOLDOWN_S: Final = 30

# Confirmação de comando: espera a resposta de estado por tentativa, reenviando
# o MESMO frame (mesmo seed: o firmware descarta o repetido).
COMMAND_ATTEMPTS: Final = 3
COMMAND_TIMEOUT_S: Final = 1.5
# Envios UDP espaçados: equipamento de baixo consumo perde pacote em rajada.
UDP_SPACING_S: Final = 0.05

# Describe por TCP: conecta, pede `/*@9`, lê até `nAC` descritores ou silêncio,
# fecha. O servidor TCP do equipamento atende um cliente por vez.
TCP_CONNECT_TIMEOUT_S: Final = 5.0
TCP_IDLE_TIMEOUT_S: Final = 2.5
TCP_TOTAL_TIMEOUT_S: Final = 20.0
# Fallback por UDP (multicast): descritores grandes podem truncar, mas os que a
# integração usa são pequenos.
UDP_DESCRIBE_WINDOW_S: Final = 6.0

# Janela de deduplicação: cada resposta chega várias vezes (multicast + unicast).
DEDUP_TTL_S: Final = 5.0

MAX_FRAME_LEN: Final = 4096
MAX_STATE_FRAME_LEN: Final = 1024

STORAGE_VERSION: Final = 1

SIGNAL_DEVICE_READY: Final = "shc_nd_device_ready_{entry_id}"
SIGNAL_DEVICE_UPDATE: Final = "shc_nd_device_update_{entry_id}_{device_id}"
SIGNAL_BUTTON: Final = "shc_nd_button_{entry_id}_{device_id}"

# Evento no barramento do HA, além da EventEntity.
EVENT_BUTTON: Final = "shc_nd_button"

# Gesto do firmware (`s` em /ac/bt) → tipo de evento no HA.
GESTURES: Final[dict[str, str]] = {
    "PRE": "press",
    "CL": "click",
    "HO": "hold",
    "HD": "holding",
    "RE": "release",
}

MANUFACTURER: Final = "Smart Home Control"
