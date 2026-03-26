"""
main_multi_cidade.py — Orquestrador multi-cidade: prospecção e marketing em escala.

Como usar:
  python main_multi_cidade.py                        # processa proximas cidades da fila
  python main_multi_cidade.py --cidade "Ribeirao Preto"  # forca uma cidade especifica
  python main_multi_cidade.py --status               # exibe estado de todas as cidades
  python main_multi_cidade.py --ranking              # exibe ranking de oportunidades
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Logging basico (ASCII-safe para Windows CP1252)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

_STATUS_EMOJI = {
    "pendente":     "[pendente  ]",
    "em_andamento": "[andamento ]",
    "concluida":    "[concluida ]",
    "erro":         "[ERRO      ]",
}


def main(cidade_forcada: str = None) -> None:
    """Ponto de entrada para o scheduler."""
    from core.orquestrador_multi_cidade import executar
    resultado = executar(cidade_forcada=cidade_forcada)
    _imprimir_resumo_ciclo(resultado)


def cmd_status() -> None:
    from core.orquestrador_multi_cidade import obter_status

    estado = obter_status()
    cidades = estado.get("cidades", {})
    cfg = estado.get("configuracao", {})
    total_ciclos = estado.get("total_ciclos", 0)
    ultima_exec = estado.get("ultima_execucao_ciclo", "nunca")

    print()
    print("=" * 65)
    print("MULTI-CIDADE — STATUS")
    print(f"  Ultimo ciclo : {ultima_exec}")
    print(f"  Total ciclos : {total_ciclos}")
    print(f"  Max cidades/ciclo: {cfg.get('max_cidades_por_ciclo', 2)}")
    print(f"  Max nichos/cidade: {cfg.get('max_nichos_por_cidade_por_ciclo', 3)}")
    print("=" * 65)
    print(f"{'Cidade':<28} {'UF':>3}  {'Status':<13} {'Leads':>6}  {'Oport':>6}  {'Exec':>5}")
    print("-" * 65)

    # Ordenar por status (em_andamento > pendente > concluida > erro)
    _ordem = {"em_andamento": 0, "pendente": 1, "concluida": 2, "erro": 3}
    for nome, info in sorted(cidades.items(), key=lambda x: _ordem.get(x[1].get("status", "pendente"), 9)):
        uf      = info.get("estado", "")
        status  = info.get("status", "pendente")
        leads   = info.get("leads_encontrados", 0)
        oport   = info.get("oportunidades_geradas", 0)
        execucoes = info.get("execucoes_total", 0)
        label   = _STATUS_EMOJI.get(status, f"[{status:<10}]")
        print(f"  {nome:<26} {uf:>3}  {label}  {leads:>6}  {oport:>6}  {execucoes:>5}")
        if info.get("ultimo_erro"):
            print(f"    -> {info['ultimo_erro'][:60]}")

    print("=" * 65)
    print(f"  Total: {len(cidades)} cidades")
    total_leads = sum(i.get("leads_encontrados", 0) for i in cidades.values())
    total_oport = sum(i.get("oportunidades_geradas", 0) for i in cidades.values())
    print(f"  Leads acumulados     : {total_leads}")
    print(f"  Oportunidades totais : {total_oport}")
    print()


def cmd_ranking() -> None:
    from core.orquestrador_multi_cidade import obter_ranking, _carregar_consolidado

    ranking = obter_ranking()
    consolidado = _carregar_consolidado()
    redes = consolidado.get("redes_detectadas", [])

    print()
    print("=" * 55)
    print("RANKING DE OPORTUNIDADES POR CIDADE")
    print("=" * 55)

    if not ranking:
        print("  Nenhum dado disponivel ainda. Execute um ciclo primeiro.")
    else:
        for pos, (cidade, oport) in enumerate(ranking, 1):
            print(f"  {pos:>2}. {cidade:<28} {oport:>6} oportunidades")

    if redes:
        print()
        print(f"REDES DETECTADAS ({len(redes)} grupos):")
        for rede in redes[:10]:
            cidades_str = ", ".join(rede["cidades"])
            print(f"  - {rede['nome_normalizado'][:30]:<32} em: {cidades_str}")

    print("=" * 55)
    print()


def _imprimir_resumo_ciclo(resultado: dict) -> None:
    cidades = resultado.get("cidades_processadas", [])
    leads   = resultado.get("leads_total_ciclo", 0)
    oport   = resultado.get("oportunidades_total_ciclo", 0)
    rate    = resultado.get("rate_limitado", False)

    print()
    print("=" * 55)
    print("MULTI-CIDADE — CICLO CONCLUIDO")
    print("=" * 55)
    if not cidades:
        motivo = resultado.get("motivo", "")
        print(f"  Nenhuma cidade processada. {motivo}")
    else:
        for cidade in cidades:
            print(f"  + {cidade}")
        print(f"  Leads encontrados    : {leads}")
        print(f"  Oportunidades geradas: {oport}")
    if rate:
        print("  [AVISO] Rate limit detectado — retomando no proximo ciclo.")
    print("=" * 55)
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Orquestrador multi-cidade — prospecao e marketing em escala."
    )
    parser.add_argument(
        "--cidade",
        metavar="NOME",
        help="Forcar processamento de uma cidade especifica.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Exibir estado de todas as cidades e sair.",
    )
    parser.add_argument(
        "--ranking",
        action="store_true",
        help="Exibir ranking de oportunidades por cidade e sair.",
    )

    args = parser.parse_args()

    if args.status:
        cmd_status()
        sys.exit(0)

    if args.ranking:
        cmd_ranking()
        sys.exit(0)

    main(cidade_forcada=args.cidade)
