"""
main_agente_customer_success.py — Executa o agente de customer success.

Uso: python main_agente_customer_success.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-8s %(message)s",
)


def main():
    from agentes.customer_success.agente_customer_success import executar
    resultado = executar()

    print("\n" + "=" * 50)
    print("CUSTOMER SUCCESS — RESUMO DO CICLO")
    print("=" * 50)
    print(f"  Contas avaliadas    : {resultado.get('contas_avaliadas', 0)}")
    print(f"  Saude media         : {resultado.get('saude_media', 0)}")
    print(f"  Contas em risco     : {resultado.get('contas_risco', 0)}")
    print(f"  Acoes geradas       : {resultado.get('acoes_geradas', 0)}")
    print(f"  Expansoes sugeridas : {resultado.get('expansoes_sugeridas', 0)}")
    if resultado.get("narrativa_llm"):
        narrativa = resultado["narrativa_llm"]
        if isinstance(narrativa, dict):
            narrativa = str(narrativa)
        print(f"\n  [LLM] {narrativa[:200]}")
    print("=" * 50)


if __name__ == "__main__":
    main()
