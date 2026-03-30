"""
main_agente_executor_melhorias.py — Executa o agente executor de melhorias da Vetor.

Uso:
  python main_agente_executor_melhorias.py                  # dry-run automatico (LLM_MODO=dry-run)
  python main_agente_executor_melhorias.py --dry-run        # forcado dry-run
  python main_agente_executor_melhorias.py --max 5          # limite de mudancas por execucao

Flags:
  --dry-run    Simula sem aplicar nada. Padrao quando LLM_MODO=dry-run.
  --max N      Maximo de mudancas por execucao (1-10, padrao=3).
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(message)s",
)

_STATUS_LABEL = {
    "aplicada":       "[APLICADA]  ",
    "revertida":      "[REVERTIDA] ",
    "simulada":       "[SIMULADA]  ",
    "pendente":       "[PENDENTE]  ",
    "pulada":         "[PULADA]    ",
    "escalada":       "[ESCALADA]  ",
}


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Agente executor de melhorias da Vetor"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simula mudancas sem aplicar nada"
    )
    parser.add_argument(
        "--max", type=int, default=3, metavar="N",
        help="Maximo de mudancas por execucao (1-10, padrao=3)"
    )
    return parser.parse_args()


def main(dry_run: bool = False, max_mudancas: int = 3):
    from agentes.ti.agente_executor_melhorias import executar
    resumo = executar(dry_run=dry_run, max_mudancas=max_mudancas)

    modo = resumo.get("modo", "DRY-RUN")
    print("\n" + "=" * 60)
    print(f"EXECUTOR DE MELHORIAS — RESUMO  [{modo}]")
    print("=" * 60)
    print(f"  Processadas      : {resumo.get('recomendacoes_processadas', 0)}")
    print(f"  Aplicadas        : {resumo.get('aplicadas_com_sucesso', 0)}")
    print(f"  Revertidas       : {resumo.get('revertidas', 0)}")
    print(f"  Escaladas        : {resumo.get('escaladas_conselho', 0)}")
    print(f"  Simuladas        : {resumo.get('simuladas', 0)}")
    print(f"  Pend. LLM real   : {resumo.get('pendentes_llm_real', 0)}")
    print(f"  Puladas          : {resumo.get('puladas', 0)}")

    # Detalhes das mudancas
    _imprimir_mudancas()

    # Aviso sobre modo
    print()
    if modo == "DRY-RUN" or "dry" in modo.lower():
        print("  [SIM]   Modo dry-run — nenhuma mudanca foi aplicada.")
        print("          Para aplicar: ativar LLM_MODO=real em config.py")
    elif resumo.get("aplicadas_com_sucesso", 0) > 0:
        print("  [OK]    Melhorias aplicadas com sucesso.")
    elif resumo.get("revertidas", 0) > 0:
        print("  [ALERTA] Rollback executado — verificar dados/incidentes_executor.json")
    else:
        print("  [OK]    Nenhuma mudanca necessaria neste ciclo.")

    print()
    print("  Relatorio completo : dados/relatorio_melhorias.json")
    print("=" * 60)


def _imprimir_mudancas() -> None:
    import json
    from pathlib import Path as _Path

    arq = _Path(__file__).parent / "dados" / "relatorio_melhorias.json"
    if not arq.exists():
        return

    try:
        rel = json.loads(arq.read_text(encoding="utf-8"))
        mudancas = rel.get("mudancas", [])
        if not mudancas:
            return

        print()
        print("  -- MUDANCAS PROCESSADAS -----------------------------------")
        for m in mudancas:
            status = m.get("status", "?")
            label  = _STATUS_LABEL.get(status, f"[{status.upper()[:8]}]")
            descr  = m.get("descricao", m.get("rec_id", "?"))[:60]
            motivo = m.get("motivo", "")
            print(f"    {label}  {descr}")
            if motivo and status not in ("aplicada", "simulada"):
                print(f"             -> {motivo[:70]}")
        print()
    except Exception as _err:
        logging.warning("erro ignorado: %s", _err)


if __name__ == "__main__":
    args = _parse_args()
    max_val = max(1, min(10, args.max))
    main(dry_run=args.dry_run, max_mudancas=max_val)
