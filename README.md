# SHC NDv2 para Home Assistant

Integração **100% local** entre o Home Assistant e os equipamentos Smart Home
Control com firmware **NDv2 (3.x)**: módulos de relé (MRQ10), persianas e
keypads. Sem nuvem, sem MQTT e sem servidor intermediário. O Home Assistant
conversa com os equipamentos pelo mesmo protocolo ND que eles já usam entre si.

- Os equipamentos **aparecem sozinhos**: nenhum cadastro manual.
- Ligar uma luz pelo HA ou pelo keypad mostra o **mesmo estado** nos dois lados.
- Cada botão de keypad (e cada entrada do MRQ10) vira um **gatilho de automação**:
  clique, pressionou, segurou, segurando e soltou.
- Os equipamentos continuam funcionando normalmente sem internet e com o Home
  Assistant desligado. A integração só escuta e comanda; ela não altera a
  configuração deles.

## O que vira entidade

| No equipamento | No Home Assistant |
|---|---|
| Relé (`/ac/rs`, `r0..r9`) | `light` liga/desliga |
| Persiana (`/ac/pers`, firmware no modo persiana) | `cover` com subir, descer e parar (sem posição) |
| Botão com cena (`/cs/btN`) | `event` com `click`, `press`, `hold`, `holding` e `release` |

As entidades nascem da descrição que o próprio firmware publica (`/*@9`), sem
tabela por modelo. Só aparece o que o firmware realmente suporta. Relés usados
por persiana não viram luz.

**Fora do escopo desta versão:**
- Equipamentos da geração antiga (firmware 2.4.x: `type=RELE`, `ND` ou
  `PERSIANA`). São ignorados.
- Dimmer: nenhum firmware NDv2 conhecido publica uma rota de dimmer.

## Requisitos

- Home Assistant **2025.1 ou mais novo**.
- Home Assistant e equipamentos **na mesma rede local** (mesma sub-rede/VLAN),
  com multicast liberado:
  - UDP **5202**, unicast e multicast para o grupo **239.5.0.2** (estado,
    comandos e eventos);
  - TCP **5203**, saindo do HA para o equipamento (só para ler a descrição,
    uma vez por modelo e versão).
- **Docker:** o contêiner precisa de `network_mode: host`. Com rede em ponte,
  o multicast não chega.
- **Wi-Fi com "isolamento de clientes" ou IGMP snooping mal configurado**
  impede o multicast. Nesse caso os equipamentos não são descobertos.
- **Firewall do host** (Linux com `ufw`/`firewalld`): libere a entrada UDP 5202.

## Instalação

A distribuição é só pelo arquivo ZIP (não há HACS).

1. Baixe o `shc_nd.zip` da página de releases, ou gere com `scripts/build_zip.sh`.
2. Extraia em `<config>/custom_components/shc_nd/`, onde `<config>` é a pasta
   que tem o `configuration.yaml`. A pasta `shc_nd` precisa conter
   `manifest.json` diretamente. Dá para copiar pelo add-on **Samba share** ou
   **File editor**, ou por SSH.
3. Reinicie o Home Assistant.
4. **Configurações → Dispositivos e serviços → Adicionar integração → SHC NDv2**.

### Configuração

A tela pede só o **IP da interface de rede**:
- Deixe `0.0.0.0` para usar a interface padrão.
- Em máquinas com mais de uma rede, informe o IP da interface que está na rede
  dos equipamentos.

A integração faz uma descoberta na hora e mostra quantos equipamentos NDv2
responderam. Os demais entram sozinhos quando aparecerem.

Em **Configurar** há uma única opção: o intervalo da conferência de estado
(padrão 5 min). Veja [`docs/protocolo.md`](docs/protocolo.md).

## Atualização

Baixe o ZIP da versão nova, substitua o conteúdo de
`custom_components/shc_nd/` e reinicie.

As entidades são preservadas: o identificador de cada uma é o ID do equipamento
mais a carga, e não muda entre versões.

## Remoção

1. **Configurações → Dispositivos e serviços → SHC NDv2 → ⋮ → Excluir.**
2. Apague a pasta `custom_components/shc_nd/`.
3. Reinicie.

Nada é gravado nos equipamentos, então não há o que desfazer neles.

## Automação com botão

```yaml
automation:
  - alias: "Keypad sala, botão 1: cena cinema"
    triggers:
      - trigger: state
        entity_id: event.keypadwifi_ca00_botao_1
    conditions:
      - condition: state
        entity_id: event.keypadwifi_ca00_botao_1
        attribute: event_type
        state: click
    actions:
      - action: scene.turn_on
        target:
          entity_id: scene.cinema
```

O formato completo dos eventos está em [`docs/eventos.md`](docs/eventos.md).

## Versões compatíveis

| Integração | Home Assistant | Firmware |
|---|---|---|
| 0.1.x | 2025.1+ (testada em 2026.2.3) | NDv2 3.x; validada no MRQ10 3.3.0 |

## Documentação

- [`docs/eventos.md`](docs/eventos.md): formato dos eventos de botão.
- [`docs/protocolo.md`](docs/protocolo.md): como a integração usa o protocolo
  ND, confiabilidade, segurança e limitações.
- [`docs/testes.md`](docs/testes.md): testes automatizados e roteiro de bancada.

## Desenvolvimento

```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```
