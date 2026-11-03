# Interface do Steam Forecast

Site estático, sem build e sem dependências JavaScript. A raiz publicável é esta pasta; não publique a raiz do repositório nem a pasta `data/`.

```bash
# Na raiz do projeto
python3 -m http.server 4173 --directory web --bind 127.0.0.1
```

Abra `http://127.0.0.1:4173`. É necessário servir por HTTP, porque `app.js` importa `demo.js` como módulo.

## O que é público

`index.html`, `styles.css`, `app.js`, `demo.js` e `favicon.svg`. Os oito jogos da demonstração usam nomes e capas da Steam, mas **todos os preços, históricos e previsões são sintéticos**. As imagens são carregadas do CDN da Steam, com fallback visual se falharem; as fontes são carregadas do Google Fonts, com alternativas do sistema.

O site não faz requisições à API do ITAD, não contém chaves e não executa a CLI. O terminal é uma animação explicativa acionada pelo visitante; inclui pausar, continuar e reiniciar e respeita redução de movimento.

## Catálogo local

Depois de gerar o catálogo com `uv run steam-forecast jogos-exportar`, use **Abrir dados locais** e selecione `data/jogos/catalogo-local.json`. O JSON é lido com a File API e mantido somente na memória da aba; não há upload, localStorage, cookie ou service worker. Recarregar a página ou restaurar a demonstração descarta o catálogo. As capas continuam sendo carregadas da Steam por appid; os preços e as previsões nunca são enviados junto.

O importador aceita `schema_version: 1`, `moeda: "BRL"` e de 1 a 5.000 jogos. Limite de arquivo: 64 MB. Exemplo de contrato, com valores fictícios:

```json
{
  "schema_version": 1,
  "modo": "local",
  "moeda": "BRL",
  "jogos": [{
    "appid": 413150,
    "titulo": "Stardew Valley",
    "preco_atual": 36,
    "preco_regular": 36,
    "desconto_atual": 0,
    "data_base": "2026-11-02",
    "historico": [
      {"data": "2026-11-01", "preco": 36, "regular": 36},
      {"data": "2026-11-02", "preco": 36, "regular": 36}
    ],
    "previsoes": {
      "30": {
        "probabilidade_desconto": 0.68,
        "preco_minimo_p10": 18,
        "preco_minimo_p50": 24,
        "preco_minimo_p90": 36,
        "data_base": "2026-11-02"
      }
    }
  }]
}
```

- Preços são fechamentos diários na data-base; não são cotações ao vivo.
- `preco` e `regular` podem ser `null` em dias de indisponibilidade; o gráfico interrompe a linha nesses trechos. `preco_atual` e `preco_regular` também podem ser `null`.
- `probabilidade_desconto` é a probabilidade de um preço **menor que o da data-base** nos próximos 30 ou 90 dias, de 0 a 1.
- Os quantis descrevem o **menor preço entre a data-base e o final do horizonte**, incluindo a opção de comprar na data-base. Não representam o preço exato no fim do período nem uma trajetória futura.
- A mediana fica entre P10 e P90; os valores não devem exceder o preço na data-base. Sem previsão válida, o site mostra explicitamente a ausência e conserva o histórico.
- A data-base de cada previsão deve coincidir com a data-base do jogo e a última data do histórico. O preço e o preço cheio na data-base devem coincidir com os valores desse último dia. Inconsistências são rejeitadas.
- Histórico deve estar em ordem crescente, sem datas repetidas, com até 10.000 dias por jogo. A interface mostra os últimos 180 dias e uma tabela das mudanças.

A importação valida o contrato e coloca títulos e valores no DOM como texto. Um erro de arquivo preserva o catálogo que já estava aberto.

## Verificação rápida

```bash
node --check web/app.js
node --check web/demo.js
node --test web/test-contract.mjs
```

No navegador: buscar um nome, buscar algo inexistente, limpar a busca, filtrar por preço, trocar jogo e horizonte, conferir tabela do histórico, abrir um JSON local e um inválido, restaurar a demonstração e executar/pausar/reiniciar o terminal. Verificar também navegação por teclado e largura de 390 px.
