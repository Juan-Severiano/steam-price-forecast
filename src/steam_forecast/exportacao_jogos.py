"""Catálogo para abrir no navegador localmente, sem incluir dados reais no site."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from steam_forecast.itad import parsear_historico
from steam_forecast.series_jogos import SerieJogo

EPOCA = date(1970, 1, 1)


def data_iso(dia: int) -> str:
    return (EPOCA + timedelta(days=int(dia))).isoformat()


def _numero(valor: float) -> float | None:
    return round(float(valor), 4) if np.isfinite(valor) else None


def _appid(valor: object) -> int:
    if isinstance(valor, bool) or not isinstance(valor, (int, str)):
        raise ValueError("appid deve ser um inteiro positivo")
    appid = int(valor)
    if appid < 1:
        raise ValueError("appid deve ser um inteiro positivo")
    return appid


def catalogo_local(
    series: Sequence[SerieJogo], previsoes: dict[int, list[dict]], *, dias_historico: int = 365
) -> dict:
    """Exporta fechamento diário e previsões já calculadas, mantendo lacunas como null."""
    if dias_historico < 1:
        raise ValueError("dias_historico deve ser positivo")
    por_horizonte = {str(h): {p["appid"]: p for p in ps} for h, ps in previsoes.items()}
    jogos = []
    for s in sorted(series, key=lambda x: x.titulo.casefold()):
        if not s.dias.size:
            continue
        inicio = max(0, len(s.dias) - dias_historico)
        previsoes_jogo = {}
        disponivel = np.isfinite(s.preco[-1]) and s.preco[-1] > 0
        for h, por_id in por_horizonte.items():
            if not disponivel:
                continue
            if s.appid in por_id:
                p = por_id[s.appid]
                if p.get("data_base") != data_iso(s.dias[-1]):
                    raise ValueError(f"previsão do appid {s.appid} usa outra data-base")
                previsoes_jogo[h] = {k: v for k, v in p.items() if k != "appid"}
        jogos.append({
            "appid": s.appid,
            "titulo": s.titulo,
            "data_base": data_iso(s.dias[-1]),
            "preco_atual": _numero(s.preco[-1]),
            "preco_regular": _numero(s.regular[-1]),
            "desconto_atual": _numero(s.desconto[-1]),
            "historico": [
                {"data": data_iso(d), "preco": _numero(p), "regular": _numero(r)}
                for d, p, r in zip(s.dias[inicio:], s.preco[inicio:], s.regular[inicio:])
            ],
            "previsoes": previsoes_jogo,
        })
    return {
        "schema_version": 1,
        "modo": "local",
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fonte": "IsThereAnyDeal · histórico Steam BRL; fechamento diário, não cotação ao vivo",
        "moeda": "BRL",
        "alvo": "chance de preço menor que o da data-base; quantis do menor preço incluindo a opção de comprar na data-base",
        "jogos": jogos,
    }


def estado_coleta(universo: Path, destino: Path) -> dict:
    """Confere os IDs esperados, integridade do cache e históricos sem eventos."""
    jogos = json.loads(universo.read_text(encoding="utf-8"))
    if not isinstance(jogos, list):
        raise ValueError("universo deve conter uma lista de jogos")
    esperados: dict[int, str] = {}
    for j in jogos:
        try:
            appid, gid = _appid(j["appid"]), j["gid"]
            if not isinstance(gid, str) or not gid:
                raise ValueError("gid deve ser uma string não vazia")
            if appid in esperados and esperados[appid] != gid:
                raise ValueError(f"appid {appid} associado a gids diferentes")
            esperados[appid] = gid
        except (KeyError, TypeError, ValueError) as erro:
            raise ValueError(f"universo inválido: {erro}") from erro
    presentes: set[int] = set()
    vazios: list[int] = []
    invalidos: list[str] = []
    ultima_coleta = None
    for appid, gid in esperados.items():
        caminho = destino / f"{appid}.json"
        if not caminho.is_file():
            continue
        try:
            corpo = json.loads(caminho.read_text(encoding="utf-8"))
            if _appid(corpo["appid"]) != appid or corpo["gid"] != gid:
                raise ValueError("identidade do arquivo difere do universo")
            historico = parsear_historico(corpo["bruto"], gid, appid)
            coletado = datetime.fromisoformat(corpo["coletado_em"].replace("Z", "+00:00"))
            if coletado.tzinfo is None:
                raise ValueError("coletado_em sem fuso")
            if historico.moeda and historico.moeda != "BRL":
                raise ValueError("moeda diferente de BRL")
            presentes.add(appid)
            if not historico.ts.size:
                vazios.append(appid)
            if ultima_coleta is None or coletado > ultima_coleta:
                ultima_coleta = coletado
        except (OSError, KeyError, TypeError, ValueError, AttributeError) as erro:
            invalidos.append(f"{appid}: {erro}")
    faltantes = sorted(set(esperados) - presentes)
    return {
        "universo": len(esperados),
        "validos": len(presentes),
        "sem_eventos": len(vazios),
        "faltantes": len(faltantes),
        "appids_faltantes": faltantes,
        "invalidos": invalidos,
        "ultima_coleta": ultima_coleta.isoformat() if ultima_coleta else None,
        "completa": not faltantes and not invalidos,
    }
