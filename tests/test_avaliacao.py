import numpy as np
import pytest

from steam_forecast.avaliacao import (
    MODELOS,
    avaliar,
    filtrar_series,
    modelo_media_movel_erro,
    modelo_naive_erro,
    origens_validas,
    pinball,
    tabela_markdown,
)
from steam_forecast.series import DIA_S, SerieDiaria, diaria
from steam_forecast.steam import Historico


def _historico(dias, precos, volumes):
    return Historico(
        appid=730,
        nome="x",
        prefixo="R$",
        sufixo="",
        ts=np.asarray(dias, dtype=np.int64) * DIA_S + 3600,
        preco=np.asarray(precos, dtype=float),
        volume=np.asarray(volumes, dtype=np.int64),
    )


def _serie(logp, volume=5):
    logp = np.asarray(logp, dtype=float)
    return SerieDiaria("x", 0, logp, np.full(logp.size, volume, dtype=np.int64))


def _passeio(n, sigma=0.02, seed=1):
    return np.cumsum(np.random.default_rng(seed).normal(0, sigma, n)) + 3.0


def test_diaria_pondera_pelo_volume_repete_dias_sem_venda_e_descarta_o_ultimo():
    # dia 0: 2; dia 1: (4*1 + 8*3)/4 = 7; dia 2 sem venda; dia 3: 10; dia 4 e o ultimo, descartado
    h = _historico([0, 1, 1, 3, 4], [2, 4, 8, 10, 999], [1, 1, 3, 2, 1])
    s = diaria(h)
    assert np.allclose(np.exp(s.log_preco), [2, 7, 7, 10])
    assert list(s.volume) == [1, 4, 0, 2]
    assert s.dias_com_venda == 3


def test_diaria_com_um_unico_dia_nao_tem_serie():
    assert diaria(_historico([5, 5], [1, 2], [1, 1])) is None


def test_naive_com_erro_numa_serie_constante_tem_perda_zero():
    s = _serie(np.full(800, 2.0))
    r = avaliar([s], 7)
    m = r["modelos"]["naive + erro empírico"]
    assert m["pinball"] == pytest.approx(0)
    assert m["cobertura"] == 1.0
    assert m["largura"] == pytest.approx(0)


def test_pinball_de_previsao_perfeita_e_zero_e_de_erro_e_positiva():
    real = np.array([0.1, -0.2, 0.0])
    assert pinball(np.tile(real[:, None], (1, 3)), real) == 0
    assert pinball(np.zeros((3, 3)), real) > 0


@pytest.mark.parametrize("previsor", [modelo_naive_erro, modelo_media_movel_erro])
def test_previsao_em_t_nao_depende_do_futuro(previsor):
    logp = _passeio(900)
    h = 30
    t0 = 600
    origens = origens_validas(logp.size, h)
    ate_t0 = origens[origens <= t0]
    antes = previsor(logp, h, ate_t0)

    mexido = logp.copy()
    mexido[t0 + 1 :] += np.random.default_rng(9).normal(0, 5, logp.size - t0 - 1)
    depois = previsor(mexido, h, ate_t0)

    assert np.allclose(antes, depois, equal_nan=True)


def test_erro_so_usa_origens_cujo_alvo_ja_aconteceu():
    # Um salto em t+1 nao pode aparecer na previsao feita em t, nem nas origens s > t - h.
    logp = np.zeros(700)
    logp[400:] = 5.0  # salto no dia 400
    h = 30
    previsao = modelo_naive_erro(logp, h, np.array([420]))
    # em t=420 o salto de 400 so entrou no erro das origens s <= 390, que nao o contem: intervalo ainda zero
    assert np.allclose(previsao, 0)


def test_cobertura_de_um_passeio_aleatorio_fica_perto_de_80_por_cento():
    r = avaliar([_serie(_passeio(3000, sigma=0.02))], 7)
    cobertura = r["modelos"]["naive + erro empírico"]["cobertura"]
    assert 0.7 < cobertura < 0.9


def test_naive_pontual_nao_tem_intervalo():
    r = avaliar([_serie(_passeio(900))], 7)
    m = r["modelos"]["naive (pontual)"]
    assert m["cobertura"] is None and m["largura"] is None


def test_origens_respeitam_historia_minima_e_o_fim_da_serie():
    o = origens_validas(1000, 30, passo=7, historia_min=365)
    assert o[0] == 364
    assert o[-1] + 30 <= 999
    assert np.all(np.diff(o) == 7)
    assert origens_validas(300, 30).size == 0


def test_avaliar_sem_item_elegivel_devolve_vazio_e_a_tabela_avisa():
    r = avaliar([_serie(_passeio(100))], 7)
    assert r["itens"] == 0
    assert "sem itens elegíveis" in tabela_markdown(r)


def test_filtrar_series_por_historia_e_liquidez():
    longa_liquida = _serie(_passeio(600), volume=10)
    longa_rara = _serie(_passeio(600), volume=1)
    curta = _serie(_passeio(100), volume=10)
    assert filtrar_series([longa_liquida, longa_rara, curta]) == [longa_liquida]


def test_tabela_traz_todos_os_modelos():
    r = avaliar([_serie(_passeio(900))], 7)
    tabela = tabela_markdown(r)
    for m in MODELOS:
        assert m.nome in tabela
    assert "Horizonte 7 dias" in tabela
