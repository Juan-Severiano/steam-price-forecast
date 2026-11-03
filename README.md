# steam-price-forecast

Laboratório de previsão de preços de **jogos da loja Steam**, em reais. A pergunta: **qual a chance de encontrar um preço menor se eu esperar 30 ou 90 dias?** O projeto compara regras simples com gradient boosting e estima P10, P50 e P90 do menor preço nesse período.

> **Estado em 03/11/2026:** coleta dos 1.160 jogos concluída; séries diárias, baselines, classificação e quantis medidos em avaliação temporal ([resultados](#resultados-dos-jogos-em-03112026)). Interface estática em `web/`, com exemplos sintéticos e importação de catálogo local. A [demonstração no GitHub Pages](https://juan-severiano.github.io/steam-price-forecast/) usa somente dados sintéticos; o catálogo real pode ser aberto localmente na interface. O módulo anterior de **itens do mercado** permanece separado, com resultados em 232 itens do CS2; seus resultados não são resultados de jogos.

## Uso

```bash
uv sync --extra dev --extra ml
uv run pytest

# Grave ITAD_API_KEY em .env (fora do git), conforme .env.example.
uv run steam-forecast jogos-universo
uv run steam-forecast jogos-coletar
uv run steam-forecast jogos-status

# Mesmas origens para todos os modelos; padrão: horizontes 30 e 90 dias.
uv run steam-forecast jogos-avaliar

# Arquivo privado em data/jogos/catalogo-local.json.
uv run steam-forecast jogos-exportar

# Apenas a interface demonstrativa é servida.
python3 -m http.server 4173 --bind 127.0.0.1 --directory web
```

Abra `http://127.0.0.1:4173` e use **Abrir dados locais** para selecionar `data/jogos/catalogo-local.json`. O navegador lê esse arquivo em memória, sem enviá-lo a um servidor e sem guardar os preços no armazenamento do navegador. Recarregar volta à demonstração. As capas dos jogos e fontes usam serviços externos; os preços locais não são enviados a eles.

A busca, seleção de jogo, filtro de preço, horizontes de 30/90 dias e gráfico funcionam na demonstração e no catálogo importado. O terminal animado é uma **simulação**, não executa Python nem chamadas à API. A interface informa a data-base: o valor real é o fechamento do último dia completo do cache, não uma cotação ao vivo.

## Modelo dos jogos

- **Série:** último preço conhecido no fechamento de cada dia UTC, até o dia anterior à coleta de cada arquivo. Não antecipa eventos nem prolonga um cache antigo até hoje. Retirada da loja permanece como ausência de preço até a próxima oferta.
- **Alvos:** chance de preço estritamente menor que o da origem em `h` dias; quantis do menor fechamento entre a origem e `origem + h`, incluindo a opção de comprar na origem. Isso difere de prever o preço no último dia ou simplesmente qualquer promoção.
- **Atributos:** calendário, idade do histórico, preço/regular, desconto, tempo desde mudança/desconto e frequência, profundidade e mínimos retrospectivos de 30/90/365 dias.
- **ML:** um `HistGradientBoostingClassifier` e três `HistGradientBoostingRegressor` de quantis. Treino determinístico, sem parada antecipada aleatória; quantis ordenados e limitados entre zero e o preço na origem.
- **Avaliação:** origens semanais, pelo menos 365 dias de histórico, teste desde 2023 e retreino a cada 180 dias. Todos os modelos usam as mesmas origens e apenas alvos já completos no início da dobra. Os atributos de cada origem usam só o que era conhecido naquela data.
- **Baselines:** manter o preço; taxa geral histórica; frequência do próprio jogo; mesma época do ano anterior (±15 dias, com fallback para a frequência do jogo). Os baselines também são congelados no início da dobra.
- **Métricas:** Brier e log loss para a chance; pinball, erro da mediana e cobertura para os quantis. Menor Brier/pinball é melhor. Pinball é medido na razão entre o menor preço e o preço da origem, permitindo comparar jogos de preços diferentes.

Resultados completos ficam em `data/jogos/resultados-modelo.json`, com configuração, cortes de treino/teste e recortes por ano/jogo. O arquivo é local; métricas agregadas podem ser documentadas aqui. O comando retorna erro se não houver origens elegíveis.

### Resultados dos jogos em 03/11/2026

Coleta concluída: **1.160/1.160 arquivos íntegros**, quatro históricos sem eventos e **1.156 séries**. Dados até o fechamento de 02/11/2026. Horizonte de 30 dias: **1.086 jogos e 198.212 origens**; de 90 dias: **1.081 jogos e 188.819 origens**. São oito cortes de treino/teste por horizonte, desde 2023, com a configuração padrão descrita acima.

| Horizonte | Modelo | Brier | Pinball | Cobertura P10–P90 | MAE do menor preço |
|---|---|---:|---:|---:|---:|
| 30 dias | frequência do jogo | 0,2367 | 0,0777 | 84,8% | R$ 18,52 |
| 30 dias | gradient boosting | 0,1382 | 0,0506 | 88,1% | R$ 11,86 |
| 90 dias | frequência do jogo | 0,1943 | 0,0710 | 82,3% | R$ 10,64 |
| 90 dias | gradient boosting | 0,0666 | 0,0290 | 84,8% | R$ 3,74 |

- **30 dias:** redução de **41,6% no Brier** e **34,8% no pinball** frente à frequência do jogo. Melhora nas duas métricas em cada um dos quatro anos avaliados.
- **90 dias:** redução de **65,7% no Brier** e **59,1% no pinball** frente à frequência do jogo. Melhora nas duas métricas em cada um dos quatro anos avaliados.

O ML também superou os demais baselines em Brier e pinball agregados nesta rodada. Isso é redução de perda no backtest, **não aumento equivalente de “taxa de acerto”**, nem prova de desempenho futuro. Não houve ajuste de hiperparâmetros sobre esse teste. A cobertura nominal é de 80%; a observada está na tabela, sem calibração posterior. O alvo inclui muitos casos em que esperar não reduz o preço, então a distribuição tem massa no preço atual. Médias por origem dão mais peso a jogos com mais datas elegíveis.

Limitações: universo escolhido pela popularidade atual (viés de sobrevivência), jogos e origens correlacionados, datas de promoções futuras não conhecidas, cobertura não garantida. Janelas futuras com indisponibilidade ficam fora dos rótulos: a avaliação é condicionada à disponibilidade contínua. Fechamentos diários podem perder promoções que começam e acabam no mesmo dia. A data do primeiro registro é idade do histórico, não necessariamente lançamento. A previsão não é recomendação de compra.

## Site e GitHub Pages

O site é HTML/CSS/JavaScript sem build ou backend. `web/demo.js` contém somente exemplos sintéticos; nunca carrega `.env` nem chama o ITAD. Os dados reais e previsões locais ficam em `data/`, ignorado pelo Git.

```bash
python3 scripts/preparar_site.py
```

Esse comando monta `_site/` com uma lista explícita de arquivos públicos. O workflow `.github/workflows/pages.yml` publica apenas esse pacote, em push na `main` que altere o site ou por execução manual. A origem do Pages é **GitHub Actions**; o endereço da demonstração é [juan-severiano.github.io/steam-price-forecast](https://juan-severiano.github.io/steam-price-forecast/). Não copie o catálogo local para `web/` ou para o pacote público.

## Como funciona o módulo de itens

O módulo secundário trata de skins e caixas do Mercado da Comunidade: onde o preço pode estar em 7/30 dias, em vez do menor preço de um jogo durante uma espera. Seus números abaixo são independentes do modelo de jogos.

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

## Uso dos itens

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

## Fonte e coleta dos jogos

O universo reúne 1.160 entradas do tipo `game` entre os populares/colecionados do IsThereAnyDeal com appid da Steam; pode incluir edições e servidores de teste classificados assim pela fonte. A coleta grava um JSON bruto por appid, com a data de aquisição, e retoma os arquivos pendentes.

O histórico vem da API do [IsThereAnyDeal](https://isthereanydeal.com), em reais. O cliente pede eventos desde 2005; a cobertura disponível varia por jogo e não comprova que todos tenham dados desde o lançamento. Preços fornecidos por IsThereAnyDeal; este projeto não é afiliado a eles. **Os dados reais não ficam no repositório nem na demonstração pública.** Consulte os [termos da API](https://docs.isthereanydeal.com/) antes de reutilizar ou publicar dados; a opção de importação é para explorar o catálogo pessoal localmente.

```bash
# 1. chave: registre um app em https://isthereanydeal.com/apps/my/ e grave ITAD_API_KEY no .env
# 2. jogos mais populares e mais colecionados do IsThereAnyDeal que existem na Steam
uv run steam-forecast jogos-universo
# 3. histórico de preço de cada jogo (cache em data/jogos/historico/, retoma de onde parou)
uv run steam-forecast jogos-coletar --max-jogos 20
```

Em `429`, o coletor respeita `Retry-After` (segundos, inclusive zero, ou data HTTP), acrescenta 1 s de folga e registra a espera imediatamente. Sem cabeçalho válido, usa 30/120/300 s; ao esgotar tentativas, salva o progresso e encerra com erro. Em 03/11 houve uma espera real de 247 s pedida pelo ITAD, seguida de retomada: poucas chamadas bem-sucedidas não descartam limitação em rodadas maiores. Falhas isoladas também produzem código de saída 1. `jogos-status --detalhes` confere identidade e integridade e lista o que falta; um arquivo com histórico vazio é coleta concluída, mas não vira série de treino.

## Limites conhecidos

- Preço de mercado se comporta quase como passeio aleatório. Se um modelo não ganhar do **naive + erro empírico**, este README dirá isso.
- Itens com pouco histórico ou poucas vendas por dia ficam fora da avaliação (`--min-dias`, `--min-vendas`): o preço deles é ruído de um ou dois negócios.
- Eventos que movem preço de verdade (caixa que sai do pool de drops, operações, Majors, promoções da Steam, mudanças de regra de troca) ainda não entram como variável.

## Licença

MIT. Os dados da Steam pertencem à Valve e a quem negocia os itens; este projeto não é afiliado à Valve.
