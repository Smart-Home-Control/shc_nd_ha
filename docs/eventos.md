# Eventos de botão

Cada botão físico vira uma entidade `event` (device class `button`):
- um por `/cs/btN` declarado na descrição do equipamento;
- nos keypads, cada tecla;
- no MRQ10, cada uma das 10 entradas.

## De onde vem

O firmware já publica cada gesto no multicast, sem configuração nenhuma.
Exemplos capturados na bancada em 15/10/2026:

```
$73B4>/ac/bt@0?code=0&s=PRE&b=0&t=0<2841000#   pressionou
$73B4>/ac/bt@0?code=0&s=CL&b=0&t=0<57000#      clique
$73B4>/ac/bt@0?code=0&s=HO&b=0&t=0<2149000#    começou a segurar (~1 s)
$73B4>/ac/bt@0?code=0&s=HD&b=0&t=2<3942000#    segurando (repete a cada ~1 s)
$73B4>/ac/bt@0?code=0&s=RE&b=0&t=4<3597000#    soltou depois de segurar
```

A integração só escuta:
- não registra o HA no equipamento;
- não grava nada em flash;
- não muda o protocolo.

## Tipos de evento

| Firmware (`s`) | `event_type` no HA | Quando |
|---|---|---|
| `PRE` | `press` | o dedo encostou (vem antes de `click` ou `hold`) |
| `CL` | `click` | clique curto |
| `HO` | `hold` | passou de ~1 s pressionado |
| `HD` | `holding` | continua pressionado; repete a cada ~1 s |
| `RE` | `release` | soltou depois de segurar |

Sequências típicas:
- **Clique:** `press` → `click`.
- **Pressionamento longo:** `press` → `hold` → `holding` × N → `release`.

Para "aumentar enquanto segura", use `holding`. Para "segurou", use `hold` ou
`release` (que traz a duração).

## Atributos

| Atributo | Conteúdo |
|---|---|
| `event_type` | um dos tipos acima |
| `button` | índice do botão no firmware (0 = primeiro) |
| `duration` | `t` do firmware: segundos segurando (`holding`, `release`); 0 no clique |

## Evento no barramento

Além da entidade, cada gesto dispara `shc_nd_button`, útil em automações
escritas em YAML:

```yaml
triggers:
  - trigger: event
    event_type: shc_nd_button
    event_data:
      nd_id: "73B4"
      button: 0
      gesture: click
```

| Campo | Conteúdo |
|---|---|
| `device_id` | id do dispositivo no registro do HA |
| `nd_id` | ID do equipamento no protocolo ND (4 hex) |
| `button` | índice do botão |
| `gesture` | `press`, `click`, `hold`, `holding` ou `release` |
| `duration` | segundos (`t`) |

## Entrega

- O multicast UDP não garante entrega.
- Cada evento chega com várias cópias, e a integração descarta as repetidas
  pelo seed (janela de 5 s).
- Se todas as cópias de um gesto se perderem, a automação daquele gesto não
  dispara. Isso é raro numa LAN saudável.
- **O botão continua executando a cena gravada nele de qualquer forma:** a
  automação do HA é um acréscimo, não um substituto.
