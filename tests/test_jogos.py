import json

import httpx
import pytest

from steam_forecast.env import ChaveITAD
from steam_forecast.itad import ChaveRecusada, ClienteITAD, RespostaInvalida
from steam_forecast.jogos import (
    caminho_do_jogo,
    coletar_jogos,
    listar_historicos_jogos,
    montar_universo,
)
from steam_forecast.steam import LimiteExcedido

BRUTO = [
    {
        "timestamp": "2024-01-01T00:00:00Z",
        "shop": {"id": 61, "name": "Steam"},
        "deal": {
            "price": {"amount": 12.49, "amountInt": 1249, "currency": "BRL"},
            "regular": {"amount": 24.99, "amountInt": 2499, "currency": "BRL"},
            "cut": 50,
        },
    }
]


def _cliente(handler):
    return ClienteITAD(ChaveITAD("segredo"), transport=httpx.MockTransport(handler))


def _item(gid, posicao, tipo="game", titulo=None):
    return {"id": gid, "position": posicao, "title": titulo or f"Jogo {gid}", "type": tipo, "slug": gid, "mature": False, "count": 1}


def test_ranking_pagina_de_500_em_500_e_para_no_fim():
    pedidos = []

    def handler(req: httpx.Request):
        limite, offset = int(req.url.params["limit"]), int(req.url.params["offset"])
        pedidos.append((limite, offset))
        restante = max(0, 700 - offset)
        return httpx.Response(200, json=[_item(f"g{offset + i}", offset + i + 1) for i in range(min(limite, restante))])

    itens = _cliente(handler).ranking("most-popular", 1500)
    assert len(itens) == 700
    assert pedidos == [(500, 0), (500, 500)]


def test_ranking_nunca_pede_mais_de_500_de_uma_vez():
    pedidos = []

    def handler(req: httpx.Request):
        pedidos.append(int(req.url.params["limit"]))
        return httpx.Response(200, json=[_item(f"g{i}", i) for i in range(int(req.url.params["limit"]))])

    _cliente(handler).ranking("most-collected", 1200)
    assert pedidos == [500, 500, 200]


def test_ranking_com_resposta_que_nao_e_lista_falha():
    with pytest.raises(RespostaInvalida):
        _cliente(lambda req: httpx.Response(200, json={})).ranking("most-popular", 10)


def test_appids_por_id_devolve_os_candidatos_ordenados_e_ignora_pacotes_e_desconhecidos():
    def handler(req: httpx.Request):
        return httpx.Response(
            200,
            json={"a": ["sub/1", "app/659", "sub/2", "app/620"], "b": ["sub/9"], "c": None, "d": ["app/413150"]},
        )

    assert _cliente(handler).appids_por_id(["a", "b", "c", "d"]) == {"a": [620, 659], "d": [413150]}


def test_appid_principal_vem_do_info_e_e_none_quando_falta():
    def handler(req: httpx.Request):
        assert req.url.path == "/games/info/v2"
        return httpx.Response(200, json={"appid": 620} if req.url.params["id"] == "a" else {"appid": None})

    cliente = _cliente(handler)
    assert cliente.appid_principal("a") == 620
    assert cliente.appid_principal("b") is None


def test_montar_universo_resolve_o_appid_ambiguo_pelo_info_e_cai_no_menor_sem_info():
    consultados = []

    def handler(req: httpx.Request):
        if req.url.path.startswith("/stats/"):
            return httpx.Response(200, json=[_item("g1", 1), _item("g2", 2), _item("g3", 3)])
        if req.url.path == "/games/info/v2":
            gid = req.url.params["id"]
            consultados.append(gid)
            return httpx.Response(200, json={"appid": {"g1": 231430}.get(gid)})
        return httpx.Response(200, json={"g1": ["app/55300", "app/231430"], "g2": ["app/10", "app/20"], "g3": ["app/30"]})

    universo = montar_universo(_cliente(handler), por_ranking=3)
    assert {j["gid"]: j["appid"] for j in universo} == {"g1": 231430, "g2": 10, "g3": 30}
    assert sorted(set(consultados)) == ["g1", "g2"]  # g3 tem um candidato só: nem pergunta


