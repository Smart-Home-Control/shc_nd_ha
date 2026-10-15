# Como a integração usa o protocolo ND

Frame: `$ID>path@proto?query<seed#`.

| Parte | Significado |
|---|---|
| `ID` | 4 hex do equipamento; `0000` = todos |
| `proto` | `0` = ler/escrever; `9` = descrição |
| `query` vazia | leitura |
| `seed` | número aleatório; o firmware descarta um seed que já processou |

## Descoberta

1. **Ativa.** Na inicialização e a cada 60 s, `$0000>/if/device@0?<seed#` vai
   para o multicast 239.5.0.2:5202. Cada equipamento responde com modelo,
   versão, tipo e `nAC` (quantidade de ações na descrição):
   ```
   $72B0>/if/device@0?code=1001&model=MRQ10&deviceName=MRQ10-72B0&version=3.3.0&serialNumber=000&type=NDV2&id=72B0&date=Aug%2028%202026&nAC=27<2006106#
   ```
2. **Passiva.** Um frame com `code` vindo de um ID ainda desconhecido (por
   exemplo, a resposta a um comando do Studio) dispara na hora um
   `$ID>/if/device` para aquele ID.
3. **Só NDv2.** Quem responde `type` diferente de `NDV2` é ignorado e não
   recebe nenhum frame endereçado a ele.

**Identidade:**
- A chave é o **ID** do equipamento. O `unique_id` de cada entidade é
  `<ID>_<rota>_<carga>`, por exemplo `72B0_ac_rs_r0`.
- O IP é só um atributo, atualizado a cada resposta de `/if/device`. A troca
  de IP por DHCP não duplica nada.

## Descrição (capacidades)

- `$ID>/*@9?<seed#` por **TCP 5203**: conecta, envia, lê até `nAC` descritores
  ou 2,5 s de silêncio, e fecha.
- Se o TCP falhar (outro cliente conectado, por exemplo), o mesmo pedido vai
  por UDP e as respostas chegam pelo multicast.
- O resultado fica em cache por **modelo + versão + nAC**: a descrição é fixa
  por firmware.
- Um firmware novo (outra versão) faz a integração ler de novo e recriar as
  entidades.

| Descritor | Entidades |
|---|---|
| `/ac/rs` (`r0..rN`, Boolean) | `light` |
| `/ac/pers` (`on0..onN`) | `cover`; os relés não viram luz |
| `/cs/btN`, ou `/ac/bt` | `event` por botão |

## Estado

| Quando | Como |
|---|---|
| **Tempo real** | Toda mudança, física ou não, é publicada pelo equipamento no multicast com `code=1…` e o estado de todas as cargas. A entidade atualiza na hora. |
| **Leitura** | Query vazia: `$72B0>/ac/rs@0?<seed#` devolve `code=1001&r0=off&…&r9=off`. |
| **Ao iniciar** | Depois da descrição, lê o estado de cada equipamento. |
| **Quando um equipamento volta** | Depois de ficar offline ou reiniciar, lê o estado de novo. Isso cobre pacotes perdidos e mudanças feitas enquanto ele estava fora. |
| **Reconciliação** | A cada N minutos (padrão 5, configurável de 1 a 60), lê o estado dos equipamentos disponíveis. É uma leitura por equipamento; não é polling contínuo. |

- Frames **sem `code`** não são estado: são a "intenção" de outro controlador,
  como a cena de um keypad (`$E4FB>/ac/rs@0?r0=on<1585002#`). A integração
  espera a resposta do equipamento alvo.
- Cada resposta chega várias vezes (multicast + unicast). A deduplicação é por
  ID + seed + conteúdo, numa janela de 5 s.

## Comandos e confirmação

1. O frame vai por UDP **unicast** para o IP conhecido e pelo **multicast**,
   com o mesmo seed.
2. Comando do HA só é dado como feito quando a **resposta de estado do
   equipamento** confirma o valor pedido. Timeout de 1,5 s por tentativa, até
   3 tentativas.
3. As retransmissões repetem **o mesmo frame com o mesmo seed**. Se o comando
   chegou e só a resposta se perdeu, o firmware descarta a cópia e a ação não
   acontece duas vezes.
4. Sem confirmação depois das 3 tentativas, o serviço retorna erro e a
   integração relê o estado. A tela mostra o que o equipamento realmente fez,
   nunca o que se presumiu.

**Idempotência:**
- **Luz:** sempre `on`/`off` explícito, **nunca `toggle`**. Repetir é inofensivo.
- **Persiana:**
  - Subir é `onN=on`; descer é `onN=off`.
  - Parar é o comando contrário ao sentido atual. Com a persiana já parada,
    nada é enviado.
  - Como o mesmo valor pode significar "parar" ou "inverter", a proteção contra
    repetição é o seed fixo.

## Disponibilidade

- O equipamento fica **indisponível** quando passa 3 min sem enviar nenhum
  frame com `code`.
- Depois de 90 s sem notícias, a integração pergunta direto ao último IP
  conhecido (`/if/device` unicast), para o caso de a rede perder multicast.
- Ao voltar, o equipamento fica disponível e o estado é relido.

## TCP: um cliente por vez

O servidor TCP do equipamento atende **um cliente por vez**. Por isso:
- a integração usa TCP **só para a descrição**, uma vez por modelo e versão;
- é sempre conectar, enviar, ler e fechar;
- há no máximo uma conexão nossa por equipamento;
- nunca fica conexão aberta que bloqueie o Studio.

Estado, comandos e eventos andam por UDP.

## Segurança

**O que a integração faz:**
- **Valida tudo o que chega**:
  - gramática do frame;
  - ID de 4 hex;
  - tamanho: até 4096 bytes na descrição e 1024 nos demais;
  - sem espaço ou caractere de controle fora da descrição;
  - chave de parâmetro alfanumérica;
  - faixa numérica do botão e da duração;
  - `id` do `/if/device` igual ao do cabeçalho.
- **Nunca altera configuração.** Os únicos frames enviados são:
  - `/if/device` (leitura);
  - `/*@9` (descrição);
  - leitura de `/ac/rs` e `/ac/pers`;
  - escrita de `rN`/`onN` em `/ac/rs` e `/ac/pers`, só por ação explícita do
    usuário ou de uma automação.

  Nenhum `/lb/*`, `/cs/*`, `/cf/*` ou `/aa/*` é enviado. Isso é coberto por
  teste automatizado.
- **Não usa `_to`.** Em firmwares 3.0.x, o `_to` fazia o equipamento abrir TCP
  de volta e causava travamentos.
- **Tudo é local.** Nenhum serviço externo, nenhuma biblioteca extra
  (`requirements: []`). TTL multicast 1: os frames não saem da sub-rede.

**Limitações do protocolo NDv2** (não resolvidas pela integração):
- **Sem autenticação nem criptografia.** O seed é anti-repetição, não
  assinatura. Qualquer máquina na mesma rede pode comandar os equipamentos e
  forjar estados ou eventos de botão.
- A integração não piora isso, mas também não protege. **Mitigação:** manter
  os equipamentos numa VLAN de automação sem acesso de convidados.
- **O ID tem só 4 hex** (fim do MAC). Dois equipamentos com o mesmo ID na
  mesma rede seriam confundidos. O próprio barramento ND já não funciona nesse
  caso.
- **Multicast não garante entrega.** A reconciliação periódica e a releitura
  ao voltar corrigem estados perdidos. Um evento de botão perdido não é
  recuperável.
- **Persiana sem posição.** O firmware só informa o sentido do motor, então a
  entidade não sabe se está aberta ou fechada.
