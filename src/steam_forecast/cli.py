"""steam-forecast: coleta, avaliação temporal e catálogo local de jogos e itens da Steam."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from steam_forecast.avaliacao import avaliar, filtrar_series, tabela_markdown
from steam_forecast.coleta import coletar, listar_historicos
from steam_forecast.env import ChaveAusente, CookieAusente, avisos, carregar_chave_itad, carregar_cookie
from steam_forecast.itad import ChaveRecusada, ClienteITAD
from steam_forecast.jogos import coletar_jogos, montar_universo
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


def _cliente_itad(args: argparse.Namespace, intervalo: float) -> ClienteITAD | None:
    try:
        chave = carregar_chave_itad(args.env)
    except ChaveAusente as erro:
        print(erro, file=sys.stderr)
        return None
    return ClienteITAD(chave, limitador=Limitador(intervalo, jitter_s=0.1))


def _jogos_universo(args: argparse.Namespace) -> int:
    cliente = _cliente_itad(args, 0.5)
    if cliente is None:
        return 2
    try:
        universo = montar_universo(cliente, args.por_ranking)
    except (LimiteExcedido, ChaveRecusada) as erro:
        print(f"parei: {erro}", file=sys.stderr)
        return 1
    finally:
        cliente.fechar()
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(json.dumps(universo, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(universo)} jogos da Steam em {args.saida}")
    return 0


def _jogos_coletar(args: argparse.Namespace) -> int:
    cliente = _cliente_itad(args, args.intervalo)
    if cliente is None:
        return 2
    jogos = json.loads(args.universo.read_text(encoding="utf-8"))
    try:
        resumo = coletar_jogos(cliente, jogos, args.destino, max_jogos=args.max_jogos, atualizar=args.atualizar)
    finally:
        cliente.fechar()
    print(f"baixados {resumo.baixados}, já existiam {resumo.ja_existiam}, falhas {len(resumo.falhas)}")
    if resumo.interrompida_por:
        print(f"interrompida: {resumo.interrompida_por}. O progresso está salvo; rode de novo para retomar.", file=sys.stderr)
        return 1
    if resumo.falhas:
        print("coleta incompleta: houve falhas; rode jogos-status e retome os jogos pendentes.", file=sys.stderr)
        return 1
    return 0


def _salvar_json(caminho: Path, valor: object) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(json.dumps(valor, ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")
    temporario.replace(caminho)


def _positivo(texto: str) -> int:
    valor = int(texto)
    if valor <= 0:
        raise argparse.ArgumentTypeError("precisa ser maior que zero")
    return valor


def _intervalo(texto: str) -> float:
    from math import isfinite

    valor = float(texto)
    if not isfinite(valor) or valor < 0:
        raise argparse.ArgumentTypeError("intervalo precisa ser finito e não negativo")
    return valor


def _jogos_status(args: argparse.Namespace) -> int:
    from steam_forecast.exportacao_jogos import estado_coleta

    estado = estado_coleta(args.universo, args.dados)
    print(json.dumps(estado if args.detalhes else {k: v for k, v in estado.items() if k != "appids_faltantes"}, ensure_ascii=False, indent=1))
    return 0 if estado["completa"] else 1


def _jogos_avaliar(args: argparse.Namespace) -> int:
    from datetime import date
    import time

    from steam_forecast.modelo_jogos import ConfiguracaoJogos, executar_jogos, tabela_markdown_jogos
    from steam_forecast.series_jogos import carregar_series_jogos

    series = carregar_series_jogos(args.dados)
    inicio = (date.fromisoformat(args.inicio_teste) - date(1970, 1, 1)).days
    print(f"{len(series)} séries de jogos; teste desde {args.inicio_teste}; cortes a cada {args.retreino} dias", flush=True)
    resultados = []
    for horizonte in args.horizonte:
        cfg = ConfiguracaoJogos(
            horizonte=horizonte, inicio_teste=inicio, retreino=args.retreino,
            passo=args.passo, iteracoes=args.iteracoes, min_historia=args.historia_min,
        )
        t0 = time.monotonic()
        resultado = executar_jogos(series, cfg, log=lambda m: print(m, file=sys.stderr, flush=True))
        resultado["segundos"] = round(time.monotonic() - t0, 2)
        resultados.append(resultado)
        _salvar_json(args.saida, resultados)
        print(tabela_markdown_jogos(resultado), f"\n({resultado['segundos']} s)\n", flush=True)
    print(f"avaliação em {args.saida}")
    return 0 if all(r.get("origens", 0) for r in resultados) else 1


def _jogos_exportar(args: argparse.Namespace) -> int:
    from steam_forecast.exportacao_jogos import catalogo_local
    from steam_forecast.modelo_jogos import ConfiguracaoJogos, prever_jogos_agora
    from steam_forecast.series_jogos import carregar_series_jogos

    series = carregar_series_jogos(args.dados)
    if not series:
        print("nenhuma série de jogos disponível", file=sys.stderr)
        return 1
    previsoes = {}
    for horizonte in args.horizonte:
        cfg = ConfiguracaoJogos(horizonte=horizonte, inicio_teste=0, iteracoes=args.iteracoes)
        previsoes[horizonte] = prever_jogos_agora(
            series, horizonte, cfg=cfg, log=lambda m: print(m, file=sys.stderr, flush=True)
        )
    _salvar_json(args.saida, catalogo_local(series, previsoes, dias_historico=args.dias_historico))
    print(f"{len(series)} jogos em {args.saida}; abra o arquivo pelo botão de importação local do site.")
    return 0


def _modelo(args: argparse.Namespace) -> int:
    import time
    from datetime import date

    from steam_forecast.modelo import Configuracao, dia_absoluto, executar
    from steam_forecast.modelo import tabela_markdown as tabela_ml

    series = [s for s in (diaria(h) for h in listar_historicos(args.dados)) if s is not None]
    elegiveis = filtrar_series(series, min_dias=args.min_dias, min_vendas_por_dia=args.min_vendas)
    inicio = dia_absoluto(date.fromisoformat(args.inicio_teste))
    print(f"{len(series)} séries, {len(elegiveis)} elegíveis; teste a partir de {args.inicio_teste}, retreino a cada {args.retreino} dias\n")
    resultados = []
    for h in args.horizonte:
        cfg = Configuracao(
            horizonte=h,
            inicio_teste=inicio,
            retreino=args.retreino,
            passo_treino=args.passo_treino,
            iteracoes=args.iteracoes,
        )
        t0 = time.monotonic()
        resultado = executar(elegiveis, cfg, log=lambda msg: print(msg, file=sys.stderr, flush=True))
        resultado["segundos"] = round(time.monotonic() - t0)
        resultados.append(resultado)
        print(tabela_ml(resultado), f"\n\n({resultado['segundos']} s)", end="\n\n", flush=True)
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

    m = sub.add_parser("modelo", help="gradient boosting com quantis em janela deslizante, contra os baselines (precisa do extra ml)")
    m.add_argument("--dados", type=Path, default=DADOS / "raw")
    m.add_argument("--horizonte", type=int, action="append", help="dias; repita para vários (padrão: 7 e 30)")
    m.add_argument("--inicio-teste", default="2023-01-01", help="primeira origem de teste, AAAA-MM-DD")
    m.add_argument("--retreino", type=int, default=90, help="dias entre um treino e o seguinte")
    m.add_argument("--passo-treino", type=int, default=2, help="usa uma linha de treino a cada N dias de cada item")
    m.add_argument("--iteracoes", type=int, default=150)
    m.add_argument("--min-dias", type=int, default=500)
    m.add_argument("--min-vendas", type=float, default=3.0)
    m.add_argument("--saida", type=Path, default=None)
    m.set_defaults(func=_modelo)

    ju = sub.add_parser("jogos-universo", help="jogos populares da Steam pelo ranking do IsThereAnyDeal (usa a chave do .env)")
    ju.add_argument("--por-ranking", type=int, default=1500, help="quantos pegar de cada ranking (popular e colecionado)")
    ju.add_argument("--env", type=Path, default=Path(".env"))
    ju.add_argument("--saida", type=Path, default=DADOS / "jogos" / "universo.json")
    ju.set_defaults(func=_jogos_universo)

    jc = sub.add_parser("jogos-coletar", help="baixa o histórico de preço de cada jogo no IsThereAnyDeal (BRL, desde o lançamento)")
    jc.add_argument("--universo", type=Path, default=DADOS / "jogos" / "universo.json")
    jc.add_argument("--destino", type=Path, default=DADOS / "jogos" / "historico")
    jc.add_argument("--env", type=Path, default=Path(".env"))
    jc.add_argument("--intervalo", type=_intervalo, default=0.5, help="segundos entre chamadas (o limite do ITAD é 1.000 a cada 5 min)")
    jc.add_argument("--max-jogos", type=_positivo, default=None, help="começar pequeno, por exemplo 20")
    jc.add_argument("--atualizar", action="store_true", help="baixa de novo o que já existe")
    jc.set_defaults(func=_jogos_coletar)

    js = sub.add_parser("jogos-status", help="confere completude e integridade da coleta local, sem chamar a API")
    js.add_argument("--universo", type=Path, default=DADOS / "jogos" / "universo.json")
    js.add_argument("--dados", type=Path, default=DADOS / "jogos" / "historico")
    js.add_argument("--detalhes", action="store_true", help="inclui a lista dos appids pendentes")
    js.set_defaults(func=_jogos_status)

    ja = sub.add_parser("jogos-avaliar", help="compara baselines e ML dos jogos em cortes temporais (extra ml)")
    ja.add_argument("--dados", type=Path, default=DADOS / "jogos" / "historico")
    ja.add_argument("--horizonte", type=_positivo, action="append", help="dias; padrão: 30 e 90")
    ja.add_argument("--inicio-teste", default="2023-01-01")
    ja.add_argument("--retreino", type=_positivo, default=180)
    ja.add_argument("--passo", type=_positivo, default=7)
    ja.add_argument("--iteracoes", type=_positivo, default=80)
    ja.add_argument("--historia-min", type=_positivo, default=365)
    ja.add_argument("--saida", type=Path, default=DADOS / "jogos" / "resultados-modelo.json")
    ja.set_defaults(func=_jogos_avaliar)

    je = sub.add_parser("jogos-exportar", help="treina com alvos conhecidos e gera catálogo para importação local (extra ml)")
    je.add_argument("--dados", type=Path, default=DADOS / "jogos" / "historico")
    je.add_argument("--horizonte", type=_positivo, action="append", help="dias; padrão: 30 e 90")
    je.add_argument("--iteracoes", type=_positivo, default=80)
    je.add_argument("--dias-historico", type=_positivo, default=365)
    je.add_argument("--saida", type=Path, default=DADOS / "jogos" / "catalogo-local.json")
    je.set_defaults(func=_jogos_exportar)

    args = ap.parse_args(argv)
    if args.comando in ("avaliar", "modelo") and not args.horizonte:
        args.horizonte = [7, 30]
    if args.comando in ("jogos-avaliar", "jogos-exportar") and not args.horizonte:
        args.horizonte = [30, 90]
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
