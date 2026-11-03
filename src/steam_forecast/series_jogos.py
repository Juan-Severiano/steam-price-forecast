"""Fechamento diário do preço dos jogos, limitado à data de cada coleta."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from steam_forecast.itad import HistoricoJogo, parsear_historico

DIA_S = 86400


@dataclass(frozen=True, eq=False)
class SerieJogo:
    appid: int
    gid: str
    titulo: str
    moeda: str
    dias: np.ndarray  # dias UTC desde 1970, consecutivos
    preco: np.ndarray  # fechamento do dia; NaN enquanto o jogo estiver indisponível
    regular: np.ndarray
    desconto: np.ndarray


def diaria_jogo(historico: HistoricoJogo, coletado_em: datetime) -> SerieJogo | None:
    """Estado após o último evento de cada dia completo, sem antecipar eventos.

    Começa no dia do primeiro evento e termina no dia anterior à coleta, em UTC.
    Um evento de retirada da loja continua como NaN até um novo evento de oferta.
    O histórico original não é modificado, inclusive se vier fora de ordem.
    """
    if coletado_em.tzinfo is None or coletado_em.utcoffset() is None:
        raise ValueError("coletado_em precisa informar o fuso horário")
    if not (len(historico.ts) == len(historico.preco) == len(historico.regular) == len(historico.desconto)):
        raise ValueError("arrays do histórico têm tamanhos diferentes")
    if historico.ts.size == 0:
        return None
    if historico.appid is None:
        raise ValueError("histórico sem appid da Steam")

    ordem = np.argsort(historico.ts, kind="stable")
    ts = historico.ts[ordem]
    primeiro_dia = int(ts[0] // DIA_S)
    dia_coleta = int(coletado_em.timestamp() // DIA_S)
    if primeiro_dia >= dia_coleta:
        return None

    dias = np.arange(primeiro_dia, dia_coleta, dtype=np.int64)
    # A meia-noite seguinte já pertence ao próximo dia: buscar estritamente antes.
    posicao = np.searchsorted(ts, (dias + 1) * DIA_S, side="left") - 1
    eventos = ordem[posicao]
    return SerieJogo(
        appid=int(historico.appid),
        gid=historico.gid,
        titulo=historico.titulo,
        moeda=historico.moeda,
        dias=dias,
        preco=historico.preco[eventos].copy(),
        regular=historico.regular[eventos].copy(),
        desconto=historico.desconto[eventos].copy(),
    )


def carregar_series_jogos(destino: Path) -> list[SerieJogo]:
    """Lê o cache BRL usando a data registrada em cada arquivo, nunca a data de hoje.

    Históricos vazios, sem preço ou sem um dia completo ficam de fora. Um arquivo inválido
    interrompe a carga com seu appid/caminho, para não avaliar uma amostra parcial
    sem avisar. Outra moeda não é misturada aos preços em reais.
    """
    series: list[SerieJogo] = []
    for caminho in sorted(destino.glob("*.json")):
        appid: object = caminho.stem
        try:
            corpo = json.loads(caminho.read_text(encoding="utf-8"))
            if not isinstance(corpo, dict):
                raise ValueError("o arquivo não contém um objeto")
            appid = corpo.get("appid", caminho.stem)
            if isinstance(appid, bool) or not isinstance(appid, (int, str)):
                raise ValueError("appid inválido")
            appid = int(corpo["appid"])
            if appid <= 0:
                raise ValueError("appid deve ser positivo")
            coletado_em = datetime.fromisoformat(corpo["coletado_em"].replace("Z", "+00:00"))
            historico = parsear_historico(corpo["bruto"], corpo["gid"], appid, corpo.get("titulo", ""))
            if not historico.moeda and not np.isfinite(historico.preco).any():
                continue
            if historico.moeda != "BRL":
                raise ValueError(f"moeda {historico.moeda!r}; esperado BRL")
            serie = diaria_jogo(historico, coletado_em)
            if serie is not None:
                series.append(serie)
        except (OSError, KeyError, TypeError, ValueError, AttributeError, OverflowError) as erro:
            raise ValueError(f"histórico do appid {appid} em {caminho.name}: {erro}") from erro
    return series
