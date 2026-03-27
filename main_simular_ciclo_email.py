"""
main_simular_ciclo_email.py — Ensaio geral do fluxo email completo.

Uso:
  python main_simular_ciclo_email.py              # simula 3 oportunidades
  python main_simular_ciclo_email.py --lote 10    # simula 10 emails direto
  python main_simular_ciclo_email.py --n 5        # ciclo com 5 oportunidades
  python main_simular_ciclo_email.py --metricas   # exibe métricas acumuladas

Nenhum email real é enviado. Tudo marcado com simulado=True.
"""

import argparse
import json
import sys
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)-8s %(name)s — %(message)s",
)

# Silenciar módulos ruidosos em modo CLI
for _mod in ("core.llm_router", "core.leitor_respostas_email",
             "core.simulador_ciclo_email", "core.templates_email"):
    logging.getLogger(_mod).setLevel(logging.WARNING)


def _linha(char="-", n=62):
    print(char * n)


def _sec(titulo: str):
    print()
    _linha()
    print(f"  {titulo}")
    _linha()


def _badge(texto: str, ok: bool = True) -> str:
    return f"[OK] {texto}" if ok else f"[!!] {texto}"


def _imprimir_relatorio(relatorio: dict):
    """Imprime o relatório completo do ciclo simulado no terminal."""
    status = relatorio.get("status", "?")
    duracao = relatorio.get("duracao_segundos", 0)

    _sec(f"SIMULAÇÃO DE CICLO EMAIL  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    print(f"\n  Status  : {status.upper()}")
    print(f"  Duração : {duracao}s")

    # Oportunidades
    _sec("OPORTUNIDADES UTILIZADAS")
    for opp in relatorio.get("oportunidades_detalhes", []):
        print(f"  *[{opp.get('estagio','?'):<18}] {opp.get('contraparte','?')}")

    # Emails
    _sec("EMAILS PREPARADOS E ENVIADOS (SIMULADO)")
    print(f"  Total preparados      : {relatorio.get('emails_preparados', 0)}")
    print(f"  Adicionados à fila    : {relatorio.get('emails_adicionados_fila', 0)}")
    print()
    print("  Por template:")
    for tipo, count in relatorio.get("emails_por_template", {}).items():
        print(f"    {tipo:<30} {count}")
    print()
    print("  Por fonte (llm / template / fallback):")
    for fonte, count in relatorio.get("emails_por_fonte", {}).items():
        print(f"    {fonte:<30} {count}")

    # Respostas
    _sec("RESPOSTAS SIMULADAS")
    n_resp  = relatorio.get("respostas_geradas", 0)
    n_env   = relatorio.get("emails_adicionados_fila", 0)
    taxa    = relatorio.get("taxa_resposta_ciclo", 0)
    print(f"  Respostas recebidas   : {n_resp} / {n_env} emails  ({taxa:.0%})")
    print()
    por_classif = relatorio.get("por_classificacao", {})
    if por_classif:
        print("  Por classificação:")
        for classif, count in sorted(por_classif.items(), key=lambda x: -x[1]):
            bar = "#" * count
            print(f"    {classif:<25} {count:>3}  {bar}")
    else:
        print("  Nenhuma resposta gerada neste ciclo (probabilístico — normal).")

    # Ações
    _sec("AÇÕES EXECUTADAS")
    print(f"  Total de ações        : {relatorio.get('acoes_executadas', 0)}")

    # Pipeline
    movimentos = relatorio.get("integridade", {}).get("movimentos_pipeline", {})
    if movimentos:
        print()
        print("  Movimentos no pipeline:")
        for mov, count in movimentos.items():
            print(f"    {mov:<30} {count}")

    # Integridade
    _sec("VERIFICAÇÃO DE INTEGRIDADE")
    integ = relatorio.get("integridade", {})
    ok    = integ.get("ok", True)
    print(f"  {_badge('Integridade OK' if ok else 'Alertas encontrados', ok)}")
    print(f"  Emails na fila        : {integ.get('total_emails_fila', 0)}")
    print(f"  Respostas registradas : {integ.get('total_respostas', 0)}")
    print(f"  Ações registradas     : {integ.get('total_acoes_log', 0)}")
    print(f"  Ações orphãs          : {integ.get('acoes_orphas', 0)}")
    for alerta in integ.get("alertas", []):
        print(f"  [!!] {alerta}")

    # Métricas acumuladas
    _sec("MÉTRICAS ACUMULADAS (metricas_email.json)")
    mac = relatorio.get("metricas_acumuladas", {})
    print(f"  Total enviados        : {mac.get('emails_enviados_total', 0)}")
    print(f"  Taxa de resposta      : {mac.get('taxa_resposta', 0):.1%}")
    print(f"  Ações total           : {mac.get('acoes_executadas', 0)}")

    _sec("CONCLUSÃO")
    if status == "ok":
        print("  Fluxo de ponta a ponta: OK")
        print("  O sistema está pronto para receber SMTP/IMAP real.")
    elif status == "ok_com_alertas":
        print("  Fluxo concluído com alertas — revisar antes de ir para real.")
    else:
        print(f"  Status: {status} — verificar logs para detalhes.")
    print()


def _imprimir_metricas():
    """Exibe métricas acumuladas de metricas_email.json."""
    from core.simulador_ciclo_email import obter_metricas

    m = obter_metricas()
    _sec(f"MÉTRICAS ACUMULADAS DE EMAIL  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    print(f"  Emails enviados total   : {m.get('emails_enviados_total', 0)}")
    print(f"  Respostas recebidas     : {m.get('respostas_recebidas_total', 0)}")
    print(f"  Taxa de resposta        : {m.get('taxa_resposta', 0):.1%}")
    print(f"  Ações executadas        : {m.get('acoes_executadas', 0)}")
    print()

    classif = m.get("classificacoes", {})
    if classif:
        print("  Classificações acumuladas:")
        for c, n in sorted(classif.items(), key=lambda x: -x[1]):
            print(f"    {c:<25} {n}")
        print()

    pm = m.get("pipeline_movido", {})
    if pm:
        print("  Pipeline movido (acumulado):")
        for k, v in pm.items():
            print(f"    {k:<20} {v}")
        print()

    pt = m.get("por_template", {})
    if pt:
        print("  Por template:")
        print(f"    {'Template':<30} {'Env':>5} {'Resp':>5} {'Taxa':>6}")
        _linha(n=52)
        for tipo, d in pt.items():
            print(
                f"    {tipo:<30} {d.get('enviados',0):>5} "
                f"{d.get('respondidos',0):>5} {d.get('taxa',0):>6.1%}"
            )
        print()

    ultimo = m.get("ultimo_ciclo")
    if ultimo:
        print(f"  Último ciclo: {ultimo.get('executado_em','?')[:16]}")
    print()


def _imprimir_lote(n: int):
    """Executa simular_lote(n) diretamente e exibe resultado."""
    from core.leitor_respostas_email import simular_lote

    _sec(f"SIMULAÇÃO EM LOTE — {n} respostas diretas")
    resultado = simular_lote(n)
    print(f"  Respostas geradas : {resultado.get('respostas_geradas', 0)}")
    print(f"  Ações geradas     : {resultado.get('acoes_geradas', 0)}")
    print(f"  Modo              : {resultado.get('modo', '?')}")
    print()
    por = resultado.get("por_classificacao", {})
    if por:
        print("  Por classificação:")
        for c, n in sorted(por.items(), key=lambda x: -x[1]):
            print(f"    {c:<25} {n}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Simulador de ciclo email completo — ensaio geral antes de SMTP real",
    )
    parser.add_argument("--n",        type=int, default=3,
                        help="Número de oportunidades no ciclo completo (padrão: 3)")
    parser.add_argument("--lote",     type=int, default=0,
                        help="Simular N respostas diretas (sem preparar emails)")
    parser.add_argument("--metricas", action="store_true",
                        help="Exibir métricas acumuladas de metricas_email.json")
    parser.add_argument("--json",     action="store_true",
                        help="Saída em JSON bruto (para integração)")
    args = parser.parse_args()

    if args.metricas:
        _imprimir_metricas()
        return

    if args.lote > 0:
        _imprimir_lote(args.lote)
        return

    # Ciclo completo
    from core.simulador_ciclo_email import simular_ciclo_completo
    relatorio = simular_ciclo_completo(n_oportunidades=args.n)

    if args.json:
        print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    else:
        _imprimir_relatorio(relatorio)

    # Exit code: 1 se status != ok*
    if relatorio.get("status", "").startswith("ok"):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
