"""Gradient boosting com quantis (P10, P50, P90) em janela deslizante, contra os baselines.

A cada `retreino` dias o modelo é treinado de novo só com linhas cujo alvo (t + h) já era conhecido
naquela data, e prevê as origens do trecho seguinte. As origens de teste são as mesmas dos baselines
(a cada 7 dias, com 365 dias de histórico), de `inicio_teste` em diante, para a comparação ser justa.

O alvo é padronizado: z = r / escala, com escala = volatilidade de 90 dias * sqrt(h), e cada linha pesa
`escala`, o que torna a perda de treino igual à perda medida em unidades originais.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from steam_forecast.atributos import COLUNAS_PROPRIAS, COLUNAS_TODAS, T_MIN, Painel, montar_painel
from steam_forecast.avaliacao import MODELOS, QUANTIS, metricas, modelo_naive_erro, origens_validas
from steam_forecast.series import SerieDiaria

EPOCA = date(1970, 1, 1)
REFERENCIA = "naive + erro empírico"
VARIANTES = {
    "GB quantílico (só o item)": COLUNAS_PROPRIAS,
    "GB quantílico (item + mercado)": COLUNAS_TODAS,
}


def dia_absoluto(d: date) -> int:
    return (d - EPOCA).days


@dataclass(frozen=True)
class Configuracao:
    horizonte: int
    inicio_teste: int  # dia absoluto da primeira origem de teste
    retreino: int = 90
    passo: int = 7
    historia_min: int = 365
    min_amostras: int = 60
    passo_treino: int = 2
    iteracoes: int = 150
    taxa: float = 0.05
    folhas: int = 15
    min_por_folha: int = 300


@dataclass(frozen=True, eq=False)
class Previsoes:
    """Previsões de todos os modelos nas mesmas origens de teste."""

    cfg: Configuracao
    previsoes: dict[str, np.ndarray]  # nome -> (origens, 3) com P10, P50, P90 de r
    tem_intervalo: dict[str, bool]
    real: np.ndarray
    item: np.ndarray  # índice da série de cada origem
    dia: np.ndarray  # dia absoluto de cada origem


def selecionar_treino(painel: Painel, limite_dia: int, h: int, passo_treino: int) -> np.ndarray:
    """Linhas cujo alvo (dia + h) já era conhecido em `limite_dia`. Nada depois disso entra no treino."""
    ok = (painel.dia + h <= limite_dia) & ~np.isnan(painel.r) & (painel.t % passo_treino == 0)
    return np.flatnonzero(ok)


def _ajustar_e_prever(
    X_treino: np.ndarray, z: np.ndarray, peso: np.ndarray, X_teste: np.ndarray, cfg: Configuracao
) -> np.ndarray:
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
    except ImportError as erro:  # pragma: no cover
        raise ImportError("o modelo precisa do scikit-learn: uv sync --extra ml") from erro

    saida = np.empty((X_teste.shape[0], len(QUANTIS)))
    for j, q in enumerate(QUANTIS):
        modelo = HistGradientBoostingRegressor(
            loss="quantile",
            quantile=q,
            learning_rate=cfg.taxa,
            max_iter=cfg.iteracoes,
            max_leaf_nodes=cfg.folhas,
            min_samples_leaf=cfg.min_por_folha,
            l2_regularization=1.0,
            early_stopping=False,
            random_state=0,
        )
        modelo.fit(X_treino, z, sample_weight=peso)
        saida[:, j] = modelo.predict(X_teste)
    return np.sort(saida, axis=1)  # quantis ajustados à parte podem se cruzar; ordenar resolve


def prever(
    series: Sequence[SerieDiaria],
    cfg: Configuracao,
    *,
    variantes: dict[str, tuple[int, ...]] = VARIANTES,
    log: Callable[[str], None] = lambda _msg: None,
) -> Previsoes | None:
    """Walk-forward do modelo e dos baselines nas mesmas origens. None se não houver origem de teste."""
    series = list(series)
    h = cfg.horizonte
    painel = montar_painel(series, h)

    itens, ts = [], []
    base: dict[str, list[np.ndarray]] = {m.nome: [] for m in MODELOS}
    for i, s in enumerate(series):
        todas = origens_validas(
            s.log_preco.size, h, passo=cfg.passo, historia_min=cfg.historia_min, min_amostras=cfg.min_amostras
        )
        mascara = s.dia0 + todas >= cfg.inicio_teste
        if not mascara.any():
            continue
        itens.append(np.full(int(mascara.sum()), i))
        ts.append(todas[mascara])
        for m in MODELOS:
            base[m.nome].append(m.prever(s.log_preco, h, todas)[mascara])
    if not itens:
        return None

    item, t = np.concatenate(itens), np.concatenate(ts)
    linhas = painel.linha(item, t)
    dia, real, escala = painel.dia[linhas], painel.r[linhas], painel.escala[linhas]
    previsoes = {nome: np.concatenate(v) for nome, v in base.items()}
    tem_intervalo = {m.nome: m.tem_intervalo for m in MODELOS}
    for nome in variantes:
        previsoes[nome] = np.full((item.size, len(QUANTIS)), np.nan)
        tem_intervalo[nome] = True

    dobra = (dia - cfg.inicio_teste) // cfg.retreino
    for k in np.unique(dobra):
        limite = cfg.inicio_teste + int(k) * cfg.retreino
        treino = selecionar_treino(painel, limite, h, cfg.passo_treino)
        teste = np.flatnonzero(dobra == k)
        z = painel.r[treino] / painel.escala[treino]
        for nome, colunas in variantes.items():
            cols = list(colunas)
            z_prev = _ajustar_e_prever(
                painel.X[treino][:, cols], z, painel.escala[treino], painel.X[linhas[teste]][:, cols], cfg
            )
            previsoes[nome][teste] = z_prev * escala[teste][:, None]
        log(f"h={h} dobra {int(k) + 1}: {treino.size} linhas de treino, {teste.size} origens, retreino em {EPOCA + timedelta(days=limite)}")
    return Previsoes(cfg, previsoes, tem_intervalo, real, item, dia)


def prever_agora(
    series: Sequence[SerieDiaria],
    h: int,
    *,
    colunas: tuple[int, ...] = COLUNAS_TODAS,
    cfg: Configuracao | None = None,
) -> np.ndarray:
    """Quantis (P10, P50, P90) da variação do log do preço em `h` dias, a partir do último dia de cada série.

    Treina com todas as linhas cujo alvo já existe e prevê o futuro que ainda não aconteceu.
    Série curta demais para ter atributos devolve uma linha de NaN.
    """
    series = list(series)
    cfg = cfg or Configuracao(horizonte=h, inicio_teste=0)
    painel = montar_painel(series, h)
    treino = np.flatnonzero(~np.isnan(painel.r) & (painel.t % cfg.passo_treino == 0))
    saida = np.full((len(series), len(QUANTIS)), np.nan)
    itens = np.array([i for i, s in enumerate(series) if s.log_preco.size > T_MIN], dtype=int)
    if itens.size == 0 or treino.size == 0:
        return saida
    ultimos = np.array([series[i].log_preco.size - 1 for i in itens])
    linhas = painel.linha(itens, ultimos)
    cols = list(colunas)
    z = painel.r[treino] / painel.escala[treino]
    z_prev = _ajustar_e_prever(painel.X[treino][:, cols], z, painel.escala[treino], painel.X[linhas][:, cols], cfg)
    saida[itens] = z_prev * painel.escala[linhas][:, None]
    return saida


def prever_referencia_agora(series: Sequence[SerieDiaria], h: int) -> np.ndarray:
    """O mesmo, para a referência (naive + erro empírico). NaN onde não há 60 variações já conhecidas."""
    saida = np.full((len(series), len(QUANTIS)), np.nan)
    for i, s in enumerate(series):
        saida[i] = modelo_naive_erro(s.log_preco, h, np.array([s.log_preco.size - 1]))[0]
    return saida


def plano_de_dobras(series: Sequence[SerieDiaria], cfg: Configuracao) -> list[dict]:
    """O que o walk-forward faz, sem treinar: por dobra, a data do retreino e o tamanho do treino e do teste."""
    series = list(series)
    h = cfg.horizonte
    painel = montar_painel(series, h)
    dias = []
    for s in series:
        todas = origens_validas(
            s.log_preco.size, h, passo=cfg.passo, historia_min=cfg.historia_min, min_amostras=cfg.min_amostras
        )
        d = s.dia0 + todas
        dias.append(d[d >= cfg.inicio_teste])
    dia = np.concatenate(dias)
    dobra = (dia - cfg.inicio_teste) // cfg.retreino
    plano = []
    for k in np.unique(dobra):
        limite = cfg.inicio_teste + int(k) * cfg.retreino
        plano.append(
            {
                "dobra": int(k) + 1,
                "retreino_em": str(EPOCA + timedelta(days=limite)),
                "treino": int(selecionar_treino(painel, limite, h, cfg.passo_treino).size),
                "teste": int((dobra == k).sum()),
            }
        )
    return plano


def _pinball_por_linha(pred: np.ndarray, real: np.ndarray) -> np.ndarray:
    q = np.asarray(QUANTIS)
    dif = real[:, None] - pred
    return np.maximum(q * dif, (q - 1) * dif).mean(axis=1)


def resumir(p: Previsoes) -> dict:
    por_linha = {nome: _pinball_por_linha(pred, p.real) for nome, pred in p.previsoes.items()}
    ref = por_linha[REFERENCIA]
    n_itens = int(p.item.max()) + 1
    contagem = np.bincount(p.item, minlength=n_itens)
    com_origem = contagem > 0

    def media_por_item(v: np.ndarray) -> np.ndarray:
        return (np.bincount(p.item, weights=v, minlength=n_itens) / np.maximum(contagem, 1))[com_origem]

    anos = np.array([(EPOCA + timedelta(days=int(d))).year for d in p.dia])
    modelos: dict[str, dict] = {}
    for nome, pred in p.previsoes.items():
        m = metricas(pred, p.real, p.tem_intervalo[nome])
        m["vs_referencia"] = float(por_linha[nome].mean() / ref.mean() - 1)
        m["itens_melhores"] = (
            None if nome == REFERENCIA else float(np.mean(media_por_item(por_linha[nome]) < media_por_item(ref)))
        )
        modelos[nome] = m
    por_ano = {
        int(a): {nome: float(v[anos == a].mean() / ref[anos == a].mean() - 1) for nome, v in por_linha.items()}
        for a in sorted(set(anos.tolist()))
    }
    cfg = p.cfg
    return {
        "horizonte": cfg.horizonte,
        "itens": int(com_origem.sum()),
        "origens": int(p.real.size),
        "inicio_teste": str(EPOCA + timedelta(days=cfg.inicio_teste)),
        "retreino_dias": cfg.retreino,
        "dobras": int(np.unique((p.dia - cfg.inicio_teste) // cfg.retreino).size),
        "modelos": modelos,
        "por_ano": por_ano,
    }


def executar(series: Sequence[SerieDiaria], cfg: Configuracao, **kw) -> dict:
    p = prever(series, cfg, **kw)
    if p is None:
        return {"horizonte": cfg.horizonte, "itens": 0, "origens": 0, "modelos": {}, "por_ano": {}}
    return resumir(p)


def tabela_markdown(resultado: dict) -> str:
    if not resultado["modelos"]:
        return f"Horizonte {resultado['horizonte']} dias: sem origens de teste."
    linhas = [
        f"**Horizonte {resultado['horizonte']} dias** - {resultado['itens']} itens, {resultado['origens']} origens "
        f"a partir de {resultado['inicio_teste']}, retreino a cada {resultado['retreino_dias']} dias ({resultado['dobras']} dobras)",
        "",
        "| Modelo | MAE da mediana | Pinball | vs naive+erro | Cobertura P10-P90 | Largura | Itens melhores que a referência |",
        "|---|---|---|---|---|---|---|",
    ]
    for nome, m in resultado["modelos"].items():
        relativo = "referência" if nome == REFERENCIA else f"{m['vs_referencia'] * 100:+.1f}%"
        cobertura = "-" if m["cobertura"] is None else f"{m['cobertura'] * 100:.1f}%"
        largura = "-" if m["largura"] is None else f"{m['largura']:.3f}"
        melhores = "-" if m["itens_melhores"] is None else f"{m['itens_melhores'] * 100:.0f}%"
        linhas.append(f"| {nome} | {m['mae']:.4f} | {m['pinball']:.4f} | {relativo} | {cobertura} | {largura} | {melhores} |")
    modelos_ml = [n for n in resultado["modelos"] if n.startswith("GB")]
    if modelos_ml and resultado["por_ano"]:
        linhas += ["", "Pinball contra a referência, por ano da origem:", "", "| Ano | " + " | ".join(modelos_ml) + " |"]
        linhas.append("|---|" + "---|" * len(modelos_ml))
        for ano, valores in resultado["por_ano"].items():
            linhas.append(f"| {ano} | " + " | ".join(f"{valores[n] * 100:+.1f}%" for n in modelos_ml) + " |")
    return "\n".join(linhas)
