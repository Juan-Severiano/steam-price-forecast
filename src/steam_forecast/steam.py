"""Cliente do Mercado da Comunidade Steam e leitura do histórico de preço.

`market/pricehistory` exige a sessão logada; `market/search/render` é público.
O formato do histórico (data como "Nov 01 2013 01: +0", preço em float, volume em texto)
vem de relatos de terceiros e foi escrito para falhar alto se a Steam mudar.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import numpy as np

from steam_forecast.env import Cookie
from steam_forecast.limitador import Limitador

BASE = "https://steamcommunity.com/market"
# Identifica o projeto em vez de imitar um navegador: em 03/11/2026 o search/render respondeu 429
# a um User-Agent de navegador e 200 a este e ao do curl, com o mesmo intervalo entre pedidos.
USER_AGENT = "steam-price-forecast/0.1 (projeto pessoal de pesquisa)"

MESES = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}  # fmt: skip


class HistoricoInvalido(ValueError):
    """A resposta não tem o formato esperado."""


class SessaoExpirada(RuntimeError):
    """A Steam recusou a sessão (400, 401 ou 403): cookie vencido, errado ou ausente."""


class LimiteExcedido(RuntimeError):
    """HTTP 429: a Steam pediu para esperar."""

    def __init__(self, retry_after: int | None = None) -> None:
        super().__init__("a Steam respondeu 429 (limite de requisições)")
        self.retry_after = retry_after


@dataclass(frozen=True, eq=False)
class Historico:
    appid: int
    nome: str
    prefixo: str  # moeda da carteira da conta, como a Steam devolve ("R$")
    sufixo: str
    ts: np.ndarray  # segundos desde 1970 em UTC, crescente
    preco: np.ndarray  # float, preço mediano de venda no período
    volume: np.ndarray  # int, vendas no período


def _segundos(texto: str) -> int:
    try:
        mes, dia, ano, hora, fuso = texto.split()
        if fuso != "+0" or not hora.endswith(":"):
            raise ValueError
        momento = datetime(int(ano), MESES[mes], int(dia), int(hora[:-1]), tzinfo=timezone.utc)
    except (ValueError, KeyError) as erro:
        raise HistoricoInvalido(f"data fora do formato esperado: {texto!r}") from erro
    return int(momento.timestamp())


def parsear_historico(bruto: object, appid: int, nome: str) -> Historico:
    if not isinstance(bruto, dict) or bruto.get("success") is not True:
        raise HistoricoInvalido("resposta sem success=true")
    pontos = bruto.get("prices")
    if not isinstance(pontos, list) or not pontos:
        raise HistoricoInvalido("resposta sem pontos de preço")

    ts = np.empty(len(pontos), dtype=np.int64)
    preco = np.empty(len(pontos), dtype=np.float64)
    volume = np.empty(len(pontos), dtype=np.int64)
    for i, ponto in enumerate(pontos):
        try:
            data, valor, vendas = ponto
            ts[i] = _segundos(data)
            preco[i] = float(valor)
            volume[i] = int(vendas)
        except (TypeError, ValueError) as erro:
            if isinstance(erro, HistoricoInvalido):
                raise
            raise HistoricoInvalido(f"ponto {i} fora do formato esperado") from erro
    if not np.all(np.isfinite(preco)) or np.any(preco < 0) or np.any(volume < 0):
        raise HistoricoInvalido("preço ou volume inválido")

    if np.any(np.diff(ts) < 0):
        ordem = np.argsort(ts, kind="stable")
        ts, preco, volume = ts[ordem], preco[ordem], volume[ordem]
    return Historico(
        appid=appid,
        nome=nome,
        prefixo=str(bruto.get("price_prefix", "")),
        sufixo=str(bruto.get("price_suffix", "")),
        ts=ts,
        preco=preco,
        volume=volume,
    )


def _checar(resposta: httpx.Response) -> None:
    if resposta.status_code == 429:
        espera = resposta.headers.get("Retry-After", "")
        raise LimiteExcedido(int(espera) if espera.isdigit() else None)
    if resposta.status_code in (400, 401, 403):
        raise SessaoExpirada(f"HTTP {resposta.status_code}: cookie vencido, errado ou ausente")
    resposta.raise_for_status()


class ClienteSteam:
    def __init__(
        self,
        cookie: Cookie | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._cookie = cookie
        self._http = httpx.Client(
            transport=transport,
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    def fechar(self) -> None:
        self._http.close()

    def historico(self, appid: int, nome: str) -> object:
        """JSON bruto de `pricehistory`. O cookie vai só neste pedido."""
        if self._cookie is None:
            raise SessaoExpirada("pricehistory precisa do cookie da sessão (veja .env.example)")
        resposta = self._http.get(
            f"{BASE}/pricehistory/",
            params={"appid": appid, "market_hash_name": nome},
            headers={"Cookie": self._cookie.cabecalho()},
        )
        _checar(resposta)
        try:
            dados = resposta.json()
        except ValueError as erro:
            raise HistoricoInvalido("a resposta não é JSON") from erro
        if dados is None or dados is False or dados == []:
            raise SessaoExpirada("a Steam devolveu uma resposta vazia: cookie vencido ou errado")
        return dados

    def universo(
        self,
        appid: int,
        quantidade: int,
        limitador: Limitador | None = None,
        *,
        espera_429: tuple[int, ...] = (60, 180, 300),
        dormir: Callable[[float], None] = time.sleep,
    ) -> list[dict]:
        """Itens mais negociados do jogo, pelo `search/render` público (sem cookie).

        A Steam devolve poucos itens por página (10 nos testes de 03/11/2026), então 300 itens
        são ~30 pedidos; em 429 a mesma página é repetida depois de esperar.
        """
        itens: list[dict] = []
        inicio = 0
        while len(itens) < quantidade:
            tentativa = 0
            while True:
                if limitador is not None:
                    limitador.esperar()
                resposta = self._http.get(
                    f"{BASE}/search/render/",
                    params={
                        "query": "",
                        "start": inicio,
                        "count": 100,
                        "search_descriptions": 0,
                        "sort_column": "popular",
                        "sort_dir": "desc",
                        "appid": appid,
                        "norender": 1,
                    },
                )
                try:
                    _checar(resposta)
                    break
                except LimiteExcedido as erro:
                    if tentativa >= len(espera_429):
                        raise
                    dormir(max(erro.retry_after or 0, espera_429[tentativa]))
                    tentativa += 1
            dados = resposta.json()
            if not isinstance(dados, dict) or dados.get("success") is not True:
                raise HistoricoInvalido("search/render sem success=true")
            resultados = dados.get("results") or []
            if not resultados:
                break
            for r in resultados:
                itens.append(
                    {
                        "appid": appid,
                        "nome": r["hash_name"],
                        "anuncios": r.get("sell_listings"),
                        "menor_preco_centavos": r.get("sell_price"),
                        "menor_preco_texto": r.get("sell_price_text"),
                    }
                )
            inicio += len(resultados)
            if inicio >= int(dados.get("total_count", inicio)):
                break
        return itens[:quantidade]
