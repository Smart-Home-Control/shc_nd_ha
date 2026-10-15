# Testes

## Automatizados

`pytest`: 41 testes, sem rede. Os equipamentos são simulados a partir dos frames
capturados na bancada.

| Arquivo | Cobre |
|---|---|
| `tests/test_protocol.py` | gramática do frame, codificação, frames reais, recusa de lixo e de frame grande, describe real do 72B0, persiana, keypad |
| `tests/test_init.py` | descoberta só de NDv2; estado físico → HA; comando confirmado; comando perdido reenviado com o mesmo seed (sem executar duas vezes); comando sem confirmação → erro + releitura; eventos de botão com deduplicação; troca de IP; offline e recuperação com releitura; restart com entidades restauradas do cache; fallback UDP da describe; persiana; ID desconhecido sondado; **nenhuma escrita de configuração, nenhum `toggle`, nenhum `_to`** |
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
