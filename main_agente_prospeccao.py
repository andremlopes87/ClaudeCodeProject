"""
main_agente_prospeccao.py — Ponto de entrada do agente de prospecção.

Lê artefatos da linha de prospecção, classifica oportunidades e entrega
candidatas prontas para o fluxo comercial via fila_execucao_comercial.json.

Não roda scraping. Não envia contato. Não descarta em massa.
"""

import json

import config
from agentes.prospeccao.agente_prospeccao import executar


def main() -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)

    resultado = executar()

    pasta = config.PASTA_DADOS
    print("\n" + "=" * 64)
    print("AGENTE PROSPECÇÃO")
    print("=" * 64)
    print(f"Candidatas lidas           : {resultado['candidatas_lidas']}")
    print(f"Já no fluxo comercial      : {resultado['ja_no_fluxo']}")
    print(f"Novas processadas          : {resultado['novas_processadas']}")
    print(f"Prontas para handoff       : {resultado['prontas_para_handoff']}")
    print(f"Em revisão                 : {resultado['em_revisao']}")
    print(f"Baixa prioridade           : {resultado['baixa_prioridade']}")
    print(f"Skip (já processadas)      : {resultado['skip']}")
    print(f"Fila prosp total           : {resultado['fila_prosp_total']}")
    print("---")
    print("ARQUIVOS ATUALIZADOS:")
    for nome in [
        "fila_oportunidades_prospeccao.json",
        "historico_prospeccao_agente.json",
        "fila_execucao_comercial.json",
        "handoffs_agentes.json",
        "estado_agente_prospeccao.json",
    ]:
        print(f"  {pasta / nome}")
    print(f"Log                        : {resultado['caminho_log']}")
    print("=" * 64)

    # Mostrar fila de prospecção
    fila_path = pasta / "fila_oportunidades_prospeccao.json"
    if fila_path.exists():
        fila = json.loads(fila_path.read_text(encoding="utf-8"))
        prontas = [o for o in fila if o.get("pronto_para_handoff")]
        revisao = [o for o in fila if o.get("status") == "em_revisao"]
        baixa   = [o for o in fila if o.get("status") == "baixa_prioridade"]

        print(f"\nFILA PROSPECÇÃO — {len(fila)} oportunidade(s):")
        if prontas:
            print(f"  PRONTAS PARA HANDOFF ({len(prontas)}):")
            for o in prontas[:5]:
                print(
                    f"    [{o.get('prioridade','?'):6}] {o.get('empresa','?')[:35]:35} | "
                    f"canal={o.get('canal_sugerido','?')}"
                )
        if revisao:
            print(f"  EM REVISÃO ({len(revisao)}): {', '.join(o.get('empresa','?')[:20] for o in revisao[:5])}")
        if baixa:
            print(f"  BAIXA PRIORIDADE ({len(baixa)}): {', '.join(o.get('empresa','?')[:20] for o in baixa[:3])}")
    print("=" * 64)


if __name__ == "__main__":
    main()
