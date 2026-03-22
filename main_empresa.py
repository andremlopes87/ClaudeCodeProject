"""
main_empresa.py — Ponto de entrada único da empresa.

Executa o ciclo operacional completo em ordem:
  1. agente_financeiro
  2. agente_comercial          (importar oportunidades + processar resultados de contato)
  3. agente_secretario         (consolidar + criar handoffs + deliberacoes)
  4. agente_executor_contato   (preparar execucoes dos handoffs operacionais)
  5. agente_comercial          (reabsorver efeitos gerados pelo executor)
  6. agente_secretario         (fechar retrato final do ciclo)

Produz:
  dados/ciclo_operacional.json
  dados/estado_empresa.json
  logs/empresa/ciclo_empresa_TIMESTAMP.log

Uso:
  python main_empresa.py
"""

import json

import config
from core.orquestrador_empresa import executar_ciclo_empresa


def main() -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)

    ciclo = executar_ciclo_empresa()

    print("\n" + "=" * 64)
    print("EMPRESA — CICLO OPERACIONAL CONCLUIDO")
    print("=" * 64)
    print(f"Ciclo ID       : {ciclo['ciclo_id']}")
    print(f"Status geral   : {ciclo['status_geral']}")
    print(f"Iniciado em    : {ciclo['iniciado_em']}")
    print(f"Finalizado em  : {ciclo['finalizado_em']}")
    print("---")
    print("ETAPAS EXECUTADAS:")
    for etapa in ciclo["etapas"]:
        marker = "OK" if etapa["status"] == "ok" else "!!"
        print(
            f"  [{marker}] {etapa['nome_agente']:30} | "
            f"{etapa['status']:8} | {etapa['duracao_ms']}ms"
        )
        if etapa.get("erro"):
            print(f"       Erro: {str(etapa['erro'])[:70]}")
    print("---")

    resumo = ciclo.get("resumo_final", {})
    print("RESUMO FINAL DO CICLO:")
    print(f"  Deliberacoes pendentes      : {resumo.get('deliberacoes_pendentes', 0)}")
    print(f"  Handoffs pendentes          : {resumo.get('handoffs_pendentes', 0)}")
    print(f"  Pipeline (oportunidades)    : {resumo.get('pipeline_total', 0)}")
    print(f"  Follow-ups para integracao  : {resumo.get('followups_aguardando_integracao', 0)}")
    print(f"  Riscos financeiros          : {resumo.get('riscos_financeiros', 0)}")
    print(f"  Risco de caixa              : {'SIM' if resumo.get('risco_caixa') else 'nao'}")
    print(f"  Mkt oport. importadas       : {resumo.get('mkt_importadas', 0)}")
    print(f"  Mkt handoffs criados        : {resumo.get('mkt_handoffs_criados', 0)}")
    print(f"  Oportunidades novas         : {resumo.get('oportunidades_novas_no_ciclo', 0)}")
    print(f"  Resultados gerados (integr.): {resumo.get('resultados_gerados_integrador', 0)}")
    print(f"  Resultados de contato aplic.: {resumo.get('resultados_aplicados', 0)}")
    print(f"  Execucoes preparadas        : {resumo.get('execucoes_preparadas', 0)}")
    print(f"  Erros no ciclo              : {resumo.get('erros_no_ciclo', 0)}")
    print("---")

    if ciclo["erros"]:
        print(f"ERROS ({len(ciclo['erros'])}):")
        for err in ciclo["erros"]:
            print(f"  [{err.get('etapa', '?'):30}] {str(err.get('erro', '?'))[:60]}")

    print("=" * 64)
    pasta = config.PASTA_DADOS
    print(f"\nARQUIVOS PRODUZIDOS:")
    print(f"  {pasta / 'ciclo_operacional.json'}")
    print(f"  {pasta / 'estado_empresa.json'}")
    print(f"  {config.PASTA_LOGS / 'empresa'}/ciclo_empresa_*.log")
    print("=" * 64)


if __name__ == "__main__":
    main()
