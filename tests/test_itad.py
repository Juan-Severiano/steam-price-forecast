from datetime import datetime, timezone

import httpx
import numpy as np
import pytest

from steam_forecast.env import ChaveITAD
from steam_forecast.itad import (
    ChaveRecusada,
    ClienteITAD,
    RespostaInvalida,
    parsear_historico,
    retry_after_segundos,
)
from steam_forecast.steam import LimiteExcedido

SEGREDO = "chave-secreta-do-itad"
GID = "018d937e-f835-710c-b95b-928e277b187e"


@pytest.mark.parametrize("valor,esperado", [("0", 0), (" 2 ", 2), ("", None), ("-1", None), ("errado", None)])
def test_retry_after_segundos_ou_ausente(valor, esperado):
    assert retry_after_segundos(valor) == esperado


def test_retry_after_data_http_e_data_passada():
    agora = datetime(2026, 11, 3, 16, 0, 0, tzinfo=timezone.utc)
    assert retry_after_segundos("Tue, 03 Nov 2026 16:00:02 GMT", agora) == 2
    assert retry_after_segundos("Tue, 03 Nov 2026 15:59:59 GMT", agora) == 0


def _evento(quando, preco=19.99, regular=24.99, corte=20, moeda="BRL"):
    deal = None
    if preco is not None:
        deal = {
            "price": {"amount": preco, "amountInt": round(preco * 100), "currency": moeda},
            "regular": {"amount": regular, "amountInt": round(regular * 100), "currency": moeda},
            "cut": corte,
        }
    return {"timestamp": quando, "shop": {"id": 61, "name": "Steam"}, "deal": deal}


def _epoch(*args):
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


def test_parseia_eventos_com_fuso_e_com_z():
    h = parsear_historico(
        [_evento("2024-11-21T17:00:03+01:00"), _evento("2024-12-05T18:00:00Z", 24.99, 24.99, 0)], GID
    )
    assert h.gid == GID and h.moeda == "BRL"
    assert list(h.ts) == [_epoch(2024, 11, 21, 16, 0, 3), _epoch(2024, 12, 5, 18)]
    assert list(h.preco) == [19.99, 24.99] and list(h.regular) == [24.99, 24.99]
    assert list(h.desconto) == [20, 0]


def test_ordena_quando_a_api_devolve_do_mais_novo_para_o_mais_antigo():
    h = parsear_historico([_evento("2024-12-05T18:00:00Z", 24.99, 24.99, 0), _evento("2024-11-21T17:00:00Z")], GID)
    assert list(h.preco) == [19.99, 24.99]


def test_deal_nulo_vira_nan_jogo_fora_da_loja():
    h = parsear_historico([_evento("2024-01-01T00:00:00Z"), _evento("2024-02-01T00:00:00Z", preco=None)], GID)
    assert np.isnan(h.preco[1]) and np.isnan(h.desconto[1]) and h.preco[0] == 19.99


def test_lista_vazia_e_um_historico_sem_eventos():
    h = parsear_historico([], GID)
    assert h.ts.size == 0 and h.moeda == ""


@pytest.mark.parametrize(
    "ruim",
    [
        {"timestamp": "ontem", "shop": {}, "deal": None},
        {"shop": {}, "deal": None},
        {"timestamp": "2024-01-01T00:00:00Z", "shop": {}},
        {"timestamp": "2024-01-01T00:00:00Z", "shop": {}, "deal": {"price": {"amount": "x"}, "regular": {}, "cut": 0}},
        _evento("2024-01-01T00:00:00Z", preco=-1),
        _evento("2024-01-01T00:00:00Z", corte=150),
    ],
)
def test_formato_inesperado_falha_alto(ruim):
    with pytest.raises(RespostaInvalida):
        parsear_historico([ruim], GID)


