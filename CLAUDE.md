# shc_nd_ha

## Documentação técnica (fonte única)

A documentação técnica desta integração (descoberta, comandos, entidades, armadilhas, instalação e testes) fica no
espaço técnico do painel do manual:
https://docs-novo.smarthomecontrol.com.br/painel/tecnica/busca-integracoes/home-assistant/ (depois da virada do DNS,
https://docs.smarthomecontrol.com.br/painel/tecnica/busca-integracoes/home-assistant/). Não recrie documentos técnicos
neste repositório. Mudou um comportamento (protocolo, ritmo de envio, entidades, testes), atualize a página pelo MCP
`shc-docs` com `espaco: "tecnica"`, citando arquivo e commit. `README.md` e `docs/eventos.md` são de quem usa a
integração e continuam aqui.

| Assunto | Página do painel |
|---|---|
| Visão geral | https://docs-novo.smarthomecontrol.com.br/painel/tecnica/busca-integracoes/home-assistant/ |
| Descoberta (ativa/passiva, identidade, descrição por TCP/UDP, cache) | https://docs-novo.smarthomecontrol.com.br/painel/tecnica/busca-integracoes/home-assistant/descoberta/ |
| Comandos (tentativas, ritmo de envio, idempotência) | https://docs-novo.smarthomecontrol.com.br/painel/tecnica/busca-integracoes/home-assistant/comandos/ |
| Entidades e eventos (gestos, atributos, disponibilidade) | https://docs-novo.smarthomecontrol.com.br/painel/tecnica/busca-integracoes/home-assistant/entidades/ |
| Armadilhas e limitações do NDv2 | https://docs-novo.smarthomecontrol.com.br/painel/tecnica/busca-integracoes/home-assistant/armadilhas/ |
| Instalação, roteiro de aceite na bancada e teste em campo | https://docs-novo.smarthomecontrol.com.br/painel/tecnica/busca-integracoes/home-assistant/instalacao/ |

Tarefa que muda como algo funciona só vai para QA com a página técnica atualizada no painel (MCP `shc-docs`,
`atualizar_pagina` com `espaco: "tecnica"`, ou pedido à sessão do manual) e o link da página num comentário do card.
Não crie documento técnico novo neste repositório.
