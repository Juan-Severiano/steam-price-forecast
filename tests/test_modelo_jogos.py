from dataclasses import replace

import numpy as np
import pytest

pytest.importorskip("sklearn")

from steam_forecast.modelo_jogos import (  # noqa: E402
    ATUAL, ESTADO, GERAL, JOGO, JOGO_ESTADO, ML, ConfiguracaoJogos, NOMES, atributos_jogo,
    executar_jogos, montar_painel_jogos, prever_avaliacao_jogos,
    prever_jogos_agora, selecionar_treino_jogos, tabela_markdown_jogos,
)
from steam_forecast.series_jogos import SerieJogo  # noqa: E402


def _serie(precos, appid=1, dia0=18000):
    p = np.asarray(precos, dtype=float)
    return SerieJogo(
        appid=appid, gid=str(appid), titulo=f"Jogo {appid}", moeda="BRL",
        dias=np.arange(dia0, dia0 + p.size), preco=p,
        regular=np.full(p.size, 100.0), desconto=100 - p,
    )


def _periodica(n=1100, appid=1):
    t = np.arange(n)
    fase = (t + appid * 11) % 70
    return _serie(np.where(fase < 7, 50.0, 100.0), appid)


def _cfg(**kw):
    padrao = dict(horizonte=14, inicio_teste=18700, min_historia=120, retreino=200, passo=7, iteracoes=30, min_por_folha=10)
    return ConfiguracaoJogos(**{**padrao, **kw})


def test_atributos_nao_veem_precos_nem_cortes_futuros():
    s = _periodica(600)
    posicoes = np.array([120, 220, 360, 420])
    antes = atributos_jogo(s, posicoes)
    precos, regular, desconto = s.preco.copy(), s.regular.copy(), s.desconto.copy()
    precos[421:], regular[421:], desconto[421:] = 7, 29, 76
    depois = atributos_jogo(replace(s, preco=precos, regular=regular, desconto=desconto), posicoes)
    assert antes.shape == (4, len(NOMES))
    np.testing.assert_allclose(antes, depois, equal_nan=True)


def test_alvo_inclui_hoje_e_exclui_indisponibilidade_e_origem_gratis():
    s = _serie([100, 80, 120, 0, 100, np.nan, 100, 90, 110, 100])
    p = montar_painel_jogos([s], _cfg(horizonte=2, min_historia=1, passo=1))
    assert p.dia.tolist() == [18000, 18001, 18002, 18006, 18007]
    np.testing.assert_allclose(p.razao, [0.8, 0, 0, 0.9, 1.0])
    assert p.baixou.tolist() == [True, True, True, True, False]


def test_treino_usa_so_alvos_completos_no_corte():
    p = montar_painel_jogos([_periodica()], _cfg())
    treino = selecionar_treino_jogos(p, 18600, 14)
    assert treino.size > 30
    assert np.max(p.dia[treino] + 14) <= 18600
    assert (p.dia[np.setdiff1d(np.arange(p.dia.size), treino)] + 14 > 18600).all()


def test_primeira_dobra_inteira_nao_muda_com_futuro_posterior():
    series = [_periodica(appid=i + 1) for i in range(3)]
    cfg = _cfg(retreino=100, iteracoes=10)
    antes = prever_avaliacao_jogos(series, cfg)
    mexidas = []
    for s in series:
        precos = s.preco.copy()
        precos[815:] = np.where(np.arange(precos.size - 815) % 3, 20, 90)
        mexidas.append(replace(s, preco=precos, desconto=100 - precos))
    depois = prever_avaliacao_jogos(mexidas, cfg)
    primeiro = antes.dia < 18800
    assert primeiro.sum() > 30
    np.testing.assert_array_equal(antes.dia, depois.dia)
    for nome in antes.probabilidades:
        np.testing.assert_allclose(antes.probabilidades[nome][primeiro], depois.probabilidades[nome][primeiro])
        np.testing.assert_allclose(antes.quantis[nome][primeiro], depois.quantis[nome][primeiro])


def test_aprende_promocao_periodica_com_avaliacao_temporal():
    series = [_periodica(appid=i + 1) for i in range(8)]
    resultado = executar_jogos(series, _cfg(retreino=400, iteracoes=60))
    modelos = resultado["modelos"]
    assert resultado["jogos"] == 8
    assert resultado["origens"] > 300
    assert modelos[ML]["brier"] < 0.65 * modelos[JOGO]["brier"]
    assert modelos[ML]["pinball"] < modelos[GERAL]["pinball"]
    assert resultado["por_jogo"] and resultado["por_ano"]
    assert "gradient boosting" in tabela_markdown_jogos(resultado)


