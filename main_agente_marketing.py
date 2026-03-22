"""
main_agente_marketing.py — Execução avulsa do agente de marketing.

Uso:
  python main_agente_marketing.py

Produz:
  dados/fila_oportunidades_marketing_agente.json
  dados/historico_marketing_agente.json
  dados/estado_agente_marketing.json
  dados/handoffs_agentes.json  (atualizado)
  dados/deliberacoes_conselho.json  (atualizado se houver casos sensíveis)
  logs/agentes/agente_marketing_TIMESTAMP.log
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agentes.marketing.agente_marketing import executar

if __name__ == "__main__":
    resultado = executar()

    print()
    print("=" * 60)
    print("AGENTE MARKETING — RESULTADO")
    print("=" * 60)
    print(f"  Oportunidades importadas : {resultado['importadas']}")
    print(f"  Handoffs criados         : {resultado['handoffs_criados']}")
    print(f"  Deliberações criadas     : {resultado['deliberacoes']}")
    print(f"  Baixa prioridade         : {resultado['baixa_prioridade']}")
    print(f"  Em revisão               : {resultado['em_revisao']}")
    print(f"  Já no fluxo (ignoradas)  : {resultado['ja_no_fluxo']}")
    print(f"  Fila agente (total)      : {resultado['fila_agente_total']}")
    print("=" * 60)
