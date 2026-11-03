import base64
import json
from datetime import datetime, timezone

import pytest

from steam_forecast.env import (
    ChaveAusente,
    ChaveITAD,
    Cookie,
    CookieAusente,
    avisos,
    carregar_chave_itad,
    carregar_cookie,
    ler_dotenv,
)

SEGREDO = "valor-secreto-123"


def test_le_so_os_dois_nomes_do_arquivo(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        f"# comentario\nSTEAM_LOGIN_SECURE={SEGREDO}\nSTEAM_SESSIONID='abc'\nOUTRA_COISA=nao-deve-ler\n",
        encoding="utf-8",
    )
    assert ler_dotenv(env) == {"STEAM_LOGIN_SECURE": SEGREDO, "STEAM_SESSIONID": "abc"}


def test_arquivo_ausente_nao_quebra(tmp_path):
    assert ler_dotenv(tmp_path / "nao-existe.env") == {}


def test_ambiente_vence_o_arquivo(tmp_path):
    env = tmp_path / ".env"
    env.write_text("STEAM_LOGIN_SECURE=do-arquivo\n", encoding="utf-8")
    cookie = carregar_cookie(env, ambiente={"STEAM_LOGIN_SECURE": "do-ambiente"})
    assert cookie.login_secure == "do-ambiente"


def test_sem_cookie_levanta_sem_vazar_nada(tmp_path):
    with pytest.raises(CookieAusente) as erro:
        carregar_cookie(tmp_path / ".env", ambiente={})
    assert "STEAM_LOGIN_SECURE" in str(erro.value)


def test_cookie_vazio_conta_como_ausente(tmp_path):
    env = tmp_path / ".env"
    env.write_text("STEAM_LOGIN_SECURE=\n", encoding="utf-8")
    with pytest.raises(CookieAusente):
        carregar_cookie(env, ambiente={})


def test_repr_e_str_nao_mostram_o_valor():
    cookie = Cookie(login_secure=SEGREDO, sessionid="sessao-secreta")
    assert SEGREDO not in repr(cookie)
    assert "sessao-secreta" not in repr(cookie)
    assert SEGREDO not in str(cookie)


def test_cabecalho_inclui_sessionid_so_quando_existe():
    assert Cookie(login_secure="a").cabecalho() == "steamLoginSecure=a"
    assert Cookie(login_secure="a", sessionid="b").cabecalho() == "steamLoginSecure=a; sessionid=b"


def test_chave_do_itad_vem_do_arquivo_e_o_ambiente_vence(tmp_path):
    env = tmp_path / ".env"
    env.write_text("STEAM_LOGIN_SECURE=x\nITAD_API_KEY=do-arquivo\n", encoding="utf-8")
    assert carregar_chave_itad(env, ambiente={}).valor == "do-arquivo"
    assert carregar_chave_itad(env, ambiente={"ITAD_API_KEY": "do-ambiente"}).valor == "do-ambiente"


def test_sem_chave_do_itad_levanta_sem_vazar_nada(tmp_path):
    with pytest.raises(ChaveAusente) as erro:
        carregar_chave_itad(tmp_path / ".env", ambiente={})
    assert "ITAD_API_KEY" in str(erro.value)


def test_repr_da_chave_do_itad_nao_mostra_o_valor():
    assert "segredo-do-itad" not in repr(ChaveITAD(valor="segredo-do-itad"))


AGORA = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
DEPOIS = int(datetime(2026, 11, 4, tzinfo=timezone.utc).timestamp())
ANTES = int(datetime(2026, 11, 2, tzinfo=timezone.utc).timestamp())


def _login(**afirmacoes) -> Cookie:
    """Token só com a forma de um steamLoginSecure: '<id>%7C%7C<cabeçalho>.<payload>.<assinatura>'."""

    def b64(dados: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(dados).encode()).decode().rstrip("=")

    jwt = f"{b64({'alg': 'x'})}.{b64(afirmacoes)}.assinatura"
    return Cookie(login_secure=f"76561198000000000%7C%7C{jwt}")


def test_avisa_que_o_cookie_e_da_loja():
    problemas = avisos(_login(aud=["web:store"], exp=DEPOIS), AGORA)
    assert len(problemas) == 1 and "loja" in problemas[0] and "steamcommunity.com" in problemas[0]


def test_cookie_da_comunidade_valido_nao_tem_aviso():
    assert avisos(_login(aud=["web:community"], exp=DEPOIS), AGORA) == []


def test_avisa_cookie_vencido():
    problemas = avisos(_login(aud=["web:community"], exp=ANTES), AGORA)
    assert len(problemas) == 1 and "venceu" in problemas[0]


def test_avisa_valor_com_forma_errada():
    assert "forma" in avisos(Cookie(login_secure="abc"), AGORA)[0]
    assert "forma" in avisos(Cookie(login_secure="765%7C%7Cnao-e-jwt"), AGORA)[0]


def test_aviso_nao_vaza_id_nem_ip_do_token():
    cookie = _login(aud=["web:store"], exp=ANTES, sub="76561198999999999", ip_subject="203.0.113.7")
    texto = "\n".join(avisos(cookie, AGORA))
    for segredo in ("76561198999999999", "76561198000000000", "203.0.113.7", cookie.login_secure):
        assert segredo not in texto
