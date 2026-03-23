"""
main_agente_operacao_entrega.py — Runner standalone do agente de operacao de entrega.

Uso:
  python main_agente_operacao_entrega.py
"""

import config
from agentes.operacao_entrega.agente_operacao_entrega import executar


def main() -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)

    resultado = executar()

    print("\n" + "=" * 60)
    print("AGENTE OPERACAO ENTREGA — CONCLUIDO")
    print("=" * 60)
    print(f"  Aptas para entrega   : {resultado['aptas']}")
    print(f"  Entregas abertas     : {resultado['abertas']}")
    print(f"  Entregas atualizadas : {resultado['atualizadas']}")
    print(f"  Checklists criados   : {resultado['checklists_criados']}")
    print(f"  Entregas bloqueadas  : {resultado['bloqueadas']}")
    print(f"  Deliberacoes criadas : {resultado['deliberacoes']}")
    print(f"  Pipeline entrega     : {resultado['pipeline_entrega']} total")
    print("=" * 60)


if __name__ == "__main__":
    main()