def test_mais_de_uma_moeda_falha():
    with pytest.raises(RespostaInvalida):
        parsear_historico([_evento("2024-01-01T00:00:00Z"), _evento("2024-02-01T00:00:00Z", moeda="USD")], GID)


@pytest.mark.parametrize("campo", ["price", "regular", "cut"])
@pytest.mark.parametrize("valor", [float("nan"), float("inf"), float("-inf")])
def test_numero_nao_finito_da_api_e_rejeitado(campo, valor):
    evento = _evento("2024-01-01T00:00:00Z")
    if campo == "cut":
        evento["deal"][campo] = valor
    else:
        evento["deal"][campo]["amount"] = valor
    with pytest.raises(RespostaInvalida, match="não finito"):
        parsear_historico([evento], GID)


def test_resposta_que_nao_e_lista_falha():
    with pytest.raises(RespostaInvalida):
        parsear_historico({"erro": 1}, GID)


def _cliente(handler):
    return ClienteITAD(ChaveITAD(SEGREDO), transport=httpx.MockTransport(handler))


def test_historico_pede_desde_2005_so_da_steam_e_manda_a_chave_no_cabecalho():
    visto = {}

    def handler(req: httpx.Request):
        visto["url"] = str(req.url)
        visto["params"] = req.url.params
        visto["chave"] = req.headers.get("itad-api-key")
        return httpx.Response(200, json=[_evento("2024-11-21T17:00:03Z")])

    h = _cliente(handler).historico(GID, pais="BR")
    assert h.preco[0] == 19.99
    assert visto["chave"] == SEGREDO
    assert SEGREDO not in visto["url"]
    assert visto["params"]["id"] == GID and visto["params"]["country"] == "BR"
    assert visto["params"].get_list("shops") == ["61"]
    assert visto["params"]["since"].startswith("2005-")


@pytest.mark.parametrize("status", [401, 403])
def test_chave_recusada(status):
    cliente = _cliente(lambda req: httpx.Response(status, json={"reason_phrase": "x"}))
    with pytest.raises(ChaveRecusada) as erro:
        cliente.historico(GID)
    assert SEGREDO not in str(erro.value)


def test_429_devolve_o_retry_after():
    cliente = _cliente(lambda req: httpx.Response(429, headers={"Retry-After": "90"}))
    with pytest.raises(LimiteExcedido) as erro:
        cliente.buscar("stardew")
    assert erro.value.retry_after == 90


def test_erro_de_servidor_nao_vaza_a_chave():
    cliente = _cliente(lambda req: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError) as erro:
        cliente.historico(GID)
    assert SEGREDO not in str(erro.value)


def test_ids_por_appid_mapeia_e_descarta_o_que_o_itad_nao_conhece():
    corpos = []

    def handler(req: httpx.Request):
        import json

        corpos.append(json.loads(req.content))
        return httpx.Response(200, json={"app/413150": GID, "app/999999999": None})

    ids = _cliente(handler).ids_por_appid([413150, 999999999])
    assert ids == {413150: GID}
    assert corpos == [["app/413150", "app/999999999"]]


def test_ids_por_appid_divide_em_lotes_de_200():
    tamanhos = []

    def handler(req: httpx.Request):
        import json

        corpo = json.loads(req.content)
        tamanhos.append(len(corpo))
        return httpx.Response(200, json={c: "g" for c in corpo})

    ids = _cliente(handler).ids_por_appid(list(range(1, 451)))
    assert tamanhos == [200, 200, 50] and len(ids) == 450


def test_lookup_com_resposta_que_nao_e_objeto_falha():
    with pytest.raises(RespostaInvalida):
        _cliente(lambda req: httpx.Response(200, json=[])).ids_por_appid([1])


def test_buscar_devolve_a_lista():
    cliente = _cliente(lambda req: httpx.Response(200, json=[{"id": GID, "title": "Stardew Valley"}]))
    assert cliente.buscar("stardew")[0]["title"] == "Stardew Valley"
