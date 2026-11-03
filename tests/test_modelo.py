import numpy as np
import pytest

pytest.importorskip("sklearn")

from steam_forecast.atributos import (  # noqa: E402
    NOMES,
    NOMES_PROPRIOS,
    T_MIN,
    fatores_de_mercado,
    montar_painel,
    proprios,
)
from steam_forecast.modelo import (  # noqa: E402
    REFERENCIA,
    Configuracao,
    executar,
    plano_de_dobras,
    prever,
    prever_agora,
    prever_referencia_agora,
    resumir,
    selecionar_treino,
    tabela_markdown,
)
from steam_forecast.series import SerieDiaria  # noqa: E402


def _serie(logp, dia0=20000, volume=50):
    logp = np.asarray(logp, dtype=float)
    return SerieDiaria("x", dia0, logp, np.full(logp.size, volume, dtype=np.int64))


def _passeio(n, seed, sigma=0.02):
    return 3.0 + np.cumsum(np.random.default_rng(seed).normal(0, sigma, n))


def _momentum(n, seed, phi=0.97, sigma=0.01):
    """Retornos diários com forte autocorrelação: o retorno recente prevê o próximo."""
    ruido = np.random.default_rng(seed).normal(0, sigma, n)
    r = np.zeros(n)
    for i in range(1, n):
        r[i] = phi * r[i - 1] + ruido[i]
    return 3.0 + np.cumsum(r)


def _cfg(dia0, **kw):
    padrao = dict(horizonte=7, inicio_teste=dia0 + 700, retreino=250, iteracoes=40, min_por_folha=50, passo_treino=3)
    return Configuracao(**{**padrao, **kw})


def test_atributos_do_item_em_t_nao_dependem_do_futuro():
    logp = _passeio(600, 1)
    t0 = 400
    antes = proprios(_serie(logp), 7)[: t0 + 1]
    mexido = logp.copy()
    mexido[t0 + 1 :] += np.random.default_rng(9).normal(0, 5, logp.size - t0 - 1)
    depois = proprios(_serie(mexido), 7)[: t0 + 1]
    assert np.allclose(antes, depois, equal_nan=True)


def test_fatores_de_mercado_em_um_dia_nao_dependem_do_futuro():
    a, b = _serie(_passeio(500, 1), dia0=20000), _serie(_passeio(500, 2), dia0=20100)
    corte = 20350  # dia absoluto: nada depois dele pode mexer em dias <= corte
    ini, antes = fatores_de_mercado([a, b])
    mexido = _passeio(500, 1)
    mexido[corte - 20000 + 1 :] += 7.0
    ini2, depois = fatores_de_mercado([_serie(mexido, dia0=20000), b])
    assert ini == ini2
    n = corte - ini + 1
    assert np.allclose(antes[:n], depois[:n], equal_nan=True)


def test_painel_alinha_rotulo_escala_e_linhas():
    series = [_serie(_passeio(400, 1), dia0=20000), _serie(_passeio(500, 2), dia0=20123)]
    h = 7
    painel = montar_painel(series, h)
    assert painel.X.shape[1] == len(NOMES)
    item, t = np.array([0, 0, 1, 1]), np.array([T_MIN, 250, T_MIN, 300])
    linhas = painel.linha(item, t)
    assert np.array_equal(painel.item[linhas], item) and np.array_equal(painel.t[linhas], t)
    assert np.array_equal(painel.dia[linhas], np.array([20000, 20000, 20123, 20123]) + t)
    for i, ti, ln in zip(item, t, linhas):
        logp = series[i].log_preco
        assert painel.r[ln] == pytest.approx(logp[ti + h] - logp[ti])
        assert painel.escala[ln] > 0
    ultimas = painel.linha(np.array([0]), np.array([400 - 1]))
    assert np.isnan(painel.r[ultimas]).all()  # sem futuro ainda
    assert NOMES_PROPRIOS[0] == "ret_1"


def test_treino_so_com_alvo_ja_conhecido():
    series = [_serie(_passeio(500, 1), dia0=20000), _serie(_passeio(500, 2), dia0=20123)]
    painel = montar_painel(series, 30)
    limite = 20400
    linhas = selecionar_treino(painel, limite, 30, passo_treino=2)
    assert linhas.size > 0
    assert (painel.dia[linhas] + 30 <= limite).all()
    assert not np.isnan(painel.r[linhas]).any()


