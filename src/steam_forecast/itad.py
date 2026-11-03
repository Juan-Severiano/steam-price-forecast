"""Cliente da API do IsThereAnyDeal (https://docs.isthereanydeal.com/): histórico de preço dos jogos da Steam.

Termos da API, em resumo (leia o original antes de publicar qualquer coisa): uso pessoal privado é
permitido; app público pode ser comercial; é preciso citar o IsThereAnyDeal; não se pode insinuar
afiliação, alterar os dados recebidos nem fazer um app que concorra com o IsThereAnyDeal. Limite de
1.000 pedidos a cada 5 minutos; em excesso a API responde 429 com `Retry-After`.

A chave vai só no cabeçalho `ITAD-API-Key`: na URL ela apareceria em mensagem de erro.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import ceil

import httpx
import numpy as np

from steam_forecast.env import ChaveITAD
from steam_forecast.limitador import Limitador
from steam_forecast.steam import LimiteExcedido

BASE = "https://api.isthereanydeal.com"
STEAM = 61  # id da Steam em /service/shops/v1
USER_AGENT = "steam-price-forecast/0.1 (projeto pessoal de pesquisa)"
# Sem `since` a API devolve só os últimos 3 meses.
DESDE_PADRAO = "2005-01-01T00:00:00Z"
MAX_POR_PAGINA = 500  # nos rankings; com limit maior a API devolve só 20


class ChaveRecusada(RuntimeError):
    """A API recusou a chave (401 ou 403): errada, ausente ou sem permissão para o endpoint."""


class RespostaInvalida(ValueError):
    """A resposta não tem o formato descrito na especificação."""


@dataclass(frozen=True, eq=False)
class HistoricoJogo:
    gid: str  # id do jogo no IsThereAnyDeal
    moeda: str  # "BRL"; vazio se o histórico veio sem eventos
    ts: np.ndarray  # segundos desde 1970 em UTC, crescente: quando o preço mudou
    preco: np.ndarray  # preço em vigor a partir de `ts`; NaN quando o jogo não estava à venda
    regular: np.ndarray  # preço cheio em vigor
    desconto: np.ndarray  # corte em %, 0 a 100
    appid: int | None = None  # appid da Steam, quando se sabe
    titulo: str = ""


def _segundos(texto: object) -> int:
    try:
        momento = datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except ValueError as erro:
        raise RespostaInvalida(f"timestamp fora do formato esperado: {texto!r}") from erro
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return int(momento.timestamp())


def parsear_historico(bruto: object, gid: str, appid: int | None = None, titulo: str = "") -> HistoricoJogo:
    """`/games/history/v2`: lista de {timestamp, shop, deal}; `deal` é null quando saiu da loja."""
    if not isinstance(bruto, list):
        raise RespostaInvalida("o histórico não é uma lista")
    n = len(bruto)
    ts = np.empty(n, dtype=np.int64)
    preco = np.full(n, np.nan)
    regular = np.full(n, np.nan)
    desconto = np.full(n, np.nan)
    moedas: set[str] = set()
    for i, evento in enumerate(bruto):
        try:
            ts[i] = _segundos(evento["timestamp"])
            deal = evento["deal"]
            if deal is not None:
                preco[i] = float(deal["price"]["amount"])
                regular[i] = float(deal["regular"]["amount"])
                desconto[i] = float(deal["cut"])
                if not np.isfinite([preco[i], regular[i], desconto[i]]).all():
                    raise RespostaInvalida(f"evento {i} contém preço ou desconto não finito")
                moedas.add(str(deal["price"]["currency"]))
        except RespostaInvalida:
            raise
        except (KeyError, TypeError, ValueError) as erro:
            raise RespostaInvalida(f"evento {i} fora do formato esperado") from erro
    if len(moedas) > 1:
        raise RespostaInvalida(f"mais de uma moeda no histórico: {sorted(moedas)}")
    if np.any(preco < 0) or np.any(regular < 0) or np.any((desconto < 0) | (desconto > 100)):
        raise RespostaInvalida("preço ou desconto fora da faixa")
    if np.any(np.diff(ts) < 0):
        ordem = np.argsort(ts, kind="stable")
        ts, preco, regular, desconto = ts[ordem], preco[ordem], regular[ordem], desconto[ordem]
    return HistoricoJogo(gid, moedas.pop() if moedas else "", ts, preco, regular, desconto, appid, titulo)


def retry_after_segundos(valor: str, agora: datetime | None = None) -> int | None:
    """Retry-After aceita segundos (inclusive zero) ou uma data HTTP, conforme RFC 9110."""
    valor = valor.strip()
    if valor.isascii() and valor.isdigit():
        return int(valor)
    try:
        momento = parsedate_to_datetime(valor)
        if momento.tzinfo is None:
            return None
        return max(0, ceil((momento - (agora or datetime.now(timezone.utc))).total_seconds()))
    except (ValueError, TypeError, OverflowError):
        return None


def _checar(resposta: httpx.Response) -> None:
    if resposta.status_code == 429:
        espera = resposta.headers.get("Retry-After", "")
        raise LimiteExcedido(retry_after_segundos(espera))
    if resposta.status_code in (401, 403):
        raise ChaveRecusada(f"HTTP {resposta.status_code}: chave errada, ausente ou sem permissão")
    resposta.raise_for_status()


class ClienteITAD:
    def __init__(
        self,
        chave: ChaveITAD,
        *,
        limitador: Limitador | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._limitador = limitador
        self._http = httpx.Client(
            base_url=BASE,
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "ITAD-API-Key": chave.valor, "Accept": "application/json"},
        )

    def fechar(self) -> None:
        self._http.close()

    def _pedir(self, metodo: str, caminho: str, **kw) -> object:
        if self._limitador is not None:
            self._limitador.esperar()
        resposta = self._http.request(metodo, caminho, **kw)
        _checar(resposta)
        try:
            return resposta.json()
        except ValueError as erro:
            raise RespostaInvalida("a resposta não é JSON") from erro

    def ids_por_appid(self, appids: list[int]) -> dict[int, str]:
        """appid da Steam -> id do jogo no ITAD. Jogos que o ITAD não conhece ficam de fora."""
        saida: dict[int, str] = {}
        for i in range(0, len(appids), 200):
            lote = appids[i : i + 200]
            dados = self._pedir("POST", f"/lookup/id/shop/{STEAM}/v1", json=[f"app/{a}" for a in lote])
            if not isinstance(dados, dict):
                raise RespostaInvalida("o lookup não devolveu um objeto")
            for chave, gid in dados.items():
                if gid and str(chave).startswith("app/") and str(chave)[4:].isdigit():
                    saida[int(str(chave)[4:])] = str(gid)
        return saida

    def buscar(self, titulo: str, resultados: int = 10) -> list[dict]:
        dados = self._pedir("GET", "/games/search/v1", params={"title": titulo, "results": resultados})
        if not isinstance(dados, list):
            raise RespostaInvalida("a busca não devolveu uma lista")
        return dados

    def ranking(self, tipo: str, quantidade: int) -> list[dict]:
        """`tipo` é "most-popular" ou "most-collected". Páginas de 500: acima disso a API ignora o limite e devolve 20."""
        itens: list[dict] = []
        while len(itens) < quantidade:
            pedido = min(MAX_POR_PAGINA, quantidade - len(itens))
            lote = self._pedir("GET", f"/stats/{tipo}/v1", params={"limit": pedido, "offset": len(itens)})
            if not isinstance(lote, list):
                raise RespostaInvalida("o ranking não devolveu uma lista")
            itens += lote
            if len(lote) < pedido:
                break
        return itens[:quantidade]

    def appids_por_id(self, gids: list[str]) -> dict[str, list[int]]:
        """id do jogo no ITAD -> appids da Steam candidatos, em ordem crescente (`sub/<n>` são pacotes e ficam de fora).

        Um mesmo jogo do ITAD pode ter mais de um `app/<n>` (edições, jogo e demo): ver `appid_principal`.
        """
        saida: dict[str, list[int]] = {}
        for i in range(0, len(gids), 200):
            dados = self._pedir("POST", f"/lookup/shop/{STEAM}/id/v1", json=gids[i : i + 200])
            if not isinstance(dados, dict):
                raise RespostaInvalida("o lookup não devolveu um objeto")
            for gid, lojas in dados.items():
                apps = sorted(
                    {int(str(x)[4:]) for x in (lojas or []) if str(x).startswith("app/") and str(x)[4:].isdigit()}
                )
                if apps:
                    saida[str(gid)] = apps
        return saida

    def appid_principal(self, gid: str) -> int | None:
        """O appid que o próprio ITAD considera o do jogo (`/games/info/v2`), ou None se ele não informa."""
        info = self._pedir("GET", "/games/info/v2", params={"id": gid})
        if not isinstance(info, dict):
            raise RespostaInvalida("o info não devolveu um objeto")
        appid = info.get("appid")
        return int(appid) if isinstance(appid, int) and not isinstance(appid, bool) else None

    def historico_bruto(self, gid: str, pais: str = "BR", desde: str = DESDE_PADRAO) -> object:
        """JSON como a API devolveu. É o que se guarda em disco: os dados não são alterados."""
        return self._pedir(
            "GET", "/games/history/v2", params={"id": gid, "country": pais, "shops": [STEAM], "since": desde}
        )

    def historico(self, gid: str, pais: str = "BR", desde: str = DESDE_PADRAO) -> HistoricoJogo:
        """Mudanças de preço do jogo na Steam desde `desde` (padrão da API: só 3 meses; aqui, desde 2005)."""
        return parsear_historico(self.historico_bruto(gid, pais, desde), gid)
