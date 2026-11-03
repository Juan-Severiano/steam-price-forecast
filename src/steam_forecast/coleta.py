"""Baixa o histórico de cada item para `data/raw/<appid>/`, com limite, retomada e parada segura.

Um arquivo por item, escrito por inteiro ou nada. Rodar de novo pula o que já existe.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx

from steam_forecast.limitador import Limitador
from steam_forecast.steam import (
    ClienteSteam,
    Historico,
    HistoricoInvalido,
    LimiteExcedido,
    SessaoExpirada,
    parsear_historico,
)

# Espera, em segundos, a cada 429 seguido no mesmo item. A Steam não documenta o bloqueio.
ESPERA_429 = (300, 900, 1800)


@dataclass
class Resumo:
    baixados: int = 0
    ja_existiam: int = 0
    falhas: list[tuple[str, str]] = field(default_factory=list)
    interrompida_por: str | None = None


def caminho_do_item(destino: Path, appid: int, nome: str) -> Path:
    seguro = re.sub(r"[^A-Za-z0-9._-]+", "_", nome).strip("_")[:80]
    sufixo = hashlib.sha1(nome.encode("utf-8")).hexdigest()[:8]
    return destino / str(appid) / f"{seguro}-{sufixo}.json"


def _gravar(alvo: Path, appid: int, nome: str, bruto: object) -> None:
    alvo.parent.mkdir(parents=True, exist_ok=True)
    corpo = {
        "appid": appid,
        "nome": nome,
        "coletado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bruto": bruto,
    }
    temporario = alvo.with_suffix(".json.tmp")
    temporario.write_text(json.dumps(corpo, ensure_ascii=False), encoding="utf-8")
    temporario.replace(alvo)


def coletar(
    cliente: ClienteSteam,
    itens: Iterable[dict],
    destino: Path,
    limitador: Limitador,
    *,
    max_itens: int | None = None,
    atualizar: bool = False,
    espera_429: tuple[int, ...] = ESPERA_429,
    falhas_seguidas_max: int = 5,
    dormir: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = print,
) -> Resumo:
    resumo = Resumo()
    seguidas = 0
    for item in itens:
        if max_itens is not None and resumo.baixados >= max_itens:
            break
        appid, nome = int(item["appid"]), str(item["nome"])
        alvo = caminho_do_item(destino, appid, nome)
        if alvo.exists() and not atualizar:
            resumo.ja_existiam += 1
            continue

        historico: Historico | None = None
        bruto: object = None
        tentativa = 0
        while True:
            limitador.esperar()
            try:
                bruto = cliente.historico(appid, nome)
                historico = parsear_historico(bruto, appid, nome)  # valida antes de gravar
                break
            except LimiteExcedido as erro:
                if tentativa >= len(espera_429):
                    resumo.interrompida_por = "429 persistente: a Steam bloqueou por um tempo, tente mais tarde"
                    return resumo
                espera = max(erro.retry_after or 0, espera_429[tentativa])
                log(f"429 em {nome!r}: esperando {espera} s (tentativa {tentativa + 1}/{len(espera_429)})")
                dormir(espera)
                tentativa += 1
            except SessaoExpirada as erro:
                resumo.interrompida_por = f"sessão recusada ({erro})"
                return resumo
            except (HistoricoInvalido, httpx.HTTPError) as erro:
                resumo.falhas.append((nome, str(erro)[:200]))
                log(f"falha em {nome!r}: {str(erro)[:120]}")
                seguidas += 1
                if seguidas >= falhas_seguidas_max:
                    resumo.interrompida_por = f"{seguidas} falhas seguidas"
                    return resumo
                break

        if historico is None:
            continue
        seguidas = 0
        _gravar(alvo, appid, nome, bruto)
        resumo.baixados += 1
        log(f"[{resumo.baixados}] {nome}: {len(historico.ts)} pontos")
    return resumo


def carregar_historico(caminho: Path) -> Historico:
    corpo = json.loads(caminho.read_text(encoding="utf-8"))
    return parsear_historico(corpo["bruto"], int(corpo["appid"]), str(corpo["nome"]))


def listar_historicos(destino: Path) -> Iterator[Historico]:
    for caminho in sorted(destino.glob("*/*.json")):
        yield carregar_historico(caminho)