def test_montar_universo_junta_rankings_tira_dlc_e_ordena_pela_melhor_posicao():
    def handler(req: httpx.Request):
        if req.url.path == "/stats/most-popular/v1":
            return httpx.Response(200, json=[_item("g1", 1), _item("dlc", 2, tipo="dlc"), _item("g2", 3)])
        if req.url.path == "/stats/most-collected/v1":
            return httpx.Response(200, json=[_item("g3", 1), _item("g2", 2), _item("sem-steam", 3)])
        corpo = json.loads(req.content)
        mapa = {"g1": ["app/10"], "g2": ["app/20"], "g3": ["app/30"], "sem-steam": None, "dlc": None}
        return httpx.Response(200, json={g: mapa[g] for g in corpo})

    universo = montar_universo(_cliente(handler), por_ranking=3)
    assert [(j["gid"], j["appid"]) for j in universo] == [("g1", 10), ("g3", 30), ("g2", 20)]
    g2 = next(j for j in universo if j["gid"] == "g2")
    assert (g2["pos_popular"], g2["pos_colecionado"]) == (3, 2)
    assert all(j["gid"] != "dlc" for j in universo)


class ClienteFalso:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.gids: list[str] = []

    def historico_bruto(self, gid):
        self.gids.append(gid)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _jogos(*appids):
    return [{"appid": a, "gid": f"g{a}", "titulo": f"Jogo {a}"} for a in appids]


def _coletar(cliente, jogos, destino, **kw):
    kw.setdefault("log", lambda _m: None)
    kw.setdefault("dormir", lambda _s: None)
    return coletar_jogos(cliente, jogos, destino, **kw)


def test_baixa_grava_o_bruto_e_a_segunda_rodada_pula(tmp_path):
    r = _coletar(ClienteFalso([BRUTO, BRUTO]), _jogos(1, 2), tmp_path)
    assert (r.baixados, r.ja_existiam) == (2, 0)
    de_novo = _coletar(ClienteFalso([]), _jogos(1, 2), tmp_path)
    assert (de_novo.baixados, de_novo.ja_existiam) == (0, 2)
    corpo = json.loads(caminho_do_jogo(tmp_path, 1).read_text(encoding="utf-8"))
    assert corpo["bruto"] == BRUTO and corpo["appid"] == 1 and corpo["gid"] == "g1"
    assert sorted(h.appid for h in listar_historicos_jogos(tmp_path)) == [1, 2]


def test_max_jogos_conta_so_os_baixados(tmp_path):
    _coletar(ClienteFalso([BRUTO]), _jogos(1), tmp_path)
    cliente = ClienteFalso([BRUTO, BRUTO, BRUTO])
    r = _coletar(cliente, _jogos(1, 2, 3, 4), tmp_path, max_jogos=2)
    assert r.baixados == 2 and r.ja_existiam == 1 and cliente.gids == ["g2", "g3"]


def test_chave_recusada_para_e_guarda_o_que_ja_veio(tmp_path):
    r = _coletar(ClienteFalso([BRUTO, ChaveRecusada("HTTP 401"), BRUTO]), _jogos(1, 2, 3), tmp_path)
    assert r.baixados == 1 and "chave recusada" in r.interrompida_por
    assert [h.appid for h in listar_historicos_jogos(tmp_path)] == [1]


def test_429_espera_o_maior_entre_retry_after_e_a_tabela_e_tenta_de_novo(tmp_path):
    dormiu = []
    r = _coletar(ClienteFalso([LimiteExcedido(1000), LimiteExcedido(None), BRUTO]), _jogos(1), tmp_path, dormir=dormiu.append)
    assert r.baixados == 1 and dormiu == [1000, 900]


def test_429_persistente_interrompe_sem_gravar(tmp_path):
    r = _coletar(ClienteFalso([LimiteExcedido(None)] * 4), _jogos(1, 2), tmp_path, espera_429=(1, 2, 3))
    assert r.baixados == 0 and "429" in r.interrompida_por
    assert list(listar_historicos_jogos(tmp_path)) == []


def test_resposta_invalida_vira_falha_e_nao_grava(tmp_path):
    r = _coletar(ClienteFalso([{"nao": "lista"}, BRUTO]), _jogos(1, 2), tmp_path)
    assert r.baixados == 1 and [t for t, _ in r.falhas] == ["Jogo 1"] and r.interrompida_por is None


def test_falhas_seguidas_interrompem(tmp_path):
    r = _coletar(ClienteFalso([RespostaInvalida("x")] * 3 + [BRUTO]), _jogos(1, 2, 3, 4), tmp_path, falhas_seguidas_max=3)
    assert r.baixados == 0 and "3 falhas seguidas" in r.interrompida_por


def test_historico_sem_eventos_e_valido(tmp_path):
    r = _coletar(ClienteFalso([[]]), _jogos(1), tmp_path)
    assert r.baixados == 1
