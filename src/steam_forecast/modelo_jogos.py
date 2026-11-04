"""Chance de comprar mais barato e quantis do menor preço, com validação temporal.

O alvo é o menor fechamento diário entre hoje e t+h, dividido pelo preço de hoje.
Incluir hoje representa a opção de comprar agora; a razão está entre zero e um.
``probabilidade_desconto`` significa preço estritamente menor que o de hoje,
mesmo quando o jogo já está em promoção. Não é a chance de qualquer promoção.

O treino e todos os baselines são congelados no início de cada dobra, usando
apenas alvos cujo último dia já terminou. Nenhum preço posterior à origem entra
nos atributos. Janelas com indisponibilidade não recebem rótulo. A amostragem é
semanal por padrão; origens sobrepostas e jogos correlacionados não são amostras
independentes. Os resultados medem previsão, não significância estatística.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from steam_forecast.series_jogos import SerieJogo

EPOCA = date(1970, 1, 1)
QUANTIS = np.array([0.1, 0.5, 0.9])
ATUAL = "preço atual"
GERAL = "taxa geral histórica"
JOGO = "frequência do jogo"
SAZONAL = "mesma época do ano anterior"
# As quatro réguas acima ignoram se o jogo já está em promoção hoje; o ML sabe disso (desconto_atual).
# Estas duas sabem, para a comparação não premiar o ML só por enxergar o estado atual.
ESTADO = "taxa por estado"
JOGO_ESTADO = "frequência do jogo dado o estado"
MIN_ESTADO = 5  # linhas de treino do jogo naquele estado; abaixo disso vale a taxa geral do estado
ML = "gradient boosting"
NOMES = (
    "ano_seno", "ano_cosseno", "semana_seno", "semana_cosseno", "idade_dias",
    "log_preco", "preco_sobre_regular", "desconto_atual", "dias_desde_mudanca",
    "dias_desde_desconto", "retorno_30", "minimo_30", "frequencia_desconto_30",
    "desconto_medio_30", "disponibilidade_30", "retorno_90", "minimo_90",
    "frequencia_desconto_90", "desconto_medio_90", "disponibilidade_90",
    "retorno_365", "minimo_365", "frequencia_desconto_365", "desconto_medio_365",
    "disponibilidade_365",
)
COL_DESCONTO = NOMES.index("desconto_atual")


@dataclass(frozen=True)
class ConfiguracaoJogos:
    horizonte: int
    inicio_teste: int
    retreino: int = 180
    passo: int = 7
    iteracoes: int = 80
    min_historia: int = 365
    min_amostras: int = 30
    min_por_folha: int = 30

    def __post_init__(self) -> None:
        for nome in ("horizonte", "retreino", "passo", "iteracoes", "min_historia", "min_amostras", "min_por_folha"):
            valor = getattr(self, nome)
            if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
                raise ValueError(f"{nome} deve ser um inteiro positivo")


@dataclass(frozen=True, eq=False)
class PainelJogos:
    X: np.ndarray
    dia: np.ndarray
    item: np.ndarray
    preco: np.ndarray
    razao: np.ndarray
    baixou: np.ndarray


@dataclass(frozen=True, eq=False)
class PrevisoesJogos:
    cfg: ConfiguracaoJogos
    dia: np.ndarray
    item: np.ndarray
    preco: np.ndarray
    real: np.ndarray
    baixou: np.ndarray
    probabilidades: dict[str, np.ndarray]
    quantis: dict[str, np.ndarray]
    dobras: list[dict]


def _validar_serie(s: SerieJogo) -> None:
    n = len(s.dias)
    if any(len(v) != n for v in (s.preco, s.regular, s.desconto)):
        raise ValueError(f"appid {s.appid}: arrays com tamanhos diferentes")
    if n and (np.diff(s.dias) != 1).any():
        raise ValueError(f"appid {s.appid}: a série deve ter dias consecutivos")


def atributos_jogo(s: SerieJogo, posicoes: np.ndarray) -> np.ndarray:
    """Atributos somente até cada posição. NaN representa histórico indisponível."""
    _validar_serie(s)
    t = np.asarray(posicoes, dtype=int)
    if t.size == 0:
        return np.empty((0, len(NOMES)))
    if t.min() < 0 or t.max() >= len(s.dias):
        raise ValueError("posição fora da série")
    p = np.asarray(s.preco, dtype=float)
    regular = np.asarray(s.regular, dtype=float)
    corte = np.asarray(s.desconto, dtype=float)
    valido = np.isfinite(p) & (p >= 0)
    em_desconto = valido & np.isfinite(corte) & (corte > 0)
    ii = np.arange(p.size)
    mudou = np.r_[True, (p[1:] != p[:-1]) & (valido[1:] | valido[:-1])]
    ultima_mudanca = np.maximum.accumulate(np.where(mudou, ii, 0))
    ultimo_desconto = np.maximum.accumulate(np.where(em_desconto, ii, -1))
    datas = [EPOCA + timedelta(days=int(d)) for d in s.dias[t]]
    dia_ano = np.array([d.timetuple().tm_yday for d in datas])
    dia_semana = np.array([d.weekday() for d in datas])
    atual = p[t]
    atual_seguro = np.where(atual > 0, atual, np.nan)
    regular_seguro = np.where(regular[t] > 0, regular[t], np.nan)
    colunas = [
        np.sin(2 * np.pi * dia_ano / 365.25), np.cos(2 * np.pi * dia_ano / 365.25),
        np.sin(2 * np.pi * dia_semana / 7), np.cos(2 * np.pi * dia_semana / 7),
        t.astype(float), np.log1p(np.maximum(atual, 0)), atual / regular_seguro,
        corte[t] / 100, (t - ultima_mudanca[t]).astype(float),
        np.where(ultimo_desconto[t] >= 0, t - ultimo_desconto[t], np.nan),
    ]
    contagem = np.r_[0, np.cumsum(valido)]
    contagem_corte = np.r_[0, np.cumsum(valido & np.isfinite(corte))]
    promocao = np.r_[0, np.cumsum(em_desconto)]
    profundidade = np.r_[0.0, np.cumsum(np.where(valido & np.isfinite(corte), corte / 100, 0))]
    for janela in (30, 90, 365):
        inicio = np.maximum(0, t - janela + 1)
        qtd = contagem[t + 1] - contagem[inicio]
        qtd_corte = contagem_corte[t + 1] - contagem_corte[inicio]
        # Só há até janela * origens elementos temporários por jogo.
        offsets = np.arange(janela)
        indices = t[:, None] - offsets
        historico = p[np.maximum(indices, 0)]
        historico = np.where((indices >= 0) & np.isfinite(historico), historico, np.inf)
        minimo = historico.min(axis=1)
        minimo[~np.isfinite(minimo)] = np.nan
        anterior = p[np.maximum(0, t - janela)]
        retorno = np.divide(atual, anterior, out=np.full(t.size, np.nan), where=anterior > 0) - 1
        retorno[t < janela] = np.nan
        colunas.extend([
            retorno, minimo / atual_seguro,
            np.divide(promocao[t + 1] - promocao[inicio], qtd_corte, out=np.full(t.size, np.nan), where=qtd_corte > 0),
            np.divide(profundidade[t + 1] - profundidade[inicio], qtd_corte, out=np.full(t.size, np.nan), where=qtd_corte > 0),
            qtd / (t - inicio + 1),
        ])
    X = np.column_stack(colunas)
    X[~np.isfinite(X)] = np.nan
    return X


def montar_painel_jogos(series: Sequence[SerieJogo], cfg: ConfiguracaoJogos) -> PainelJogos:
    partes: list[tuple] = []
    h = cfg.horizonte
    for i, s in enumerate(series):
        _validar_serie(s)
        n = len(s.dias)
        if n < cfg.min_historia + h:
            continue
        t = np.arange(cfg.min_historia - 1, n - h, cfg.passo)
        p = np.asarray(s.preco, dtype=float)
        valido = np.isfinite(p) & (p >= 0)
        soma = np.r_[0, np.cumsum(valido)]
        ok = (p[t] > 0) & (soma[t + h + 1] - soma[t] == h + 1)
        t = t[ok]
        if not t.size:
            continue
        futuro = np.lib.stride_tricks.sliding_window_view(p, h + 1)
        menor = futuro[t].min(axis=1)
        razao = np.clip(menor / p[t], 0, 1)
        partes.append((atributos_jogo(s, t), s.dias[t], np.full(t.size, i), p[t], razao, menor < p[t] - 1e-8))
    if not partes:
        vazio = np.empty(0)
        return PainelJogos(np.empty((0, len(NOMES))), vazio.astype(int), vazio.astype(int), vazio, vazio, vazio)
    return PainelJogos(*(np.concatenate([p[j] for p in partes], axis=0) for j in range(6)))


def selecionar_treino_jogos(painel: PainelJogos, limite: int, horizonte: int) -> np.ndarray:
    return np.flatnonzero(painel.dia + horizonte <= limite)


def _ajustar_prever(X: np.ndarray, y: np.ndarray, razao: np.ndarray, teste: np.ndarray, cfg: ConfiguracaoJogos) -> tuple[np.ndarray, np.ndarray]:
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
        from threadpoolctl import threadpool_limits
    except ImportError as erro:
        raise ImportError("o modelo dos jogos precisa de scikit-learn: uv sync --extra ml") from erro
    parametros = dict(
        learning_rate=0.06, max_iter=cfg.iteracoes, max_leaf_nodes=15,
        min_samples_leaf=cfg.min_por_folha, l2_regularization=1.0,
        early_stopping=False, random_state=0,
    )
    with threadpool_limits(limits=2):
        if np.unique(y).size == 1:
            prob = np.full(teste.shape[0], float(y[0]))
        else:
            classificador = HistGradientBoostingClassifier(**parametros).fit(X, y)
            prob = classificador.predict_proba(teste)[:, 1]
        if np.ptp(razao) < 1e-12:
            quantis = np.full((teste.shape[0], 3), razao[0])
        else:
            quantis = np.column_stack([
                HistGradientBoostingRegressor(loss="quantile", quantile=float(q), **parametros)
                .fit(X, razao).predict(teste) for q in QUANTIS
            ])
    return np.clip(prob, 0, 1), np.sort(np.clip(quantis, 0, 1), axis=1)


def _empirico(p: PainelJogos, linhas: np.ndarray) -> tuple[float, np.ndarray]:
    return float(p.baixou[linhas].mean()), np.quantile(p.razao[linhas], QUANTIS)


def _baselines(p: PainelJogos, treino: np.ndarray, teste: np.ndarray) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    n = teste.size
    media, quantil = _empirico(p, treino)
    probs = {ATUAL: np.zeros(n), GERAL: np.full(n, media), JOGO: np.full(n, media), SAZONAL: np.full(n, media)}
    qs = {ATUAL: np.ones((n, 3)), GERAL: np.tile(quantil, (n, 1)), JOGO: np.tile(quantil, (n, 1)), SAZONAL: np.tile(quantil, (n, 1))}
    # Réguas que conhecem o estado: o mesmo cálculo, separado entre "já em promoção" e "preço cheio".
    em_treino, em_teste = p.X[treino, COL_DESCONTO] > 0, p.X[teste, COL_DESCONTO] > 0
    por_estado = {}
    for estado in (True, False):
        linhas = treino[em_treino == estado]
        por_estado[estado] = _empirico(p, linhas) if linhas.size else (media, quantil)
    probs[ESTADO] = np.where(em_teste, por_estado[True][0], por_estado[False][0])
    qs[ESTADO] = np.where(em_teste[:, None], por_estado[True][1], por_estado[False][1])
    probs[JOGO_ESTADO], qs[JOGO_ESTADO] = probs[ESTADO].copy(), qs[ESTADO].copy()
    for item in np.unique(p.item[teste]):
        no_teste = np.flatnonzero(p.item[teste] == item)
        historico = treino[p.item[treino] == item]
        if not historico.size:
            continue
        prob, q = _empirico(p, historico)
        probs[JOGO][no_teste] = prob
        probs[SAZONAL][no_teste] = prob
        qs[JOGO][no_teste] = q
        qs[SAZONAL][no_teste] = q
        em_historico = p.X[historico, COL_DESCONTO] > 0
        for estado in (True, False):
            do_estado = historico[em_historico == estado]
            alvo = no_teste[em_teste[no_teste] == estado]
            if do_estado.size >= MIN_ESTADO and alvo.size:
                probs[JOGO_ESTADO][alvo], qs[JOGO_ESTADO][alvo] = _empirico(p, do_estado)
        dias = p.dia[historico]
        for j in no_teste:
            # ±15 dias em torno da mesma data um ano antes; ano bissexto
            # pode deslocar um dia, sem mudar a natureza histórica do baseline.
            epoca = historico[np.abs(dias - (p.dia[teste[j]] - 365)) <= 15]
            if epoca.size:
                probs[SAZONAL][j], qs[SAZONAL][j] = _empirico(p, epoca)
    return probs, qs


def prever_avaliacao_jogos(series: Sequence[SerieJogo], cfg: ConfiguracaoJogos, *, log: Callable[[str], None] = lambda _: None) -> PrevisoesJogos | None:
    p = montar_painel_jogos(series, cfg)
    candidatas = np.flatnonzero(p.dia >= cfg.inicio_teste)
    if not candidatas.size:
        return None
    blocos, probabilidades, quantis, dobras = [], [], [], []
    numero = (p.dia[candidatas] - cfg.inicio_teste) // cfg.retreino
    for k in np.unique(numero):
        limite = cfg.inicio_teste + int(k) * cfg.retreino
        treino = selecionar_treino_jogos(p, limite, cfg.horizonte)
        teste = candidatas[numero == k]
        if treino.size < cfg.min_amostras:
            log(f"h={cfg.horizonte} dobra {int(k) + 1}: sem treino suficiente ({treino.size})")
            continue
        probs, qs = _baselines(p, treino, teste)
        probs[ML], qs[ML] = _ajustar_prever(p.X[treino], p.baixou[treino], p.razao[treino], p.X[teste], cfg)
        blocos.append(teste)
        probabilidades.append(probs)
        quantis.append(qs)
        info = {"dobra": int(k) + 1, "retreino_em": str(EPOCA + timedelta(days=limite)), "treino": int(treino.size), "teste": int(teste.size)}
        dobras.append(info)
        log(f"h={cfg.horizonte} dobra {int(k) + 1}: {treino.size} treino, {teste.size} teste; retreino {info['retreino_em']}")
    if not blocos:
        return None
    linhas = np.concatenate(blocos)
    return PrevisoesJogos(
        cfg, p.dia[linhas], p.item[linhas], p.preco[linhas], p.razao[linhas], p.baixou[linhas],
        {nome: np.concatenate([b[nome] for b in probabilidades]) for nome in probabilidades[0]},
        {nome: np.concatenate([b[nome] for b in quantis]) for nome in quantis[0]}, dobras,
    )


def _metricas(prob: np.ndarray, q: np.ndarray, real: np.ndarray, baixou: np.ndarray, preco: np.ndarray) -> dict:
    erro = real[:, None] - q
    eps = np.clip(prob, 1e-7, 1 - 1e-7)
    return {
        "brier": float(np.mean((prob - baixou) ** 2)),
        "log_loss": float(-np.mean(baixou * np.log(eps) + (1 - baixou) * np.log(1 - eps))),
        "pinball": float(np.maximum(QUANTIS * erro, (QUANTIS - 1) * erro).mean()),
        "mae_razao": float(np.abs(q[:, 1] - real).mean()),
        "mae_preco": float((np.abs(q[:, 1] - real) * preco).mean()),
        "cobertura": float(np.mean((real >= q[:, 0] - 1e-10) & (real <= q[:, 2] + 1e-10))),
        "largura": float(np.mean(q[:, 2] - q[:, 0])),
    }


def executar_jogos(series: Sequence[SerieJogo], cfg: ConfiguracaoJogos, *, log: Callable[[str], None] = lambda _: None) -> dict:
    series = list(series)
    p = prever_avaliacao_jogos(series, cfg, log=log)
    base = {
        "horizonte": cfg.horizonte, "inicio_teste": str(EPOCA + timedelta(days=cfg.inicio_teste)),
        "retreino_dias": cfg.retreino, "passo_dias": cfg.passo, "min_historia": cfg.min_historia,
        "iteracoes": cfg.iteracoes, "min_amostras_treino": cfg.min_amostras,
        "min_por_folha": cfg.min_por_folha,
        "alvo": "preço menor que o atual; menor fechamento diário entre hoje e t+h",
        "unidade_pinball": "razão do menor preço pelo preço na origem",
        "ressalvas": [
            "Janelas com indisponibilidade são excluídas; a avaliação é condicionada à disponibilidade contínua.",
            "Origens sobrepostas e jogos correlacionados; diferenças não demonstram significância estatística.",
            "Fechamentos diários não capturam promoções que começam e terminam dentro do mesmo dia.",
        ],
        "jogos": 0, "origens": 0, "dobras": [], "modelos": {}, "por_ano": {}, "por_jogo": {},
    }
    if p is None:
        return base

    def resumo(mascara: np.ndarray) -> dict:
        modelos = {nome: _metricas(prob[mascara], p.quantis[nome][mascara], p.real[mascara], p.baixou[mascara], p.preco[mascara]) for nome, prob in p.probabilidades.items()}
        for m in modelos.values():
            for metrica in ("brier", "pinball"):
                for sufixo, regua in (("vs_frequencia", JOGO), ("vs_jogo_estado", JOGO_ESTADO)):
                    ref = modelos[regua][metrica]
                    m[f"{metrica}_{sufixo}"] = m[metrica] / ref - 1 if ref > 1e-12 else None
        return {"origens": int(mascara.sum()), "frequencia_preco_menor": float(p.baixou[mascara].mean()), "modelos": modelos}

    base.update(resumo(np.ones(p.dia.size, dtype=bool)))
    base["jogos"] = int(np.unique(p.item).size)
    base["dobras"] = p.dobras
    anos = np.array([(EPOCA + timedelta(days=int(d))).year for d in p.dia])
    base["por_ano"] = {str(a): resumo(anos == a) for a in np.unique(anos)}
    base["por_jogo"] = {str(series[int(i)].appid): {"titulo": series[int(i)].titulo, **resumo(p.item == i)} for i in np.unique(p.item)}
    return base


def prever_jogos_agora(series: Sequence[SerieJogo], horizonte: int, *, cfg: ConfiguracaoJogos | None = None, log: Callable[[str], None] = lambda _: None) -> list[dict]:
    """Treina até a data final de cada cache; não chama APIs nem prolonga série antiga."""
    series = list(series)
    cfg = cfg or ConfiguracaoJogos(horizonte=horizonte, inicio_teste=0)
    if cfg.horizonte != horizonte:
        raise ValueError("horizonte diverge da configuração")
    p = montar_painel_jogos(series, cfg)
    por_dia: dict[int, list[int]] = {}
    for i, s in enumerate(series):
        if len(s.dias) >= cfg.min_historia and np.isfinite(s.preco[-1]) and s.preco[-1] > 0:
            por_dia.setdefault(int(s.dias[-1]), []).append(i)
    saida = []
    for dia, itens in sorted(por_dia.items()):
        treino = selecionar_treino_jogos(p, dia, horizonte)
        if treino.size < cfg.min_amostras:
            continue
        X = np.concatenate([atributos_jogo(series[i], np.array([len(series[i].dias) - 1])) for i in itens])
        probs, qs = _ajustar_prever(p.X[treino], p.baixou[treino], p.razao[treino], X, cfg)
        for j, i in enumerate(itens):
            s = series[i]
            valores = qs[j] * s.preco[-1]
            saida.append({
                "appid": s.appid, "data_base": str(EPOCA + timedelta(days=dia)),
                "horizonte": horizonte, "modelo": ML,
                "probabilidade_desconto": float(probs[j]),
                "preco_minimo_p10": round(float(valores[0]), 2),
                "preco_minimo_p50": round(float(valores[1]), 2),
                "preco_minimo_p90": round(float(valores[2]), 2),
            })
        log(f"h={horizonte}: {len(itens)} previsões em {EPOCA + timedelta(days=dia)}, {treino.size} linhas de treino")
    return saida


def tabela_markdown_jogos(resultado: dict) -> str:
    if not resultado["origens"]:
        return f"Horizonte {resultado['horizonte']} dias: sem origens elegíveis."
    linhas = [
        f"Horizonte {resultado['horizonte']} dias: {resultado['jogos']} jogos, {resultado['origens']} origens",
        "", "| Modelo | Brier | Pinball | Cobertura P10–P90 | MAE (R$) |",
        "|---|---:|---:|---:|---:|",
    ]
    for nome, m in resultado["modelos"].items():
        linhas.append(f"| {nome} | {m['brier']:.4f} | {m['pinball']:.4f} | {m['cobertura']:.1%} | {m['mae_preco']:.2f} |")
    return "\n".join(linhas)
