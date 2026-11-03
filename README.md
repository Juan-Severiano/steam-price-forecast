# steam-price-forecast

Previsão de preço de itens do Mercado da Comunidade Steam (skins e caixas de CS2, itens de Dota 2 e outros). A pergunta: **onde o preço de um item pode estar daqui a 7 e 30 dias?** A resposta é um **intervalo** (P10, P50, P90), e o projeto mede se esse intervalo ganha de "o preço de amanhã é o de hoje".

> **Estado:** duas frentes. **Itens do mercado:** coleta, baselines e um modelo de gradient boosting com quantis, medidos em 232 itens do CS2 ([baselines](#resultados-dos-baselines), [modelo](#modelo-de-ml-dos-itens)). **Jogos da loja** (preço de jogo, como o Stardew Valley): universo e coleta do histórico prontos, [modelo ainda não](#jogos-da-loja-em-andamento). Isto não é recomendação financeira.

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

## Resultados dos baselines

Medidos em 03/11/2026 sobre os 300 itens mais negociados do CS2 naquele dia. A lista tem 284 nomes distintos, porque o ranking da Steam muda entre uma página e outra; pelo nome, cerca de 224 são skins de arma, 32 caixas, 20 cápsulas, 14 adesivos, 8 souvenirs e 2 itens selados. Passaram no filtro (pelo menos 500 dias de histórico e 3 vendas por dia) **232 itens**. As origens são a cada 7 dias, com pelo menos 365 dias de histórico antes. Preços em R$.

**Horizonte 7 dias** - 232 itens, 59.911 origens

| Modelo | MAE da mediana | Pinball | vs naive+erro | Cobertura P10-P90 | Largura |
|---|---|---|---|---|---|
| naive (pontual) | 0,0630 | 0,0315 | +43,1% | - | - |
| **naive + erro empírico** | 0,0633 | **0,0220** | referência | 80,0% | 0,194 |
| média móvel 30d + erro empírico | 0,0921 | 0,0311 | +41,4% | 78,9% | 0,292 |

**Horizonte 30 dias** - 232 itens, 59.192 origens

| Modelo | MAE da mediana | Pinball | vs naive+erro | Cobertura P10-P90 | Largura |
|---|---|---|---|---|---|
| naive (pontual) | 0,1246 | 0,0623 | +44,5% | - | - |
| **naive + erro empírico** | 0,1279 | **0,0431** | referência | 77,9% | 0,399 |
| média móvel 30d + erro empírico | 0,1504 | 0,0503 | +16,7% | 75,2% | 0,467 |

Como ler:

- Pinball menor é melhor. Na mediana, o naive pontual e o naive com intervalo empatam (0,0630 e 0,0633 em 7 dias); o que o intervalo acrescenta é a cobertura. O P10 a P90 cobre 80,0% a 7 dias e 77,9% a 30 (o nominal é 80%), então o de 30 dias fica um pouco estreito.
- A largura é em log: 0,194 a 7 dias é um topo cerca de 21% acima do piso do intervalo; 0,399 a 30 dias, cerca de 49%.
- A média móvel de 30 dias perde nos dois horizontes: apostar na volta à média não ajudou.
- **Isto é o piso que um modelo de ML precisa vencer, não resultado de ML.** As origens se sobrepõem, a média simples pesa mais os itens de histórico longo, os itens se movem juntos (não são 232 amostras independentes) e é um único dia de coleta num único regime de mercado.
- O dado bruto não está no repositório. Para reproduzir, rode os comandos acima; a lista de popularidade muda, então os números vão variar.

## Modelo de ML dos itens

Gradient boosting com perda de quantil (`HistGradientBoostingRegressor`, extra `ml`: `uv sync --extra ml`), três modelos por horizonte (P10, P50, P90). Atributos do dia de origem: retornos de 1 a 180 dias, volatilidade, volume, posição na faixa de 365 dias, idade do item e calendário; a variante "item + mercado" soma o retorno médio dos itens no mesmo dia. O alvo é padronizado pela volatilidade de 90 dias e cada linha pesa a escala, o que iguala a perda de treino à medida em unidades originais. O modelo é retreinado a cada 90 dias só com linhas cujo alvo já era conhecido, e prevê as mesmas origens dos baselines (teste de 01/01/2023 em diante, 16 dobras). Um teste de vazamento confere que mexer nos dados depois de uma dobra não muda as previsões dela.

| Horizonte | Modelo | Pinball | vs referência | Cobertura P10-P90 | Itens melhores |
|---|---|---|---|---|---|
| 7 dias (35.840 origens) | naive + erro empírico | 0,0210 | referência | 79,6% | - |
| 7 dias | GB só do item | 0,0199 | **-5,0%** | 76,3% | 81% |
| 7 dias | GB item + mercado | 0,0200 | -4,9% | 75,9% | 80% |
| 30 dias (35.121 origens) | naive + erro empírico | 0,0424 | referência | 76,7% | - |
| 30 dias | GB só do item | 0,0414 | -2,1% | 71,5% | 58% |
| 30 dias | GB item + mercado | 0,0416 | -1,8% | 69,7% | 58% |

- **A 7 dias o ganho é pequeno, mas robusto:** melhora em todos os anos, de -3,4% a -6,2%.
- **A 30 dias não há vantagem confiável:** por ano o resultado oscila (2023 pior em 1,2%, 2024 melhor em 8,9%, 2025 praticamente igual, 2026 melhor em 2,9%), e o ganho médio vem quase todo de 2024.
- **Os intervalos do modelo são estreitos demais** (70% a 76% de cobertura para 80% nominais). Calibrar (por exemplo, com CQR) é o próximo passo desse módulo.
- Os fatores de mercado não acrescentaram nada.
- Mesmas ressalvas dos baselines: origens sobrepostas, itens correlacionados, um único dia de coleta. O universo é o top 300 de hoje, então há viés de sobrevivência.

```bash
uv run steam-forecast modelo --saida data/resultados-modelo.json
```

## Jogos da loja (em andamento)

Segunda frente: prever o preço dos **jogos** da loja da Steam (o Stardew Valley, por exemplo), não dos itens. Preço de jogo anda em degraus, com liquidações sazonais, então a pergunta útil é "vale esperar?": chance de desconto nos próximos 30 e 90 dias e quanto se economiza esperando.

O histórico vem da API do [IsThereAnyDeal](https://isthereanydeal.com) (chave gratuita; mudanças de preço desde o lançamento, em reais). Preços fornecidos por IsThereAnyDeal; este projeto não é afiliado a eles. Uso pessoal: **o dado do IsThereAnyDeal não fica no repositório** (`data/` está no `.gitignore`), e os termos da API proíbem alterar os dados e concorrer com o serviço.

```bash
# 1. chave: registre um app em https://isthereanydeal.com/apps/my/ e grave ITAD_API_KEY no .env
# 2. jogos mais populares e mais colecionados do IsThereAnyDeal que existem na Steam
uv run steam-forecast jogos-universo
# 3. histórico de preço de cada jogo (cache em data/jogos/historico/, retoma de onde parou)
uv run steam-forecast jogos-coletar --max-jogos 20
```

**Ainda não existe** modelo nem resultado para jogos: só o universo (1.160 jogos), o cliente da API e a coleta, com testes. A coleta completa ainda está sendo estabilizada.

## Limites conhecidos

- Preço de mercado se comporta quase como passeio aleatório. Se um modelo não ganhar do **naive + erro empírico**, este README dirá isso.
- Itens com pouco histórico ou poucas vendas por dia ficam fora da avaliação (`--min-dias`, `--min-vendas`): o preço deles é ruído de um ou dois negócios.
- Eventos que movem preço de verdade (caixa que sai do pool de drops, operações, Majors, promoções da Steam, mudanças de regra de troca) ainda não entram como variável.

## Licença

MIT. Os dados da Steam pertencem à Valve e a quem negocia os itens; este projeto não é afiliado à Valve.
