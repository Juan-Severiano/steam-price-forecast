import json

import httpx
import pytest

from steam_forecast import cli


def _evento():
    return {
        "timestamp": "2024-01-01T12:00:00Z",
        "deal": {
            "price": {"amount": 50, "currency": "BRL"},
            "regular": {"amount": 100, "currency": "BRL"}, "cut": 50,
        },
    }


def _universo(tmp_path):
    universo = tmp_path / "universo.json"
    universo.write_text(json.dumps([
        {"appid": 10, "gid": "g10", "titulo": "Primeiro"},
        {"appid": 20, "gid": "g20", "titulo": "Segundo"},
    ]))
    dados = tmp_path / "historico"
    dados.mkdir()
    return universo, dados


def _gravar(dados, appid):
    (dados / f"{appid}.json").write_text(json.dumps({
        "appid": appid, "gid": f"g{appid}", "titulo": f"Jogo {appid}",
        "coletado_em": "2024-01-03T00:00:00Z", "bruto": [_evento()],
    }))


def test_status_distingue_coleta_parcial_completa_e_corrompida(tmp_path, capsys):
    universo, dados = _universo(tmp_path)
    _gravar(dados, 10)
    argumentos = ["jogos-status", "--universo", str(universo), "--dados", str(dados)]
    assert cli.main([*argumentos, "--detalhes"]) == 1
    parcial = json.loads(capsys.readouterr().out)
    assert parcial["appids_faltantes"] == [20]
    assert parcial["validos"] == 1 and not parcial["completa"]

    _gravar(dados, 20)
    assert cli.main(argumentos) == 0
    completa = json.loads(capsys.readouterr().out)
    assert completa["completa"] and completa["validos"] == 2
    assert "appids_faltantes" not in completa

    corrompido = dados / "10.json"
    corrompido.write_text("{")
    assert cli.main(argumentos) == 1
    estado = json.loads(capsys.readouterr().out)
    assert estado["faltantes"] == 1 and len(estado["invalidos"]) == 1
    assert corrompido.read_text() == "{"


def test_coleta_com_falha_isolada_preserva_sucesso_mas_retorna_erro(tmp_path, capsys, monkeypatch):
    universo, dados = _universo(tmp_path)

    class ClienteSimulado:
        fechado = False

        def historico_bruto(self, gid):
            if gid == "g10":
                raise httpx.ReadTimeout("falha temporária de rede")
            return [_evento()]

        def fechar(self):
            self.fechado = True

    cliente = ClienteSimulado()
    monkeypatch.setattr(cli, "_cliente_itad", lambda *_: cliente)
    codigo = cli.main(["jogos-coletar", "--universo", str(universo), "--destino", str(dados)])
    assert codigo == 1 and cliente.fechado
    assert not (dados / "10.json").exists()
    gravado = json.loads((dados / "20.json").read_text())
    assert gravado["appid"] == 20 and gravado["bruto"] == [_evento()]
    saida = capsys.readouterr()
    assert "baixados 1" in saida.out and "falhas 1" in saida.out
    assert "coleta incompleta" in saida.err


def test_avaliacao_sem_dados_grava_resultado_valido_e_retorna_erro(tmp_path, capsys):
    dados = tmp_path / "sem-historico"
    saida = tmp_path / "resultados" / "avaliacao.json"
    codigo = cli.main(["jogos-avaliar", "--dados", str(dados), "--saida", str(saida)])
    assert codigo == 1
    resultados = json.loads(saida.read_text())
    assert [r["horizonte"] for r in resultados] == [30, 90]
    assert all(r["origens"] == 0 and not r["modelos"] for r in resultados)
    assert "sem origens" in capsys.readouterr().out
    assert not saida.with_suffix(".json.tmp").exists()


def test_exportacao_sem_dados_nao_sobrescreve_catalogo_existente(tmp_path, capsys):
    saida = tmp_path / "catalogo.json"
    conteudo = '{"anterior":true}'
    saida.write_text(conteudo)
    codigo = cli.main(["jogos-exportar", "--dados", str(tmp_path / "ausente"), "--saida", str(saida)])
    assert codigo == 1
    assert saida.read_text() == conteudo
    assert "nenhuma série" in capsys.readouterr().err


@pytest.mark.parametrize("comando,opcao,valor", [
    ("jogos-avaliar", "--horizonte", "0"),
    ("jogos-avaliar", "--passo", "-1"),
    ("jogos-avaliar", "--retreino", "0"),
    ("jogos-avaliar", "--iteracoes", "0"),
    ("jogos-avaliar", "--historia-min", "0"),
    ("jogos-exportar", "--dias-historico", "-1"),
    ("jogos-exportar", "--horizonte", "-30"),
    ("jogos-exportar", "--iteracoes", "nan"),
    ("jogos-coletar", "--max-jogos", "0"),
    ("jogos-coletar", "--max-jogos", "-2"),
    ("jogos-coletar", "--intervalo", "-1"),
    ("jogos-coletar", "--intervalo", "nan"),
    ("jogos-coletar", "--intervalo", "inf"),
])
def test_argumentos_invalidos_falham_antes_de_ler_dados_ou_abrir_cliente(comando, opcao, valor, monkeypatch, capsys):
    def nao_deve_abrir_cliente(*_):
        pytest.fail("argumento inválido passou da validação")

    monkeypatch.setattr(cli, "_cliente_itad", nao_deve_abrir_cliente)
    with pytest.raises(SystemExit) as erro:
        cli.main([comando, opcao, valor])
    assert erro.value.code == 2
    assert opcao in capsys.readouterr().err
