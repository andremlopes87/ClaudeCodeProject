"""
main_agente_qualidade.py — Executa o agente de qualidade da Vetor.

Uso: python main_agente_qualidade.py

Roda testes, analisa cobertura e qualidade de codigo, gera relatorio.
NUNCA modifica codigo.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(message)s",
)

_PRIO_LABEL = {
    "alta":  "[ALTA] ",
    "media": "[MEDIA]",
    "baixa": "[BAIXA]",
}


def main():
    from agentes.ti.agente_qualidade import executar
    resumo = executar()

    print("\n" + "=" * 60)
    print("AGENTE DE QUALIDADE — RESUMO DA ANALISE")
    print("=" * 60)

    score = resumo.get("score_qualidade", 0)
    barra = _barra_score(score)
    print(f"  Score de Qualidade : {barra} {score}/100")
    print(f"  Taxa de testes     : {resumo.get('taxa_testes', 0)}%")
    print(f"  Cobertura modulos  : {resumo.get('taxa_cobertura_modulos', 0)}%")
    print(f"  Recomendacoes      : {resumo.get('total_recomendacoes', 0)} total  |  {resumo.get('recomendacoes_altas', 0)} altas")
    print()

    # Top 5 recomendacoes
    _imprimir_top_recs(5)

    # Avaliacao geral
    print()
    if score >= 90:
        print("  [OK]    Codigo com boa saude geral.")
    elif score >= 70:
        print("  [AVISO] Qualidade aceitavel -- enderecsar recomendacoes altas.")
    elif score >= 50:
        print("  [AVISO] Atencao necessaria -- multiplas fragilidades detectadas.")
    else:
        print("  [ALERTA] Qualidade critica -- acao imediata recomendada.")

    print()
    print("  Relatorio completo : dados/relatorio_qualidade.json")
    print("=" * 60)


def _barra_score(score: int) -> str:
    filled = score // 10
    empty  = 10 - filled
    return f"[{'#' * filled}{'.' * empty}]"


def _imprimir_top_recs(n: int) -> None:
    import json
    from pathlib import Path as _Path

    raiz = _Path(__file__).parent
    arq  = raiz / "dados" / "relatorio_qualidade.json"
    if not arq.exists():
        return

    try:
        relatorio = json.loads(arq.read_text(encoding="utf-8"))
        recs = relatorio.get("recomendacoes", [])
        # Ordenar: altas primeiro, depois medias
        ordem = {"alta": 0, "media": 1, "baixa": 2}
        recs_ord = sorted(recs, key=lambda r: ordem.get(r.get("prioridade", "baixa"), 3))
        top = recs_ord[:n]

        if not top:
            return

        print("  -- TOP RECOMENDACOES ------------------------------------------")
        for rec in top:
            prio   = rec.get("prioridade", "baixa")
            label  = _PRIO_LABEL.get(prio, "[?]    ")
            descr  = rec.get("descricao", "—")[:70]
            acao   = rec.get("acao_sugerida", "—")[:65]
            cat    = rec.get("categoria", "—")
            print(f"    {label}  [{cat}]")
            print(f"      {descr}")
            print(f"      -> {acao}")
            print()
    except Exception as _err:
        logging.warning("erro ignorado: %s", _err)


if __name__ == "__main__":
    main()
