import copy
from datetime import datetime, timezone

import httpx
import pytest

from steam_forecast.env import Cookie
from steam_forecast.steam import (
    ClienteSteam,
    HistoricoInvalido,
    LimiteExcedido,
    SessaoExpirada,
    parsear_historico,
)

BRUTO = {
    "success": True,
    "price_prefix": "R$",
    "price_suffix": "",
    "prices": [
        ["Nov 01 2013 01: +0", 1.5, "10"],
        ["Nov 02 2013 01: +0", 2.0, "4"],
    ],
}


def _epoch(*args):
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


def test_parseia_datas_precos_e_volumes():
    h = parsear_historico(BRUTO, 730, "AK-47 | Redline (Field-Tested)")
    assert h.appid == 730
    assert h.prefixo == "R$"
    assert list(h.ts) == [_epoch(2013, 11, 1, 1), _epoch(2013, 11, 2, 1)]
    assert list(h.preco) == [1.5, 2.0]
    assert list(h.volume) == [10, 4]


def test_ordena_quando_a_resposta_vem_fora_de_ordem():
    bruto = copy.deepcopy(BRUTO)
    bruto["prices"].reverse()
    h = parsear_historico(bruto, 730, "x")
    assert list(h.preco) == [1.5, 2.0]


@pytest.mark.parametrize(
    "mudar",
    [
        lambda b: b.update(success=False),
        lambda b: b.update(prices=[]),
        lambda b: b["prices"].append(["Foo 03 2013 01: +0", 1.0, "1"]),
        lambda b: b["prices"].append(["Nov 03 2013 01: +1", 1.0, "1"]),
        lambda b: b["prices"].append(["Nov 03 2013 01 +0", 1.0, "1"]),
        lambda b: b["prices"].append(["Nov 03 2013 01: +0", "x", "1"]),
        lambda b: b["prices"].append(["Nov 03 2013 01: +0", 1.0, "-4"]),
        lambda b: b["prices"].append(["Nov 03 2013 01: +0", float("nan"), "1"]),
        lambda b: b["prices"].append(["Nov 03 2013 01: +0", 1.0]),
    ],
)
def test_formato_inesperado_falha_alto(mudar):
    bruto = copy.deepcopy(BRUTO)
    mudar(bruto)
    with pytest.raises(HistoricoInvalido):
        parsear_historico(bruto, 730, "x")


def test_resposta_que_nao_e_dict_falha():
    with pytest.raises(HistoricoInvalido):
        parsear_historico([], 730, "x")


def _cliente(handler, cookie=Cookie(login_secure="SEGREDO", sessionid="SESSAO")):
    return ClienteSteam(cookie, transport=httpx.MockTransport(handler))


def test_historico_manda_o_cookie_e_os_parametros():
    visto = {}

    def handler(req: httpx.Request):
        visto["cookie"] = req.headers.get("cookie")
        visto["params"] = dict(req.url.params)
        return httpx.Response(200, json=BRUTO)

    assert _cliente(handler).historico(730, "AK-47 | Redline (Field-Tested)") == BRUTO
    assert visto["cookie"] == "steamLoginSecure=SEGREDO; sessionid=SESSAO"
    assert visto["params"] == {"appid": "730", "market_hash_name": "AK-47 | Redline (Field-Tested)"}


@pytest.mark.parametrize("status", [400, 401, 403])
def test_status_de_sessao_recusada(status):
    cliente = _cliente(lambda req: httpx.Response(status, json=[]))
    with pytest.raises(SessaoExpirada) as erro:
        cliente.historico(730, "x")
    assert "SEGREDO" not in str(erro.value)


@pytest.mark.parametrize("corpo", ["null", "false", "[]"])
def test_resposta_vazia_com_200_conta_como_sessao_recusada(corpo):
    # content=, não json=: httpx.Response(json=None) manda corpo vazio em vez de "null".
    cliente = _cliente(lambda req: httpx.Response(200, content=corpo))
    with pytest.raises(SessaoExpirada):
        cliente.historico(730, "x")


