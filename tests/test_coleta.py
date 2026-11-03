import httpx
import pytest

from steam_forecast.coleta import caminho_do_item, coletar, listar_historicos
from steam_forecast.limitador import Limitador
from steam_forecast.steam import HistoricoInvalido, LimiteExcedido, SessaoExpirada

BRUTO = {
    "success": True,
    "price_prefix": "R$",
    "price_suffix": "",
    "prices": [["Nov 01 2013 01: +0", 1.5, "10"], ["Nov 02 2013 01: +0", 2.0, "4"]],
}


class ClienteFalso:
    """Devolve, em ordem, o que `respostas` tiver; exceção é levantada, o resto é devolvido."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas: list[str] = []

    def historico(self, appid, nome):
        self.chamadas.append(nome)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _itens(*nomes):
    return [{"appid": 730, "nome": n} for n in nomes]


def _coletar(cliente, itens, destino, **kw):
    kw.setdefault("log", lambda _msg: None)
    kw.setdefault("dormir", lambda _s: None)
    return coletar(cliente, itens, destino, Limitador(0.0), **kw)


def test_baixa_grava_e_a_segunda_rodada_pula(tmp_path):
    cliente = ClienteFalso([BRUTO, BRUTO])
    resumo = _coletar(cliente, _itens("A", "B"), tmp_path)
    assert (resumo.baixados, resumo.ja_existiam) == (2, 0)

    de_novo = _coletar(ClienteFalso([]), _itens("A", "B"), tmp_path)
    assert (de_novo.baixados, de_novo.ja_existiam) == (0, 2)
    assert sorted(h.nome for h in listar_historicos(tmp_path)) == ["A", "B"]


def test_atualizar_baixa_de_novo(tmp_path):
    _coletar(ClienteFalso([BRUTO]), _itens("A"), tmp_path)
    resumo = _coletar(ClienteFalso([BRUTO]), _itens("A"), tmp_path, atualizar=True)
    assert resumo.baixados == 1


def test_max_itens_conta_so_os_baixados(tmp_path):
    _coletar(ClienteFalso([BRUTO]), _itens("A"), tmp_path)
    cliente = ClienteFalso([BRUTO, BRUTO, BRUTO])
    resumo = _coletar(cliente, _itens("A", "B", "C", "D"), tmp_path, max_itens=2)
    assert resumo.baixados == 2 and resumo.ja_existiam == 1
    assert cliente.chamadas == ["B", "C"]


def test_sessao_recusada_para_e_guarda_o_que_ja_veio(tmp_path):
    cliente = ClienteFalso([BRUTO, SessaoExpirada("HTTP 403"), BRUTO])
    resumo = _coletar(cliente, _itens("A", "B", "C"), tmp_path)
    assert resumo.baixados == 1
    assert "sessão recusada" in resumo.interrompida_por
    assert cliente.chamadas == ["A", "B"]
    assert [h.nome for h in listar_historicos(tmp_path)] == ["A"]


def test_429_espera_e_tenta_de_novo_no_mesmo_item(tmp_path):
    dormiu = []
    cliente = ClienteFalso([LimiteExcedido(None), BRUTO])
    resumo = _coletar(cliente, _itens("A"), tmp_path, dormir=dormiu.append)
    assert resumo.baixados == 1
    assert dormiu == [300]
    assert cliente.chamadas == ["A", "A"]


def test_429_respeita_o_retry_after_quando_maior(tmp_path):
    dormiu = []
    _coletar(ClienteFalso([LimiteExcedido(1000), BRUTO]), _itens("A"), tmp_path, dormir=dormiu.append)
    assert dormiu == [1000]


def test_429_persistente_interrompe_sem_gravar(tmp_path):
    respostas = [LimiteExcedido(None)] * 4
    resumo = _coletar(ClienteFalso(respostas), _itens("A", "B"), tmp_path, espera_429=(1, 2, 3))
    assert resumo.baixados == 0
    assert "429" in resumo.interrompida_por
    assert list(listar_historicos(tmp_path)) == []


def test_resposta_invalida_vira_falha_e_nao_grava(tmp_path):
    cliente = ClienteFalso([{"success": False}, BRUTO])
    resumo = _coletar(cliente, _itens("A", "B"), tmp_path)
    assert resumo.baixados == 1
    assert [nome for nome, _ in resumo.falhas] == ["A"]
    assert resumo.interrompida_por is None


def test_erro_de_rede_vira_falha(tmp_path):
    cliente = ClienteFalso([httpx.ConnectError("sem rede"), BRUTO])
    resumo = _coletar(cliente, _itens("A", "B"), tmp_path)
    assert resumo.baixados == 1 and len(resumo.falhas) == 1


def test_falhas_seguidas_interrompem(tmp_path):
    cliente = ClienteFalso([HistoricoInvalido("x")] * 3 + [BRUTO])
    resumo = _coletar(cliente, _itens("A", "B", "C", "D"), tmp_path, falhas_seguidas_max=3)
    assert resumo.baixados == 0
    assert "3 falhas seguidas" in resumo.interrompida_por


def test_caminhos_distintos_para_nomes_que_colidem_no_nome_seguro(tmp_path):
    a = caminho_do_item(tmp_path, 730, "A|B")
    b = caminho_do_item(tmp_path, 730, "A B")
    assert a != b
    assert a.parent == tmp_path / "730"
    assert "|" not in a.name and " " not in a.name


@pytest.mark.parametrize("nome", ["StatTrak™ AK-47 | Redline (Field-Tested)", "../../fora"])
def test_nome_estranho_nao_escapa_do_destino(tmp_path, nome):
    assert tmp_path in caminho_do_item(tmp_path, 730, nome).parents