def test_reguas_com_estado_sabem_que_quem_ja_esta_em_promocao_nao_cai_mais():
    series = [_periodica(appid=i + 1) for i in range(4)]
    p = prever_avaliacao_jogos(series, _cfg(retreino=400, iteracoes=10))
    em_promocao = p.preco < 100  # na série periódica, 50 é o preço da promoção
    assert em_promocao.sum() > 10 and (~em_promocao).sum() > 10
    for regua in (ESTADO, JOGO_ESTADO):
        assert (p.probabilidades[regua][em_promocao] == 0).all(), regua  # nunca baixou mais de 50
        assert (p.probabilidades[regua][~em_promocao] > 0).all(), regua
    # a régua que ignora o estado dá chance positiva até a quem já está no preço mais baixo
    assert (p.probabilidades[JOGO][em_promocao] > 0).all()


def test_com_estado_a_regua_melhora_mas_o_ml_ainda_ganha_nesta_serie():
    series = [_periodica(appid=i + 1) for i in range(8)]
    modelos = executar_jogos(series, _cfg(retreino=400, iteracoes=60))["modelos"]
    assert modelos[ESTADO]["brier"] < modelos[JOGO]["brier"]  # nesta série, só um pouco: a promoção é rara
    assert modelos[ML]["brier"] < modelos[JOGO_ESTADO]["brier"]
    assert modelos[ML]["brier_vs_jogo_estado"] < 0 < modelos[JOGO]["brier_vs_jogo_estado"]


def test_uma_classe_e_preco_constante_nao_exigem_duas_classes():
    s = _serie(np.full(800, 100))
    cfg = _cfg(inicio_teste=18500, retreino=400)
    p = prever_avaliacao_jogos([s], cfg)
    for nome in p.probabilidades:
        np.testing.assert_array_equal(p.probabilidades[nome], 0)
        np.testing.assert_array_equal(p.quantis[nome], 1)
    resultado = executar_jogos([s], cfg)
    assert resultado["modelos"][ML]["brier"] == 0
    assert resultado["modelos"][ML]["pinball_vs_frequencia"] is None
    assert resultado["modelos"][ATUAL]["cobertura"] == 1


def test_previsoes_atuais_limitadas_ordenadas_e_sem_series_curtas():
    series = [_periodica(appid=i + 1) for i in range(3)] + [_serie([100] * 30, appid=99)]
    previsoes = prever_jogos_agora(series, 14, cfg=_cfg(iteracoes=10))
    assert len(previsoes) == 3
    for pred in previsoes:
        assert pred["appid"] != 99
        assert 0 <= pred["probabilidade_desconto"] <= 1
        preco = series[pred["appid"] - 1].preco[-1]
        assert 0 <= pred["preco_minimo_p10"] <= pred["preco_minimo_p50"] <= pred["preco_minimo_p90"] <= preco
        assert pred["data_base"] == "2022-04-17"


def test_cache_antigo_nao_usa_futuro_de_outro_jogo_no_treino():
    antigo = _periodica(700, 1)
    novo = _periodica(900, 2)
    cfg = _cfg(iteracoes=10)
    antes = prever_jogos_agora([antigo, novo], 14, cfg=cfg)
    precos = novo.preco.copy()
    precos[700:] = 1
    depois = prever_jogos_agora([antigo, replace(novo, preco=precos, desconto=100 - precos)], 14, cfg=cfg)
    assert antes[0] == depois[0]
    assert antes[0]["data_base"] < antes[1]["data_base"]


def test_sem_dados_suficientes_devolve_resultado_vazio():
    cfg = _cfg()
    r = executar_jogos([_serie([100] * 100)], cfg)
    assert r["origens"] == r["jogos"] == 0
    assert "sem origens" in tabela_markdown_jogos(r)
    assert prever_jogos_agora([], 14, cfg=cfg) == []
    assert executar_jogos([_periodica()], _cfg(min_amostras=10000))["origens"] == 0


@pytest.mark.parametrize("campo,valor", [("horizonte", 0), ("passo", -1), ("retreino", 0), ("min_historia", True)])
def test_rejeita_configuracao_invalida(campo, valor):
    with pytest.raises(ValueError, match=campo):
        _cfg(**{campo: valor})


def test_rejeita_dias_nao_consecutivos():
    s = _periodica()
    dias = s.dias.copy()
    dias[10] += 1
    with pytest.raises(ValueError, match="consecutivos"):
        montar_painel_jogos([replace(s, dias=dias)], _cfg())


def test_horizonte_agora_deve_corresponder_a_configuracao():
    with pytest.raises(ValueError, match="horizonte"):
        prever_jogos_agora([], 30, cfg=_cfg(horizonte=14))
