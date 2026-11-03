# steam-price-forecast

Previsão de preço de itens do Mercado da Comunidade Steam (skins e caixas de CS2, itens de Dota 2 e outros). A pergunta: **onde o preço de um item pode estar daqui a 7 e 30 dias?** A resposta é um **intervalo** (P10, P50, P90), e o projeto mede se esse intervalo ganha de "o preço de amanhã é o de hoje".

> **Estado:** coleta do histórico, séries diárias e baselines em janela deslizante prontos. Os modelos de ML ainda não existem e **não há resultado publicado**. Isto não é recomendação financeira.

## Como funciona

1. **Universo:** lista os itens mais negociados de um jogo pelo `search/render`, que é público.
2. **Coleta:** baixa o histórico de preço de cada item pelo `pricehistory`, que **exige uma sessão logada**. Um arquivo por item em `data/raw/`; rodar de novo retoma de onde parou.
3. **Série diária:** o histórico vem diário nos dias antigos e por hora nos últimos 30. O preço do dia é a média ponderada pelo volume; dias sem venda repetem o último preço; o último dia, incompleto, é descartado.
4. **Avaliação:** para cada item, a cada 7 dias (a "origem"), cada modelo prevê os quantis da variação do log do preço em `h` dias usando **só o que existia até a origem**. Depois compara com o que aconteceu.

| Baseline | O que faz |
|---|---|
| naive (pontual) | O preço em `t+h` é o de `t`. Sem intervalo. |
| naive + erro empírico | Mesma mediana, intervalo a partir das variações de `h` dias já vistas no próprio item. **A régua do intervalo.** |
| média móvel 30d + erro empírico | Aposta que o preço volta à média dos últimos 30 dias, com o intervalo do erro dessa regra. |

Métricas: erro absoluto da mediana, perda de quantil (pinball) média sobre P10, P50 e P90, e cobertura do intervalo P10 a P90 (o esperado é perto de 80%). As origens a cada 7 dias com horizonte de 30 se sobrepõem, então as médias vêm de dados correlacionados: não trate a diferença entre modelos como estatisticamente independente.

## Dados e o cookie

- O dado bruto da Steam **não é versionado nem redistribuído** (`data/` está no `.gitignore`). O repositório publica código e métricas agregadas.
- O `pricehistory` precisa do cookie da sua própria sessão. Copie `.env.example` para `.env`, preencha **você mesmo** e rode `chmod 600 .env`. O `.env` fica fora do git. O código lê só `STEAM_LOGIN_SECURE` e `STEAM_SESSIONID`, nunca imprime o valor e não o repete em mensagem de erro.
- **Copie o cookie de `steamcommunity.com`, não de `store.steampowered.com`.** O `steamLoginSecure` é um token por domínio. Em 03/11/2026 um token da loja (audiência `web:store`) recebeu `400` com `[]` no `pricehistory` e a página do mercado não o reconheceu como logado. O `coletar` lê só `aud` e `exp` do token e avisa antes de chamar a Steam.
- Acesso automatizado ao Mercado pode contrariar os termos da Steam, e o IP pode ser bloqueado por um tempo. A Steam não documenta o limite de requisições; o padrão aqui é 1 chamada a cada 5 s (12 por minuto). Com `429`, o coletor espera 5, 15 e 30 minutos e, se persistir, para e guarda o progresso.
- O cliente se identifica com um User-Agent próprio. Nos testes de 03/11/2026 o `search/render` respondeu `429` a um User-Agent de navegador e `200` a este e ao do `curl`, com o mesmo intervalo entre pedidos. O `pricehistory` aceitou o User-Agent próprio (5 itens, a 1 chamada a cada 5 s, sem `429`).
- O formato do `pricehistory` (data `"Nov 01 2013 01: +0"`, preço em número, volume em texto) foi escrito a partir de relatos de terceiros e confirmado em 03/11/2026 com 5 itens: um ponto por dia nos dias antigos e 24 por dia nos últimos 30. É uma API não documentada, então o parser **falha alto** se a Steam mudar.
- O preço vem na moeda da carteira da conta (o prefixo, como `R$`, é guardado junto).

## Uso

```bash
uv sync --extra dev
uv run pytest

# 1. itens mais negociados (público, sem cookie)
uv run steam-forecast universo --appid 730 --quantidade 300

# 2. histórico de preço (usa o .env). Comece pequeno.
uv run steam-forecast coletar --max-itens 5
uv run steam-forecast coletar            # retoma e baixa o resto

# 3. baselines em janela deslizante
uv run steam-forecast avaliar --horizonte 7 --horizonte 30
```

Rode a partir da raiz do projeto (o `.env` e o `data/` são caminhos relativos). `appid` 730 é CS2, 570 é Dota 2 e 440 é TF2.

## Limites conhecidos

- Preço de mercado se comporta quase como passeio aleatório. Se um modelo não ganhar do **naive + erro empírico**, este README dirá isso.
- Itens com pouco histórico ou poucas vendas por dia ficam fora da avaliação (`--min-dias`, `--min-vendas`): o preço deles é ruído de um ou dois negócios.
- Eventos que movem preço de verdade (caixa que sai do pool de drops, operações, Majors, promoções da Steam, mudanças de regra de troca) ainda não entram como variável.

## Licença

MIT. Os dados da Steam pertencem à Valve e a quem negocia os itens; este projeto não é afiliado à Valve.
