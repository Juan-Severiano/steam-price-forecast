import json
from datetime import datetime

import numpy as np
import pytest

from steam_forecast.itad import parsear_historico
from steam_forecast.series_jogos import carregar_series_jogos, diaria_jogo


def _evento(quando, preco=100, regular=100, moeda="BRL"):
    deal = None if preco is None else {
        "price": {"amount": preco, "currency": moeda},
        "regular": {"amount": regular, "currency": moeda},
        "cut": 100 * (1 - preco / regular),
    }
    return {"timestamp": quando, "deal": deal}


def _data(texto):
    return datetime.fromisoformat(texto.replace("Z", "+00:00"))


def _diaria(eventos, coletado_em="2024-01-05T15:00:00Z"):
    return diaria_jogo(parsear_historico(eventos, "jogo", appid=10, titulo="Jogo"), _data(coletado_em))


def _dias(*textos):
    return [int(_data(f"{t}T00:00:00Z").timestamp() // 86400) for t in textos]


def _gravar(tmp_path, eventos, *, coletado_em="2024-01-05T15:00:00Z", appid=10):
    caminho = tmp_path / f"{appid}.json"
    caminho.write_text(json.dumps({
        "appid": appid, "gid": "jogo", "titulo": "Jogo",
        "coletado_em": coletado_em, "bruto": eventos,
    }), encoding="utf-8")
    return caminho


def test_fechamento_intradiario_nao_antecipa_o_desconto_nos_dias_anteriores():
    s = _diaria([
        _evento("2024-01-01T12:00:00Z"),
        _evento("2024-01-03T18:00:00Z", 50),
        _evento("2024-01-03T21:00:00Z", 40),
    ])
    assert s.dias.tolist() == _dias("2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04")
    assert s.preco.tolist() == [100, 100, 40, 40]
    assert s.desconto.tolist() == [0, 0, 60, 60]
    assert (s.appid, s.gid, s.titulo, s.moeda) == (10, "jogo", "Jogo", "BRL")


def test_meia_noite_pertence_ao_novo_dia_em_utc():
    s = _diaria([
        _evento("2024-01-01T20:00:00-03:00", 100),
        _evento("2024-01-01T21:00:00-03:00", 50),
    ], "2024-01-02T21:30:00-03:00")
    assert s.dias.tolist() == _dias("2024-01-01", "2024-01-02")
    assert s.preco.tolist() == [100, 50]


def test_indisponibilidade_permanece_nan_ate_nova_oferta():
    s = _diaria([
        _evento("2024-01-01T00:00:00Z", 100),
        _evento("2024-01-02T12:00:00Z", None),
        _evento("2024-01-04T15:00:00Z", 70),
    ])
    np.testing.assert_equal(s.preco, [100, np.nan, np.nan, 70])
    np.testing.assert_equal(s.regular, [100, np.nan, np.nan, 100])
    assert np.isnan(s.desconto[1:3]).all()


def test_corta_dia_da_coleta_e_eventos_futuros_sem_estender_cache():
    s = _diaria([
        _evento("2024-01-02T12:00:00Z", 100),
        _evento("2024-01-05T10:00:00Z", 50),
        _evento("2024-02-01T00:00:00Z", 25),
    ])
    assert s.dias.tolist() == _dias("2024-01-02", "2024-01-03", "2024-01-04")
    assert s.preco.tolist() == [100, 100, 100]


def test_nao_preenche_antes_do_primeiro_evento():
    s = _diaria([_evento("2024-01-03T23:59:59Z", 50)])
    assert s.dias.tolist() == _dias("2024-01-03", "2024-01-04")
    assert s.preco.tolist() == [50, 50]


def test_serie_de_um_dia_e_valida():
    s = _diaria([_evento("2024-01-04T23:59:59Z", 50)])
    assert s.preco.tolist() == [50]


@pytest.mark.parametrize("eventos", [[], [_evento("2024-01-05T10:00:00Z")], [_evento("2024-02-01T00:00:00Z")]])
def test_sem_dias_completos_retorna_none(eventos):
    assert _diaria(eventos) is None


def test_ordena_timestamps_estavelmente_e_nao_muda_historico():
    h = parsear_historico([
        _evento("2024-01-01T12:00:00Z", 100),
        _evento("2024-01-02T12:00:00Z", 70),
        _evento("2024-01-02T12:00:00Z", 50),
    ], "jogo", appid=10)
    # O parser já ordena; montar uma entrada fora de ordem exercita a função diária.
    ordem = [1, 2, 0]
    h.ts[:] = h.ts[ordem]
    h.preco[:] = h.preco[ordem]
    h.regular[:] = h.regular[ordem]
    h.desconto[:] = h.desconto[ordem]
    ts_antes, precos_antes = h.ts.copy(), h.preco.copy()
    s = diaria_jogo(h, _data("2024-01-03T00:00:00Z"))
    assert s.preco.tolist() == [100, 50]
    np.testing.assert_equal(h.ts, ts_antes)
    np.testing.assert_equal(h.preco, precos_antes)


def test_data_sem_fuso_e_rejeitada():
    h = parsear_historico([_evento("2024-01-01T12:00:00Z")], "jogo", appid=10)
    with pytest.raises(ValueError, match="fuso"):
        diaria_jogo(h, datetime(2024, 1, 5))


def test_carrega_cache_ate_data_individual_e_pula_historico_vazio(tmp_path):
    _gravar(tmp_path, [_evento("2024-01-01T12:00:00Z")], coletado_em="2024-01-03T00:00:00Z", appid=10)
    _gravar(tmp_path, [_evento("2024-01-01T12:00:00Z")], coletado_em="2024-01-04T00:00:00Z", appid=20)
    _gravar(tmp_path, [], appid=30)
    _gravar(tmp_path, [_evento("2024-01-01T12:00:00Z", None)], appid=40)
    series = carregar_series_jogos(tmp_path)
    assert [s.appid for s in series] == [10, 20]
    assert [len(s.dias) for s in series] == [2, 3]


def test_moeda_diferente_nao_e_misturada_a_brl(tmp_path):
    _gravar(tmp_path, [_evento("2024-01-01T12:00:00Z", moeda="USD")])
    with pytest.raises(ValueError, match="appid 10.*USD.*BRL"):
        carregar_series_jogos(tmp_path)


@pytest.mark.parametrize("alteracao", [
    {"coletado_em": "ontem"},
    {"coletado_em": "2024-01-05T00:00:00"},
    {"bruto": {"erro": "resposta inesperada"}},
])
def test_erro_do_cache_identifica_o_appid(tmp_path, alteracao):
    caminho = _gravar(tmp_path, [_evento("2024-01-01T12:00:00Z")])
    corpo = json.loads(caminho.read_text())
    corpo.update(alteracao)
    caminho.write_text(json.dumps(corpo))
    with pytest.raises(ValueError, match="appid 10.*10.json"):
        carregar_series_jogos(tmp_path)
