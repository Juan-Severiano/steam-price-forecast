"""steam-forecast: universo (público), coletar (com o cookie do dono) e avaliar."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from steam_forecast.avaliacao import avaliar, filtrar_series, tabela_markdown
from steam_forecast.coleta import coletar, listar_historicos
from steam_forecast.env import CookieAusente, avisos, carregar_cookie
from steam_forecast.limitador import Limitador
from steam_forecast.series import diaria
from steam_forecast.steam import ClienteSteam, LimiteExcedido

DADOS = Path("data")


def _universo(args: argparse.Namespace) -> int:
    cliente = ClienteSteam()
    try:
        itens = cliente.universo(args.appid, args.quantidade, Limitador(args.intervalo, jitter_s=1.0))
    except LimiteExcedido as erro:
        print(f"parei: {erro}. Tente mais tarde.", file=sys.stderr)
        return 1
    finally:
        cliente.fechar()
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(itens, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(itens)} itens em {args.saida}")
    return 0


def _coletar(args: argparse.Namespace) -> int:
    try:
        cookie = carregar_cookie(args.env)
    except CookieAusente as erro:
        print(erro, file=sys.stderr)
        return 2
    for aviso in avisos(cookie):
        print(f"aviso: {aviso}", file=sys.stderr)
    itens = json.loads(args.universo.read_text(encoding="utf-8"))
    cliente = ClienteSteam(cookie)
    try:
        resumo = coletar(
            cliente,
            itens,
            args.destino,
            Limitador(args.intervalo, jitter_s=1.5),
            max_itens=args.max_itens,
            atualizar=args.atualizar,
        )
    finally:
        cliente.fechar()
    print(f"baixados {resumo.baixados}, já existiam {resumo.ja_existiam}, falhas {len(resumo.falhas)}")
    if resumo.interrompida_por:
        print(f"interrompida: {resumo.interrompida_por}. O progresso está salvo; rode de novo para retomar.", file=sys.stderr)
        return 1
    return 0


def _avaliar(args: argparse.Namespace) -> int:
    series = [s for s in (diaria(h) for h in listar_historicos(args.dados)) if s is not None]
    elegiveis = filtrar_series(series, min_dias=args.min_dias, min_vendas_por_dia=args.min_vendas)
    print(f"{len(series)} séries, {len(elegiveis)} elegíveis (>= {args.min_dias} dias e >= {args.min_vendas:g} vendas/dia)\n")
    resultados = []
    for h in args.horizonte:
        resultado = avaliar(elegiveis, h, passo=args.passo, historia_min=args.historia_min)
        resultados.append(resultado)
        print(tabela_markdown(resultado), end="\n\n")
    if args.saida:
        args.saida.write_text(json.dumps(resultados, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="steam-forecast", description=__doc__)
    sub = ap.add_subparsers(dest="comando", required=True)

    u = sub.add_parser("universo", help="lista os itens mais negociados de um jogo (público, sem cookie)")
    u.add_argument("--appid", type=int, default=730, help="730 = CS2, 570 = Dota 2, 440 = TF2")
    u.add_argument("--quantidade", type=int, default=300)
    u.add_argument("--intervalo", type=float, default=4.0, help="segundos entre chamadas")
    u.add_argument("--saida", type=Path, default=DADOS / "universo.json")
    u.set_defaults(func=_universo)

    c = sub.add_parser("coletar", help="baixa o histórico de preço de cada item (usa o cookie do .env)")
    c.add_argument("--universo", type=Path, default=DADOS / "universo.json")
    c.add_argument("--destino", type=Path, default=DADOS / "raw")
    c.add_argument("--env", type=Path, default=Path(".env"))
    c.add_argument("--intervalo", type=float, default=5.0, help="segundos entre chamadas (5 = 12 por minuto)")
    c.add_argument("--max-itens", type=int, default=None, help="começar pequeno, por exemplo 5")
    c.add_argument("--atualizar", action="store_true", help="baixa de novo o que já existe")
    c.set_defaults(func=_coletar)

    a = sub.add_parser("avaliar", help="baselines em janela deslizante sobre o que foi coletado")
    a.add_argument("--dados", type=Path, default=DADOS / "raw")
    a.add_argument("--horizonte", type=int, action="append", help="dias; repita para vários (padrão: 7 e 30)")
    a.add_argument("--passo", type=int, default=7)
    a.add_argument("--historia-min", type=int, default=365)
    a.add_argument("--min-dias", type=int, default=500)
    a.add_argument("--min-vendas", type=float, default=3.0)
    a.add_argument("--saida", type=Path, default=None)
    a.set_defaults(func=_avaliar)

    args = ap.parse_args(argv)
    if args.comando == "avaliar" and not args.horizonte:
        args.horizonte = [7, 30]
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