def test_walk_forward_nao_depende_do_que_vem_depois():
    dias0 = (20000, 20050, 20100)
    series = [_serie(_momentum(900, s), dia0=d) for s, d in enumerate(dias0)]
    cfg = Configuracao(horizonte=7, inicio_teste=20700, retreino=100, iteracoes=20, min_por_folha=50, passo_treino=3)
    limite_dobra = 20700 + 100  # a primeira dobra prevê origens em [20700, 20800)
    antes = prever(series, cfg)

    mexidas = []
    for s in series:
        logp = s.log_preco.copy()
        primeiro_mexido = limite_dobra + cfg.horizonte + 3 - s.dia0  # depois do último alvo da dobra
        logp[primeiro_mexido:] += np.random.default_rng(3).normal(0, 4, logp.size - primeiro_mexido)
        mexidas.append(_serie(logp, dia0=s.dia0))
    depois = prever(mexidas, cfg)

    na_dobra = antes.dia < limite_dobra
    assert na_dobra.sum() > 20
    for nome in antes.previsoes:
        assert np.allclose(antes.previsoes[nome][na_dobra], depois.previsoes[nome][na_dobra], equal_nan=True), nome


def test_quantis_do_modelo_saem_ordenados():
    series = [_serie(_passeio(900, s), dia0=20000 + 30 * s) for s in range(4)]
    p = prever(series, _cfg(20000))
    for nome, pred in p.previsoes.items():
        assert not np.isnan(pred).any(), nome
        assert (np.diff(pred, axis=1) >= -1e-12).all(), nome


def test_o_modelo_aprende_um_sinal_que_existe():
    series = [_serie(_momentum(1300, s), dia0=20000) for s in range(12)]
    r = resumir(prever(series, _cfg(20000, inicio_teste=20850, retreino=500, iteracoes=80)))
    for nome in ("GB quantílico (só o item)", "GB quantílico (item + mercado)"):
        assert r["modelos"][nome]["vs_referencia"] < -0.05, (nome, r["modelos"][nome]["vs_referencia"])


def test_o_modelo_nao_inventa_sinal_num_passeio_aleatorio():
    series = [_serie(_passeio(1300, s), dia0=20000) for s in range(12)]
    r = resumir(prever(series, _cfg(20000, inicio_teste=20850, retreino=500, iteracoes=80)))
    for nome in ("GB quantílico (só o item)", "GB quantílico (item + mercado)"):
        assert r["modelos"][nome]["vs_referencia"] > -0.05, (nome, r["modelos"][nome]["vs_referencia"])


def test_prever_agora_devolve_quantis_ordenados_e_nan_para_serie_curta():
    series = [_serie(_passeio(900, s), dia0=20000 + 30 * s) for s in range(4)] + [_serie(_passeio(50, 9))]
    pred = prever_agora(series, 7, cfg=_cfg(20000))
    assert pred.shape == (5, 3)
    assert np.isfinite(pred[:4]).all() and (np.diff(pred[:4], axis=1) >= -1e-12).all()
    assert np.isnan(pred[4]).all()


def test_prever_agora_enxerga_o_momentum_do_ultimo_dia():
    series = [_serie(_momentum(1300, s), dia0=20000) for s in range(12)]
    pred = prever_agora(series, 7, cfg=_cfg(20000, iteracoes=80))
    ret_7 = np.array([s.log_preco[-1] - s.log_preco[-8] for s in series])
    assert np.corrcoef(pred[:, 1], ret_7)[0, 1] > 0.5


def test_referencia_agora_tem_quantis_ordenados():
    series = [_serie(_passeio(900, s)) for s in range(3)] + [_serie(_passeio(50, 9))]
    ref = prever_referencia_agora(series, 7)
    assert (np.diff(ref[:3], axis=1) >= 0).all() and np.isnan(ref[3]).all()


def test_plano_de_dobras_bate_com_o_walk_forward():
    series = [_serie(_passeio(900, s), dia0=20000 + 20 * s) for s in range(4)]
    cfg = _cfg(20000, retreino=100)  # com retreino de 250 sobra uma dobra só e a comparação do treino não faz sentido
    plano = plano_de_dobras(series, cfg)
    previsto = prever(series, cfg)
    assert sum(d["teste"] for d in plano) == previsto.real.size
    assert [d["dobra"] for d in plano] == list(range(1, len(plano) + 1))
    assert all(d["treino"] > 0 for d in plano) and plano[0]["treino"] < plano[-1]["treino"]


def test_resumo_e_tabela():
    series = [_serie(_passeio(900, s), dia0=20000 + 20 * s) for s in range(4)]
    r = executar(series, _cfg(20000))
    assert r["modelos"][REFERENCIA]["vs_referencia"] == 0
    assert r["modelos"][REFERENCIA]["itens_melhores"] is None
    assert r["itens"] == 4 and r["dobras"] >= 1
    tabela = tabela_markdown(r)
    assert "GB quantílico (item + mercado)" in tabela and "Horizonte 7 dias" in tabela and "| Ano |" in tabela


def test_sem_origem_de_teste_devolve_vazio():
    series = [_serie(_passeio(500, 1))]
    r = executar(series, _cfg(20000, inicio_teste=30000))
    assert r["itens"] == 0 and "sem origens" in tabela_markdown(r)
