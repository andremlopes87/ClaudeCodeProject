"""
main_agente_auditor_seguranca.py — Executa o auditor de segurança da Vetor.

Uso: python main_agente_auditor_seguranca.py

Análise estática e passiva — NUNCA modifica código, NUNCA executa código encontrado.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(message)s",
)

_SEV_LABEL = {
    "critico":     "[CRITICO]",
    "alto":        "[ALTO]   ",
    "medio":       "[MEDIO]  ",
    "baixo":       "[BAIXO]  ",
    "informativo": "[INFO]   ",
}


def main():
    from agentes.ti.agente_auditor_seguranca import executar
    resumo = executar()

    print("\n" + "=" * 60)
    print("AUDITOR DE SEGURANÇA — RESUMO DA AUDITORIA")
    print("=" * 60)

    score = resumo.get("score_seguranca", 0)
    barra = _barra_score(score)
    print(f"  Score de Seguranca : {barra} {score}/100")
    print(f"  Total de achados   : {resumo.get('total_vulnerabilidades', 0)}")
    print()

    criticas     = resumo.get("criticas", 0)
    altas        = resumo.get("altas", 0)
    medias       = resumo.get("medias", 0)
    baixas       = resumo.get("baixas", 0)
    informativas = resumo.get("informativas", 0)

    print(f"  {_SEV_LABEL['critico']}  Criticas    : {criticas}")
    print(f"  {_SEV_LABEL['alto']}  Altas       : {altas}")
    print(f"  {_SEV_LABEL['medio']}  Medias      : {medias}")
    print(f"  {_SEV_LABEL['baixo']}  Baixas      : {baixas}")
    print(f"  {_SEV_LABEL['informativo']}  Informativas: {informativas}")

    # Top 3 achados críticos
    if criticas > 0:
        print()
        print("  -- TOP CRITICAS -------------------------------------------")
        _imprimir_top_vulns("critico", 3)

    # Top 3 altas (se não há críticas)
    elif altas > 0:
        print()
        print("  -- TOP ALTAS ----------------------------------------------")
        _imprimir_top_vulns("alto", 3)

    # Recomendação geral
    print()
    if score >= 90:
        print("  [OK]    Sistema com boa postura de seguranca.")
    elif score >= 70:
        print("  [AVISO] Seguranca aceitavel -- enderecsar altas em breve.")
    elif score >= 50:
        print("  [AVISO] Atencao necessaria -- multiplas vulnerabilidades.")
    else:
        print("  [ALERTA] Postura de seguranca critica -- acao imediata recomendada.")

    print()
    print("  Relatório completo : dados/relatorio_seguranca.json")
    print("=" * 60)


def _barra_score(score: int) -> str:
    filled = score // 10
    empty  = 10 - filled
    return f"[{'#' * filled}{'.' * empty}]"


def _imprimir_top_vulns(severidade: str, n: int) -> None:
    import json
    from pathlib import Path as _Path
    import sys

    raiz = _Path(__file__).parent
    arq = raiz / "dados" / "relatorio_seguranca.json"
    if not arq.exists():
        return
    try:
        relatorio = json.loads(arq.read_text(encoding="utf-8"))
        vulns = [v for v in relatorio.get("vulnerabilidades", [])
                 if v.get("severidade") == severidade][:n]
        for v in vulns:
            arq_ref  = v.get("arquivo", "—")
            linha    = v.get("linha", 0)
            loc      = f"{arq_ref}:{linha}" if linha else arq_ref
            descricao = v.get("descricao", "—")[:80]
            rec       = v.get("recomendacao", "—")[:70]
            print(f"    [{loc}]")
            print(f"      {descricao}")
            print(f"      → {rec}")
            print()
    except Exception:
        pass


if __name__ == "__main__":
    main()
