import pytest

from steam_forecast.limitador import Limitador


class Relogio:
    def __init__(self):
        self.agora = 100.0
        self.dormiu: list[float] = []

    def __call__(self):
        return self.agora

    def dormir(self, segundos):
        self.dormiu.append(segundos)
        self.agora += segundos


def test_primeira_chamada_nao_espera_e_a_segunda_espera_o_intervalo():
    r = Relogio()
    lim = Limitador(5.0, relogio=r, dormir=r.dormir)
    assert lim.esperar() == 0
    assert lim.esperar() == pytest.approx(5.0)
    assert r.dormiu == [pytest.approx(5.0)]


def test_nao_espera_se_ja_passou_o_intervalo():
    r = Relogio()
    lim = Limitador(5.0, relogio=r, dormir=r.dormir)
    lim.esperar()
    r.agora += 20
    assert lim.esperar() == 0
    assert r.dormiu == []


def test_jitter_soma_ao_intervalo():
    r = Relogio()
    lim = Limitador(4.0, jitter_s=2.0, relogio=r, dormir=r.dormir, sorteio=lambda: 0.5)
    lim.esperar()
    assert lim.esperar() == pytest.approx(5.0)


def test_chamadas_seguidas_mantem_a_taxa():
    r = Relogio()
    lim = Limitador(5.0, relogio=r, dormir=r.dormir)
    inicio = r.agora
    for _ in range(4):
        lim.esperar()
    assert r.agora - inicio == pytest.approx(15.0)


def test_rejeita_valores_negativos():
    with pytest.raises(ValueError):
        Limitador(-1)
