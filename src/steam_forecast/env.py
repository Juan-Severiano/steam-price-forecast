"""Cookie da Steam: lido do ambiente ou de um .env local.

O valor nunca é impresso, registrado em log nem repetido em mensagem de erro.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

LOGIN = "STEAM_LOGIN_SECURE"
SESSAO = "STEAM_SESSIONID"
ITAD = "ITAD_API_KEY"
NOMES = (LOGIN, SESSAO, ITAD)


class CookieAusente(RuntimeError):
    pass


@dataclass(frozen=True)
class Cookie:
    # repr=False: um print ou traceback do objeto não mostra o valor.
    login_secure: str = field(repr=False)
    sessionid: str | None = field(default=None, repr=False)

    def cabecalho(self) -> str:
        partes = [f"steamLoginSecure={self.login_secure}"]
        if self.sessionid:
            partes.append(f"sessionid={self.sessionid}")
        return "; ".join(partes)


def ler_dotenv(caminho: Path) -> dict[str, str]:
    """Lê só os dois nomes que o projeto usa; qualquer outra linha do arquivo é ignorada."""
    valores: dict[str, str] = {}
    if not caminho.is_file():
        return valores
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        nome, _, valor = linha.partition("=")
        nome = nome.strip()
        if nome in NOMES:
            valores[nome] = valor.strip().strip('"').strip("'")
    return valores


def carregar_cookie(
    caminho_env: Path | None = None, ambiente: Mapping[str, str] | None = None
) -> Cookie:
    """Variável de ambiente vence o arquivo. Sem STEAM_LOGIN_SECURE, levanta CookieAusente."""
    ambiente = os.environ if ambiente is None else ambiente
    do_arquivo = ler_dotenv(caminho_env) if caminho_env is not None else {}

    def valor(nome: str) -> str | None:
        return ambiente.get(nome) or do_arquivo.get(nome) or None

    login = valor(LOGIN)
    if not login:
        onde = f" nem em {caminho_env}" if caminho_env is not None else ""
        raise CookieAusente(f"{LOGIN} não está definido no ambiente{onde}. Veja .env.example.")
    return Cookie(login_secure=login, sessionid=valor(SESSAO))


def _afirmacoes(login_secure: str) -> dict | None:
    """Payload do JWT que vem depois de `<id>%7C%7C`. Quem chama só deve olhar `aud` e `exp`."""
    try:
        payload = login_secure.split("%7C%7C", 1)[1].split(".")[1]
        dados = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return None
    return dados if isinstance(dados, dict) else None


def avisos(cookie: Cookie, agora: datetime | None = None) -> list[str]:
    """Problemas visíveis no cookie sem chamar a Steam.

    Só lê `aud` e `exp`; o id da conta e o IP que o token carrega não são lidos nem impressos.
    """
    dados = _afirmacoes(cookie.login_secure)
    if dados is None:
        return [
            "o STEAM_LOGIN_SECURE não tem a forma '<id>%7C%7C<token>': "
            "confira se copiou o valor inteiro, sem espaço nem aspas"
        ]
    saida: list[str] = []
    aud = dados.get("aud")
    aud = [aud] if isinstance(aud, str) else list(aud or [])
    if "web:store" in aud and "web:community" not in aud:
        saida.append(
            "este cookie é da loja (store.steampowered.com), não da comunidade: "
            "copie o steamLoginSecure de steamcommunity.com"
        )
    exp = dados.get("exp")
    if isinstance(exp, (int, float)):
        agora = agora or datetime.now(timezone.utc)
        if datetime.fromtimestamp(exp, tz=timezone.utc) <= agora:
            saida.append("o cookie já venceu: entre de novo na Steam no navegador e copie o valor novo")
    return saida


class ChaveAusente(RuntimeError):
    pass


@dataclass(frozen=True)
class ChaveITAD:
    # repr=False: um print ou traceback do objeto não mostra o valor.
    valor: str = field(repr=False)


def carregar_chave_itad(
    caminho_env: Path | None = None, ambiente: Mapping[str, str] | None = None
) -> ChaveITAD:
    """Variável de ambiente vence o arquivo. Sem ITAD_API_KEY, levanta ChaveAusente."""
    ambiente = os.environ if ambiente is None else ambiente
    do_arquivo = ler_dotenv(caminho_env) if caminho_env is not None else {}
    valor = ambiente.get(ITAD) or do_arquivo.get(ITAD)
    if not valor:
        onde = f" nem em {caminho_env}" if caminho_env is not None else ""
        raise ChaveAusente(f"{ITAD} não está definido no ambiente{onde}. Veja .env.example.")
    return ChaveITAD(valor=valor)
