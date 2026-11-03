"""Jogos da Steam: universo de jogos populares e coleta do histórico de preço, via IsThereAnyDeal.

Um arquivo por jogo em `data/jogos/historico/<appid>.json`, com o JSON bruto da API. Rodar de novo pula
o que já existe (a API pede cache e tem limite de 1.000 pedidos a cada 5 minutos).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path

import httpx

from steam_forecast.coleta import Resumo
from steam_forecast.itad import (
    ChaveRecusada,
    ClienteITAD,
    HistoricoJogo,
    RespostaInvalida,
    parsear_historico,
)
from steam_forecast.steam import LimiteExcedido

_SEM_POSICAO = 10**9
# Reserva para o 429 sem `Retry-After`, em segundos.
ESPERA_429_ITAD = (30, 120, 300)


def _imprimir(mensagem: str) -> None:
    print(mensagem, flush=True)  # sem flush, a saída de um processo em segundo plano só aparece no fim


def montar_universo(cliente: ClienteITAD, por_ranking: int = 1500) -> list[dict]:
    """Jogos que estão entre os mais populares ou os mais colecionados do ITAD e existem na Steam (appid)."""
    por_gid: dict[str, dict] = {}
    for origem, tipo in (("popular", "most-popular"), ("colecionado", "most-collected")):
        for item in cliente.ranking(tipo, por_ranking):
            if item.get("type") != "game":  # fora DLC, trilhas e pacotes
                continue
            registro = por_gid.setdefault(
                item["id"],
                {"gid": item["id"], "titulo": item.get("title", ""), "pos_popular": None, "pos_colecionado": None},
            )
            registro[f"pos_{origem}"] = item.get("position")
    candidatos = cliente.appids_por_id(list(por_gid))
    universo = []
    for gid, registro in por_gid.items():
        if gid not in candidatos:
            continue
        apps = candidatos[gid]
        appid = apps[0]
        if len(apps) > 1:  # edições, jogo e demo: pergunta ao ITAD qual é o principal; senão fica o menor
            principal = cliente.appid_principal(gid)
            appid = principal if principal in apps else apps[0]
        universo.append({**registro, "appid": appid})
    universo.sort(key=lambda r: min(p for p in (r["pos_popular"], r["pos_colecionado"], _SEM_POSICAO) if p is not None))
    return universo


def caminho_do_jogo(destino: Path, appid: int) -> Path:
    return destino / f"{int(appid)}.json"


def _gravar(alvo: Path, jogo: dict, bruto: object) -> None:
    alvo.parent.mkdir(parents=True, exist_ok=True)
    corpo = {
        "appid": int(jogo["appid"]),
        "gid": jogo["gid"],
        "titulo": jogo.get("titulo", ""),
        "coletado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bruto": bruto,
    }
    temporario = alvo.with_suffix(".json.tmp")
    temporario.write_text(json.dumps(corpo, ensure_ascii=False), encoding="utf-8")
    temporario.replace(alvo)


def coletar_jogos(
    cliente: ClienteITAD,
    jogos: Iterable[dict],
    destino: Path,
    *,
    max_jogos: int | None = None,
    atualizar: bool = False,
    espera_429: tuple[int, ...] = ESPERA_429_ITAD,
    falhas_seguidas_max: int = 5,
    dormir: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = _imprimir,
) -> Resumo:
    resumo = Resumo()
    seguidas = 0
    for jogo in jogos:
        if max_jogos is not None and resumo.baixados >= max_jogos:
            break
        appid, gid, titulo = int(jogo["appid"]), str(jogo["gid"]), str(jogo.get("titulo", ""))
        alvo = caminho_do_jogo(destino, appid)
        if alvo.exists() and not atualizar:
            resumo.ja_existiam += 1
            continue

        bruto: object = None
        ok = False
        tentativa = 0
        while True:
            try:
                bruto = cliente.historico_bruto(gid)
                parsear_historico(bruto, gid)  # valida antes de gravar
                ok = True
                break
            except LimiteExcedido as erro:
                if tentativa >= len(espera_429):
                    resumo.interrompida_por = "429 persistente: o ITAD pediu para esperar, tente mais tarde"
                    return resumo
                # A API manda `Retry-After` no 429: obedecer esse valor (mais 1 s de folga); a tabela é só reserva.
                espera = erro.retry_after + 1 if erro.retry_after else espera_429[tentativa]
                log(f"429 em {titulo!r}: esperando {espera} s (tentativa {tentativa + 1}/{len(espera_429)})")
                dormir(espera)
                tentativa += 1
            except ChaveRecusada as erro:
                resumo.interrompida_por = f"chave recusada ({erro})"
                return resumo
            except (RespostaInvalida, httpx.HTTPError) as erro:
                resumo.falhas.append((titulo or str(appid), str(erro)[:200]))
                log(f"falha em {titulo!r}: {str(erro)[:120]}")
                seguidas += 1
                if seguidas >= falhas_seguidas_max:
                    resumo.interrompida_por = f"{seguidas} falhas seguidas"
                    return resumo
                break

        if not ok:
            continue
        seguidas = 0
        _gravar(alvo, jogo, bruto)
        resumo.baixados += 1
        log(f"[{resumo.baixados}] {titulo}: {len(bruto)} mudanças de preço")  # type: ignore[arg-type]
    return resumo


def carregar_historico_jogo(caminho: Path) -> HistoricoJogo:
    corpo = json.loads(caminho.read_text(encoding="utf-8"))
    return parsear_historico(corpo["bruto"], corpo["gid"], int(corpo["appid"]), corpo.get("titulo", ""))


def listar_historicos_jogos(destino: Path) -> Iterator[HistoricoJogo]:
    for caminho in sorted(destino.glob("*.json")):
        yield carregar_historico_jogo(caminho)
