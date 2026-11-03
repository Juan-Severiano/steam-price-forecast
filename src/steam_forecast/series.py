"""Do histórico da Steam (diário nos dias antigos, por hora nos últimos 30) para uma série diária."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from steam_forecast.steam import Historico

DIA_S = 86400


@dataclass(frozen=True, eq=False)
class SerieDiaria:
    nome: str
    dia0: int  # dia (segundos // 86400) do primeiro valor
    log_preco: np.ndarray  # um valor por dia; nos dias sem venda repete o último preço
    volume: np.ndarray  # vendas no dia (0 nos dias repetidos)

    @property
    def dias_com_venda(self) -> int:
        return int((self.volume > 0).sum())


def diaria(historico: Historico) -> SerieDiaria | None:
    """Preço do dia = média do preço ponderada pelo volume. Dias sem venda repetem o último preço.

    O último dia do histórico é descartado: está incompleto e puxaria o preço do dia.
    """
    valido = historico.preco > 0
    dias = historico.ts[valido] // DIA_S
    preco = historico.preco[valido]
    volume = historico.volume[valido]
    if dias.size == 0:
        return None

    ultimo = int(dias.max())
    manter = dias < ultimo
    if not manter.any():
        return None
    dias, preco, volume = dias[manter], preco[manter], volume[manter]

    dia0 = int(dias.min())
    n = int(dias.max()) - dia0 + 1
    idx = (dias - dia0).astype(np.int64)
    vendas = np.bincount(idx, weights=volume, minlength=n)
    valor = np.bincount(idx, weights=preco * volume, minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        preco_dia = np.where(vendas > 0, valor / vendas, np.nan)

    tem = ~np.isnan(preco_dia)
    if not tem.any():
        return None
    primeiro = int(np.argmax(tem))
    preco_dia, vendas = preco_dia[primeiro:], vendas[primeiro:]
    dia0 += primeiro

    posicao = np.where(~np.isnan(preco_dia), np.arange(preco_dia.size), 0)
    np.maximum.accumulate(posicao, out=posicao)
    preco_dia = preco_dia[posicao]
    return SerieDiaria(
        nome=historico.nome,
        dia0=dia0,
        log_preco=np.log(preco_dia),
        volume=vendas.astype(np.int64),
    )
