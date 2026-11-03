"""Baselines e validação em janela deslizante (walk-forward) para a variação do log do preço.

O alvo de cada origem t é r = log p[t+h] - log p[t]. Cada modelo devolve, para cada origem,
os quantis (P10, P50, P90) de r usando só dados até t. Os modelos de baseline têm essa
propriedade por construção; o teste de vazamento confere isso mudando o futuro.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from steam_forecast.series import SerieDiaria

QUANTIS = (0.1, 0.5, 0.9)

# prever(log_preco, h, origens) -> array (len(origens), 3) com os quantis de r em cada origem
Previsor = Callable[[np.ndarray, int, np.ndarray], np.ndarray]


@dataclass(frozen=True)
class Modelo:
    nome: str
    prever: Previsor
    tem_intervalo: bool


def _regra_zero(logp: np.ndarray) -> np.ndarray:
    return np.zeros(logp.size)


def _regra_media_movel(logp: np.ndarray, janela: int = 30) -> np.ndarray:
    """Regra para cada origem s: média dos últimos `janela` dias menos o preço de s (volta à média)."""
    acumulado = np.concatenate(([0.0], np.cumsum(logp)))
    fim = np.arange(1, logp.size + 1)
    inicio = np.maximum(0, fim - janela)
    media = (acumulado[fim] - acumulado[inicio]) / (fim - inicio)
    return media - logp


def _com_erro_empirico(
    regra: np.ndarray,
    logp: np.ndarray,
    h: int,
    origens: np.ndarray,
    janela_erro: int,
    min_amostras: int,
) -> np.ndarray:
    """Mediana da regra em t somada aos quantis do erro da própria regra em origens s com s + h <= t."""
    real = logp[h:] - logp[:-h]  # real[s] = r da origem s, conhecido só em s + h
    erro = real - regra[: real.size]
    saida = np.full((origens.size, 3), np.nan)
    for i, t in enumerate(origens):
        inicio = max(0, t - h - janela_erro + 1)
        amostra = erro[inicio : t - h + 1]
        if amostra.size >= min_amostras:
            saida[i] = regra[t] + np.quantile(amostra, QUANTIS)
    return saida


def modelo_naive(logp: np.ndarray, h: int, origens: np.ndarray) -> np.ndarray:
    """O preço em t+h é o de t. Previsão pontual: sem intervalo."""
    return np.zeros((origens.size, 3))


def modelo_naive_erro(
    logp: np.ndarray, h: int, origens: np.ndarray, janela_erro: int = 365, min_amostras: int = 60
) -> np.ndarray:
    """Naive com intervalo: quantis das variações de h dias já vistas (a régua do intervalo)."""
    return _com_erro_empirico(_regra_zero(logp), logp, h, origens, janela_erro, min_amostras)


def modelo_media_movel_erro(
    logp: np.ndarray, h: int, origens: np.ndarray, janela_erro: int = 365, min_amostras: int = 60
) -> np.ndarray:
    return _com_erro_empirico(
        _regra_media_movel(logp), logp, h, origens, janela_erro, min_amostras
    )


MODELOS = (
    Modelo("naive (pontual)", modelo_naive, False),
    Modelo("naive + erro empírico", modelo_naive_erro, True),
    Modelo("média móvel 30d + erro empírico", modelo_media_movel_erro, True),
)


def origens_validas(
    n: int, h: int, *, passo: int = 7, historia_min: int = 365, min_amostras: int = 60
) -> np.ndarray:
    primeira = max(historia_min - 1, h + min_amostras - 1)
    return np.arange(primeira, n - h, passo)


def pinball(pred: np.ndarray, real: np.ndarray) -> float:
    """Perda de quantil média sobre origens e sobre P10, P50, P90."""
    q = np.asarray(QUANTIS)
    dif = real[:, None] - pred
    return float(np.mean(np.maximum(q * dif, (q - 1) * dif)))


def metricas(pred: np.ndarray, real: np.ndarray, tem_intervalo: bool) -> dict[str, float | None]:
    return {
        "mae": float(np.mean(np.abs(real - pred[:, 1]))),
        "pinball": pinball(pred, real),
        "cobertura": float(np.mean((pred[:, 0] <= real) & (real <= pred[:, 2]))) if tem_intervalo else None,
        "largura": float(np.mean(pred[:, 2] - pred[:, 0])) if tem_intervalo else None,
    }


def filtrar_series(
    series: Sequence[SerieDiaria], *, min_dias: int = 500, min_vendas_por_dia: float = 3.0
) -> list[SerieDiaria]:
    """Fora itens com pouco histórico ou pouca liquidez: o preço deles é ruído de um ou dois negócios."""
    return [
        s
        for s in series
        if s.log_preco.size >= min_dias and s.volume.sum() / s.log_preco.size >= min_vendas_por_dia
    ]


def avaliar(
    series: Sequence[SerieDiaria],
    horizonte: int,
    *,
    modelos: Sequence[Modelo] = MODELOS,
    passo: int = 7,
    historia_min: int = 365,
    min_amostras: int = 60,
) -> dict:
    """Walk-forward em todos os itens; métricas agrupadas sobre todas as origens (média simples)."""
    reais: list[np.ndarray] = []
    previstos: dict[str, list[np.ndarray]] = {m.nome: [] for m in modelos}
    itens = 0
    for serie in series:
        logp = serie.log_preco
        origens = origens_validas(
            logp.size, horizonte, passo=passo, historia_min=historia_min, min_amostras=min_amostras
        )
        if origens.size == 0:
            continue
        itens += 1
        reais.append(logp[origens + horizonte] - logp[origens])
        for m in modelos:
            previstos[m.nome].append(m.prever(logp, horizonte, origens))
    if not reais:
        return {"horizonte": horizonte, "itens": 0, "origens": 0, "modelos": {}}

    real = np.concatenate(reais)
    resultado = {
        m.nome: metricas(np.concatenate(previstos[m.nome]), real, m.tem_intervalo) for m in modelos
    }
    return {"horizonte": horizonte, "itens": itens, "origens": int(real.size), "modelos": resultado}


def tabela_markdown(resultado: dict) -> str:
    modelos = resultado["modelos"]
    if not modelos:
        return f"Horizonte {resultado['horizonte']} dias: sem itens elegíveis."
    ref = modelos.get("naive + erro empírico", {}).get("pinball")
    linhas = [
        f"**Horizonte {resultado['horizonte']} dias** - {resultado['itens']} itens, {resultado['origens']} origens",
        "",
        "| Modelo | MAE da mediana | Pinball | vs naive+erro | Cobertura P10-P90 | Largura |",
        "|---|---|---|---|---|---|",
    ]
    for nome, m in modelos.items():
        relativo = f"{(m['pinball'] / ref - 1) * 100:+.1f}%" if ref else "-"
        cobertura = "-" if m["cobertura"] is None else f"{m['cobertura'] * 100:.1f}%"
        largura = "-" if m["largura"] is None else f"{m['largura']:.3f}"
        linhas.append(f"| {nome} | {m['mae']:.4f} | {m['pinball']:.4f} | {relativo} | {cobertura} | {largura} |")
    return "\n".join(linhas)
