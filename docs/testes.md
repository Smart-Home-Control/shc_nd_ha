# Testes

## Automatizados

`pytest`: 48 testes, sem rede. Os equipamentos são simulados a partir dos frames
capturados na bancada.

| Arquivo | Cobre |
|---|---|
| `tests/test_protocol.py` | gramática do frame, codificação, frames reais, recusa de lixo e de frame grande, describe real do 72B0, persiana, keypad |
| `tests/test_init.py` | descoberta só de NDv2; estado físico → HA; comando confirmado; comando perdido reenviado com o mesmo seed (sem executar duas vezes); comando sem confirmação → erro + releitura; eventos de botão com deduplicação; troca de IP; offline e recuperação com releitura; restart com entidades restauradas do cache; fallback UDP da describe; persiana; ID desconhecido sondado; **nenhuma escrita de configuração, nenhum `toggle`, nenhum `_to`** |
| `tests/test_transport.py` | espaçamento por destino, multicast contando para todos, unicast na 1ª tentativa, espera de silêncio na rede com teto |
| `tests/test_config_flow.py` | fluxo de configuração, interface inválida, porta ocupada, instância única, opções |

## Validado na bancada (15/10/2026, rede real)

- Descoberta: o MRQ10 72B0 (3.3.0, NDV2) foi encontrado. O MRQ10 E4FB
  (2.4.25) e o keypad 73B4 (2.4.28) foram ignorados por serem da geração
  antiga.
- Describe do 72B0 por TCP: 27 de 27 descritores. Resultado: 10 relés e 10
  botões (`/cs/bt0..9`).
- Leitura de estado: `code=1001&r0=off&…&r9=off`.
- Home Assistant 2026.2.3 real: 10 `light` e 10 `event` criados sozinhos.
  Depois do restart, as entidades voltam do cache, sem nova leitura da
  descrição.
- Gestos de keypad capturados no 73B4 (PRE/CL/HO/HD/RE). O Vitor confirmou
  que o NDv2 envia o mesmo.
- **HA → equipamento:** relé ligado pelo HA, executado e confirmado em 62 ms.
- **Equipamento → HA:** relé ligado por outro cliente; o HA atualizou na hora.
- **Botão → automação:** os frames `/ac/bt` reais (clique, e depois segurar)
  foram publicados no multicast da rede, porque o 72B0 da bancada não tem
  botão físico. As automações "clique alterna relé 3" e "`hold` liga relé 4"
  dispararam e o equipamento mudou de verdade.
- **Defeito achado e corrigido na bancada:** depois do primeiro comando, toda
  1ª tentativa ficava sem resposta (1,6 s por comando). Causa: o equipamento
  perde frames com menos de ~150 ms entre si. Correção: ritmo de envio
  descrito em `docs/protocolo.md`. Depois dela, 0 retransmissões em 10
  comandos, numa cena de 4 relés e em 5 cliques seguidos.
- HA e equipamento conferidos relé a relé: idênticos.

## Roteiro de bancada (aceite)

Equipamentos: um MRQ10 NDv2, um keypad NDv2 e, quando houver firmware, um dimmer.

1. [ ] **Descoberta:** instalar, adicionar a integração e ver os equipamentos
   aparecerem sem cadastro.
2. [ ] **Entidades:** MRQ10 com 10 luzes e 10 botões; keypad com um `event`
   por tecla; nada para equipamentos 2.4.x.
3. [ ] **HA → equipamento:** ligar e desligar um relé pelo HA. O relé atua e o
   estado bate.
4. [ ] **Equipamento → HA:** acionar o mesmo relé pelo keypad ou pela entrada.
   O HA atualiza em menos de 1 s.
5. [ ] **Automação:** criar uma automação com `event_type: click` num botão do
   keypad e conferir que dispara. Repetir com `hold`.
6. [ ] **Restart do HA:** os estados voltam corretos em poucos segundos.
7. [ ] **Restart do equipamento:** desligar e religar o MRQ10. Fica
   indisponível depois de ~3 min e volta sozinho com o estado relido.
8. [ ] **Troca de IP:** forçar outro IP no DHCP. O mesmo dispositivo continua,
   sem duplicar.
9. [ ] **Perda de pacote / rede:** desligar o Wi-Fi do equipamento por 30 s e
   mudar um relé fisicamente nesse tempo. Ao voltar, o HA corrige o estado.
10. [ ] **Sem alteração indevida:** comparar `/if/checkers` antes e depois do
    roteiro. Os hashes de `/lb` e `/cs` precisam ser os mesmos.
11. [ ] **Independência:** desligar o HA e a internet. Keypads e cenas
    continuam funcionando.
12. [ ] **Studio ao mesmo tempo:** com o HA rodando, usar o Studio para ler e
    gravar configuração. Não pode haver conflito de TCP.
13. [ ] **Regressão de firmware:** não se aplica. A integração não muda o
    firmware; `docs/protecao_modelos.md` do repositório de firmware continua
    valendo sem alteração.

## Para quem vai testar em campo

1. Instale pelo ZIP. Siga o `README.md`: extraia em
   `config/custom_components/shc_nd/`, reinicie e adicione **SHC NDv2**.
2. Para o teste, ligue o log detalhado em `configuration.yaml` e reinicie:
   ```yaml
   logger:
     default: warning
     logs:
       custom_components.shc_nd: debug
   ```
3. Siga o roteiro acima. Para o keypad:
   - crie uma automação com o `event` de um botão (gatilho "estado", condição
     `event_type` = `click`);
   - aperte o botão físico;
   - repita com `hold`.
4. Mande de volta:
   - **diagnóstico:** Configurações → Dispositivos e serviços → SHC NDv2 → ⋮ →
     *Baixar diagnóstico*. Mostra o que foi descoberto, as capacidades e o
     estado;
   - o trecho do log com `custom_components.shc_nd`. As linhas `RX …` são os
     frames recebidos; `No confirmation` indica comando que precisou de
     retransmissão;
   - modelo e versão de firmware dos equipamentos que **não** apareceram.
