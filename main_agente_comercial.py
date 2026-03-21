"""
main_agente_comercial.py — Ponto de entrada do agente comercial.

Executa o agente comercial operacional:
  - lê oportunidades qualificadas de fila_execucao_comercial.json
  - importa para pipeline_comercial.json
  - gera follow-ups para agente_executor_contato (futuro)
  - registra histórico de todas as ações
  - escala deliberações estratégicas para o conselho

O pipeline só avança quando agentes executores registrarem eventos reais.
Nesta versão, as oportunidades permanecem em 'qualificado' aguardando execução.
"""

import json
from pathlib import Path

import config
from agentes.comercial.agente_comercial import executar


def main() -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)

    resultado = executar()

    pasta = config.PASTA_DADOS
    print("\n" + "=" * 64)
    print("AGENTE COMERCIAL")
    print("=" * 64)
    print(f"Leads lidos                    : {resultado['leads_lidos']}")
    print(f"Oportunidades novas importadas : {resultado['oportunidades_novas']}")
    print(f"Pipeline total                 : {resultado['pipeline_total']}")
    print(f"Follow-ups criados             : {resultado['followups_criados']}")
    print(f"Follow-ups total               : {resultado['followups_total']}")
    print("---")
    print(f"Casos para revisao interna     : {resultado['casos_revisao']}")
    print(f"Escalados ao conselho          : {resultado['escalados_conselho']}")
    print(f"Aprovacoes resolvidas          : {resultado['aprovados_nesta_exec']}")
    print("---")
    print("ARQUIVOS ATUALIZADOS:")
    for nome in [
        "pipeline_comercial.json",
        "fila_followups.json",
        "historico_abordagens.json",
        "estado_agente_comercial.json",
        "fila_decisoes_consolidada.json",
        "agenda_do_dia.json",
    ]:
        print(f"  {pasta / nome}")
    print(f"Log                            : {resultado['caminho_log']}")
    print("=" * 64)

    # Mostrar pipeline
    pipeline_path = pasta / "pipeline_comercial.json"
    if pipeline_path.exists():
        pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
        if pipeline:
            print(f"\nPIPELINE COMERCIAL — {len(pipeline)} oportunidade(s):")
            for opp in pipeline:
                print(
                    f"  [{opp.get('prioridade','?'):5}] {opp.get('estagio','?'):15} | "
                    f"{opp.get('contraparte','?')[:35]:35} | "
                    f"canal: {opp.get('canal_sugerido','?')}"
                )
                print(f"           status_op: {opp.get('status_operacional','?')} | depende_de: {opp.get('depende_de','?')}")

    # Mostrar follow-ups
    fu_path = pasta / "fila_followups.json"
    if fu_path.exists():
        fus = json.loads(fu_path.read_text(encoding="utf-8"))
        pendentes = [f for f in fus if f.get("status") == "pendente_execucao"]
        if pendentes:
            print(f"\nFOLLOW-UPS PENDENTES — {len(pendentes)} aguardando agente_executor_contato:")
            for fu in pendentes[:5]:
                print(f"  [{fu.get('canal','?'):10}] {fu.get('contraparte','?')[:35]:35} | dest: {fu.get('agente_destino','?')}")
                desc = fu.get("descricao", "")
                print(f"           {desc[:90]}")


if __name__ == "__main__":
    main()
