import json

import numpy as np
import pytest

from steam_forecast.exportacao_jogos import catalogo_local, data_iso, estado_coleta
from steam_forecast.series_jogos import SerieJogo


def _serie(precos=(100, 80, 60), *, appid=10, titulo="Jogo"):
    p = np.asarray(precos, dtype=float)
    return SerieJogo(
        appid, f"g{appid}", titulo, "BRL", np.arange(20000, 20000 + len(p)),
        p, np.where(np.isfinite(p), 100, np.nan), np.where(np.isfinite(p), 100 - p, np.nan),
    )


def _previsao(s, *, horizonte=30):
    return {
        "appid": s.appid, "data_base": data_iso(s.dias[-1]), "horizonte": horizonte,
        "modelo": "gradient boosting", "probabilidade_desconto": 0.6,
        "preco_minimo_p10": 20.0, "preco_minimo_p50": 40.0, "preco_minimo_p90": 60.0,
    }


def _evento(preco=50, *, moeda="BRL"):
    deal = None if preco is None else {
        "price": {"amount": preco, "currency": moeda},
        "regular": {"amount": 100, "currency": moeda}, "cut": 100 - preco,
    }
    return {"timestamp": "2024-01-01T12:00:00Z", "deal": deal}


def _cache(tmp_path, *, jogos=None, appid=10, gid="g10", eventos=None, coletado_em="2024-01-03T00:00:00Z"):
    universo = tmp_path / "universo.json"
    universo.write_text(json.dumps(jogos if jogos is not None else [{"appid": 10, "gid": "g10"}]))
    destino = tmp_path / "historico"
    destino.mkdir(exist_ok=True)
    caminho = destino / "10.json"
    caminho.write_text(json.dumps({
        "appid": appid, "gid": gid, "coletado_em": coletado_em,
        "bruto": eventos if eventos is not None else [_evento()],
    }))
    return universo, destino, caminho


def test_catalogo_e_json_estrito_e_preserva_lacuna_com_null():
    s = _serie([100, np.nan, 60])
    catalogo = catalogo_local([s], {})
    reaberto = json.loads(json.dumps(catalogo, allow_nan=False))
    jogo = reaberto["jogos"][0]
    assert jogo["historico"][1] == {"data": data_iso(20001), "preco": None, "regular": None}
    assert jogo["preco_atual"] == 60
    assert jogo["previsoes"] == {}


def test_ultima_data_visivel_e_data_base_da_previsao_sao_iguais():
    s = _serie([100, 80, 60, 40])
    jogo = catalogo_local([s], {30: [_previsao(s)]}, dias_historico=2)["jogos"][0]
    assert [p["data"] for p in jogo["historico"]] == [data_iso(20002), data_iso(20003)]
    assert jogo["data_base"] == jogo["historico"][-1]["data"] == jogo["previsoes"]["30"]["data_base"]
    assert "appid" not in jogo["previsoes"]["30"]


def test_previsao_de_outra_data_e_rejeitada():
    s = _serie()
    p = {**_previsao(s), "data_base": data_iso(s.dias[-1] - 1)}
    with pytest.raises(ValueError, match="appid 10.*data-base"):
        catalogo_local([s], {30: [p]})


@pytest.mark.parametrize("ultimo", [np.nan, np.inf, 0])
def test_sem_previsao_quando_preco_atual_nao_sustenta_alvo(ultimo):
    s = _serie([100, ultimo])
    jogo = catalogo_local([s], {30: [_previsao(s)]})["jogos"][0]
    assert jogo["previsoes"] == {}
    json.dumps(jogo, allow_nan=False)


def test_horizonte_ausente_nao_e_inventado_e_serie_vazia_e_omitida():
    s = _serie()
    jogo = catalogo_local([s, _serie([], appid=20)], {90: [_previsao(s, horizonte=90)]})["jogos"]
    assert len(jogo) == 1
    assert set(jogo[0]["previsoes"]) == {"90"}


