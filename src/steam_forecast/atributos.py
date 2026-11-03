"""Atributos de cada origem t, calculados só com dados até t (nada do futuro).

Os atributos do item (retornos, volatilidade, volume, posição na faixa de 365 dias, calendário)
mais três do mercado: a média, entre os itens, do retorno de 7 e de 30 dias e da volatilidade de
30 dias na mesma data. Os itens se movem juntos, então o estado do mercado é informação útil.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from steam_forecast.series import SerieDiaria

LAGS = (1, 7, 14, 30, 60, 90, 180)
JANELAS_VOL = (7, 30, 90)
JANELAS_VOLUME = (7, 30)
T_MIN = 90  # primeira origem usada: dá para calcular a volatilidade de 90 dias
ESCALA_MIN = 0.002

NOMES_PROPRIOS = (
    *[f"ret_{k}" for k in LAGS],
    "desv_ma_30",
    "desv_ma_90",
    *[f"vol_{k}" for k in JANELAS_VOL],
    *[f"volume_{k}" for k in JANELAS_VOLUME],
    "volume_razao",
    "queda_max_365",
    "alta_min_365",
    "idade",
    "nivel",
    "doy_origem_sen",
    "doy_origem_cos",
    "doy_alvo_sen",
    "doy_alvo_cos",
)
NOMES_MERCADO = ("mercado_ret_7", "mercado_ret_30", "mercado_vol_30", "rel_ret_30")
NOMES = NOMES_PROPRIOS + NOMES_MERCADO
COLUNAS_PROPRIAS = tuple(range(len(NOMES_PROPRIOS)))
COLUNAS_TODAS = tuple(range(len(NOMES)))


def _atrasar(x: np.ndarray, k: int) -> np.ndarray:
    """x[t-k], NaN onde t < k."""
    saida = np.full(x.size, np.nan)
    saida[k:] = x[:-k]
    return saida


def _media_movel(x: np.ndarray, k: int) -> np.ndarray:
    """Média dos k valores que terminam em t; NaN até t < k - 1."""
    acumulado = np.concatenate(([0.0], np.cumsum(x)))
    saida = np.full(x.size, np.nan)
    saida[k - 1 :] = (acumulado[k:] - acumulado[:-k]) / k
    return saida


def _desvio_movel(x: np.ndarray, k: int) -> np.ndarray:
    """Desvio-padrão dos k valores que terminam em t; NaN até t < k (x[0] é artificial)."""
    m1 = _media_movel(x, k)
    m2 = _media_movel(x * x, k)
    saida = np.sqrt(np.maximum(m2 - m1 * m1, 0.0))
    saida[:k] = np.nan
    return saida


def _extremo_movel(x: np.ndarray, k: int, funcao) -> np.ndarray:
    """Máximo ou mínimo dos últimos k valores; até t < k - 1 usa os que existem."""
    completo = np.concatenate((np.full(k - 1, np.nan), x))
    return funcao(sliding_window_view(completo, k), axis=1)


def _dia_do_ano(dias: np.ndarray) -> np.ndarray:
    datas = dias.astype("datetime64[D]")
    return (datas - datas.astype("datetime64[Y]")).astype(np.int64).astype(float)


def _retorno_diario(logp: np.ndarray) -> np.ndarray:
    return np.diff(logp, prepend=logp[0])


def proprios(serie: SerieDiaria, h: int) -> np.ndarray:
    """Matriz (dias, len(NOMES_PROPRIOS)); a linha t só usa dados até t (o alvo entra só pelo calendário)."""
    logp = serie.log_preco
    n = logp.size
    dr = _retorno_diario(logp)
    colunas: list[np.ndarray] = [logp - _atrasar(logp, k) for k in LAGS]
    colunas += [logp - _media_movel(logp, 30), logp - _media_movel(logp, 90)]
    colunas += [_desvio_movel(dr, k) for k in JANELAS_VOL]
    volume = serie.volume.astype(float)
    log_volume = [np.log1p(_media_movel(volume, k)) for k in JANELAS_VOLUME]
    colunas += log_volume + [log_volume[0] - log_volume[1]]
    colunas += [logp - _extremo_movel(logp, 365, np.nanmax), logp - _extremo_movel(logp, 365, np.nanmin)]
    colunas += [np.log1p(np.arange(n)), logp]
    dias = serie.dia0 + np.arange(n)
    for quando in (dias, dias + h):
        angulo = 2 * np.pi * _dia_do_ano(quando) / 365.25
        colunas += [np.sin(angulo), np.cos(angulo)]
    return np.column_stack(colunas)


def fatores_de_mercado(series: list[SerieDiaria]) -> tuple[int, np.ndarray]:
    """(dia inicial, matriz (dias, 3)): média entre os itens de ret_7, ret_30 e vol_30 em cada dia."""
    inicio = min(s.dia0 for s in series)
    fim = max(s.dia0 + s.log_preco.size for s in series)
    pilhas = np.full((3, len(series), fim - inicio), np.nan)
    for i, s in enumerate(series):
        logp = s.log_preco
        o = s.dia0 - inicio
        n = logp.size
        pilhas[0, i, o : o + n] = logp - _atrasar(logp, 7)
        pilhas[1, i, o : o + n] = logp - _atrasar(logp, 30)
        pilhas[2, i, o : o + n] = _desvio_movel(_retorno_diario(logp), 30)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # dias sem nenhum item com a janela completa
        medias = np.nanmean(pilhas, axis=1)
    return inicio, medias.T


@dataclass(frozen=True, eq=False)
class Painel:
    X: np.ndarray  # (linhas, len(NOMES))
    item: np.ndarray  # índice da série de cada linha
    t: np.ndarray  # índice da origem dentro da série
    dia: np.ndarray  # dia absoluto da origem
    r: np.ndarray  # variação do log do preço em h dias; NaN quando o futuro ainda não existe
    escala: np.ndarray  # volatilidade de 90 dias * sqrt(h): a escala típica de r
    inicio: np.ndarray  # primeira linha de cada série

    def linha(self, item: np.ndarray, t: np.ndarray) -> np.ndarray:
        return self.inicio[item] + t - T_MIN


def montar_painel(series: list[SerieDiaria], h: int) -> Painel:
    ini, mercado = fatores_de_mercado(series)
    i_ret30 = NOMES_PROPRIOS.index("ret_30")
    i_vol90 = NOMES_PROPRIOS.index("vol_90")
    partes: dict[str, list[np.ndarray]] = {k: [] for k in ("X", "item", "t", "dia", "r", "escala")}
    inicios: list[int] = []
    total = 0
    for i, s in enumerate(series):
        n = s.log_preco.size
        inicios.append(total)
        if n <= T_MIN:
            continue
        p = proprios(s, h)[T_MIN:]
        t = np.arange(T_MIN, n)
        dia = s.dia0 + t
        m = mercado[dia - ini]
        r = np.full(t.size, np.nan)
        com_futuro = t + h <= n - 1
        r[com_futuro] = s.log_preco[t[com_futuro] + h] - s.log_preco[t[com_futuro]]
        partes["X"].append(np.column_stack([p, m, p[:, i_ret30] - m[:, 1]]))
        partes["item"].append(np.full(t.size, i))
        partes["t"].append(t)
        partes["dia"].append(dia)
        partes["r"].append(r)
        partes["escala"].append(np.maximum(p[:, i_vol90], ESCALA_MIN) * np.sqrt(h))
        total += t.size
    return Painel(
        X=np.concatenate(partes["X"]),
        item=np.concatenate(partes["item"]),
        t=np.concatenate(partes["t"]),
        dia=np.concatenate(partes["dia"]),
        r=np.concatenate(partes["r"]),
        escala=np.concatenate(partes["escala"]),
        inicio=np.asarray(inicios),
    )