def test_corpo_que_nao_e_json_e_historico_invalido_e_nao_sessao_recusada():
    cliente = _cliente(lambda req: httpx.Response(200, content="<html>erro</html>"))
    with pytest.raises(HistoricoInvalido):
        cliente.historico(730, "x")


def test_429_devolve_o_retry_after():
    cliente = _cliente(lambda req: httpx.Response(429, headers={"Retry-After": "120"}))
    with pytest.raises(LimiteExcedido) as erro:
        cliente.historico(730, "x")
    assert erro.value.retry_after == 120


def test_429_sem_retry_after():
    cliente = _cliente(lambda req: httpx.Response(429))
    with pytest.raises(LimiteExcedido) as erro:
        cliente.historico(730, "x")
    assert erro.value.retry_after is None


def test_user_agent_identifica_o_projeto_e_nao_imita_navegador():
    vistos = []

    def handler(req: httpx.Request):
        vistos.append(req.headers["user-agent"])
        return httpx.Response(200, json=BRUTO)

    _cliente(handler).historico(730, "x")
    assert vistos == ["steam-price-forecast/0.1 (projeto pessoal de pesquisa)"]
    assert "Mozilla" not in vistos[0]


def test_sem_cookie_nem_chama_a_steam():
    chamadas = []
    cliente = ClienteSteam(None, transport=httpx.MockTransport(lambda r: chamadas.append(r) or httpx.Response(200)))
    with pytest.raises(SessaoExpirada):
        cliente.historico(730, "x")
    assert chamadas == []


def test_universo_pagina_sem_mandar_cookie():
    paginas = {
        "0": {
            "success": True,
            "total_count": 3,
            "results": [
                {"hash_name": "A", "sell_listings": 10, "sell_price": 100, "sell_price_text": "R$ 1,00"},
                {"hash_name": "B", "sell_listings": 5, "sell_price": 200, "sell_price_text": "R$ 2,00"},
            ],
        },
        "2": {
            "success": True,
            "total_count": 3,
            "results": [{"hash_name": "C", "sell_listings": 1, "sell_price": 300, "sell_price_text": "R$ 3,00"}],
        },
    }
    cookies = []

    def handler(req: httpx.Request):
        cookies.append(req.headers.get("cookie"))
        return httpx.Response(200, json=paginas[req.url.params["start"]])

    itens = _cliente(handler).universo(730, 3)
    assert [i["nome"] for i in itens] == ["A", "B", "C"]
    assert itens[0]["appid"] == 730 and itens[0]["anuncios"] == 10
    assert cookies == [None, None]


def test_universo_repete_a_pagina_em_429_e_depois_segue():
    pagina = {"success": True, "total_count": 1, "results": [{"hash_name": "A"}]}
    respostas = [httpx.Response(429), httpx.Response(200, json=pagina)]
    dormiu = []
    itens = _cliente(lambda req: respostas.pop(0)).universo(730, 1, espera_429=(7, 9), dormir=dormiu.append)
    assert [i["nome"] for i in itens] == ["A"]
    assert dormiu == [7]


def test_universo_com_429_persistente_levanta_depois_de_esperar():
    dormiu = []
    cliente = _cliente(lambda req: httpx.Response(429))
    with pytest.raises(LimiteExcedido):
        cliente.universo(730, 1, espera_429=(1, 2), dormir=dormiu.append)
    assert dormiu == [1, 2]


def test_universo_respeita_a_quantidade():
    resposta = {
        "success": True,
        "total_count": 5,
        "results": [{"hash_name": n} for n in "ABCDE"],
    }
    itens = _cliente(lambda req: httpx.Response(200, json=resposta)).universo(730, 2)
    assert [i["nome"] for i in itens] == ["A", "B"]