def test_exportar_nao_muda_series_ou_previsoes():
    s = _serie([100, np.nan, 60])
    originais = [v.copy() for v in (s.dias, s.preco, s.regular, s.desconto)]
    p = {30: [_previsao(s)]}
    p_antes = json.dumps(p)
    catalogo_local([s], p, dias_historico=1)
    for antes, depois in zip(originais, (s.dias, s.preco, s.regular, s.desconto)):
        np.testing.assert_equal(antes, depois)
    assert json.dumps(p) == p_antes


@pytest.mark.parametrize("dias", [0, -1])
def test_recorte_invalido_e_rejeitado(dias):
    with pytest.raises(ValueError, match="positivo"):
        catalogo_local([_serie()], {}, dias_historico=dias)


def test_cache_completo_expoe_ultima_coleta_e_nao_altera_arquivos(tmp_path):
    universo, destino, caminho = _cache(tmp_path)
    original = caminho.read_bytes()
    resultado = estado_coleta(universo, destino)
    assert resultado == {
        "universo": 1, "validos": 1, "sem_eventos": 0, "faltantes": 0,
        "appids_faltantes": [], "invalidos": [], "ultima_coleta": "2024-01-03T00:00:00+00:00", "completa": True,
    }
    assert caminho.read_bytes() == original


def test_cache_faltante_e_identificado(tmp_path):
    universo, destino, _ = _cache(tmp_path, jogos=[{"appid": 10, "gid": "g10"}, {"appid": 20, "gid": "g20"}])
    resultado = estado_coleta(universo, destino)
    assert resultado["validos"] == 1
    assert resultado["faltantes"] == 1 and resultado["appids_faltantes"] == [20]
    assert not resultado["completa"]


@pytest.mark.parametrize("alteracao", [
    {"appid": 20}, {"gid": "outro"}, {"appid": 10.5}, {"appid": True},
    {"coletado_em": "ontem"}, {"coletado_em": "2024-01-03T00:00:00"},
    {"bruto": {}}, {"bruto": [_evento(moeda="USD")]},
])
def test_cache_invalido_nao_conta_como_concluido(tmp_path, alteracao):
    universo, destino, caminho = _cache(tmp_path)
    corpo = json.loads(caminho.read_text())
    corpo.update(alteracao)
    caminho.write_text(json.dumps(corpo))
    resultado = estado_coleta(universo, destino)
    assert resultado["validos"] == 0 and resultado["appids_faltantes"] == [10]
    assert len(resultado["invalidos"]) == 1 and resultado["invalidos"][0].startswith("10:")
    assert not resultado["completa"]


def test_cache_json_corrompido_nao_conta_como_concluido(tmp_path):
    universo, destino, caminho = _cache(tmp_path)
    caminho.write_text("{")
    resultado = estado_coleta(universo, destino)
    assert resultado["validos"] == 0 and resultado["faltantes"] == 1
    assert resultado["invalidos"] and not resultado["completa"]


def test_historico_vazio_e_cache_valido_mas_sem_eventos(tmp_path):
    universo, destino, _ = _cache(tmp_path, eventos=[])
    resultado = estado_coleta(universo, destino)
    assert resultado["validos"] == resultado["sem_eventos"] == 1
    assert resultado["completa"] and not resultado["invalidos"]


def test_universo_com_appid_associado_a_dois_gids_e_rejeitado(tmp_path):
    universo, destino, _ = _cache(tmp_path, jogos=[{"appid": 10, "gid": "g10"}, {"appid": 10, "gid": "outro"}])
    with pytest.raises(ValueError, match="appid 10.*gids diferentes"):
        estado_coleta(universo, destino)


@pytest.mark.parametrize("jogos", [{"appid": 10}, [{"appid": False, "gid": "g"}], [{"appid": 10.5, "gid": "g"}], [{"appid": 10, "gid": None}]])
def test_universo_invalido_e_rejeitado(tmp_path, jogos):
    universo, destino, _ = _cache(tmp_path, jogos=jogos)
    with pytest.raises(ValueError, match="universo"):
        estado_coleta(universo, destino)
