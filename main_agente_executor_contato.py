"""
main_agente_executor_contato.py — Ponto de entrada do executor de contato.

Consome handoffs e follow-ups destinados ao agente_executor_contato,
prepara execucoes internas e deixa a fila pronta para integracao futura
com canais reais (telefone, WhatsApp, email).

Nao realiza contato real. Registra apenas fatos internos verdadeiros.

Produz:
  - fila_execucao_contato.json     — execucoes preparadas com payload
  - historico_execucao_contato.json — log auditavel de eventos
  - estado_agente_executor_contato.json
"""

import json

import config
from agentes.executor_contato.agente_executor_contato import executar


def main() -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)

    resultado = executar()

    pasta = config.PASTA_DADOS
    print("\n" + "=" * 64)
    print("AGENTE EXECUTOR CONTATO")
    print("=" * 64)
    print(f"Handoffs lidos                 : {resultado['handoffs_lidos']}")
    print(f"Execucoes preparadas           : {resultado['preparados']}")
    print(f"Bloqueadas                     : {resultado['bloqueados']}")
    print(f"Skip (ja processados)          : {resultado['skip']}")
    print(f"Fila total                     : {resultado['fila_total']}")
    print("---")
    print("ARQUIVOS ATUALIZADOS:")
    for nome in [
        "fila_execucao_contato.json",
        "historico_execucao_contato.json",
        "handoffs_agentes.json",
        "fila_followups.json",
        "pipeline_comercial.json",
        "historico_abordagens.json",
        "estado_agente_executor_contato.json",
    ]:
        print(f"  {pasta / nome}")
    print(f"Log                            : {resultado['caminho_log']}")
    print("=" * 64)

    # Mostrar fila de execucao
    fila_path = pasta / "fila_execucao_contato.json"
    if fila_path.exists():
        fila = json.loads(fila_path.read_text(encoding="utf-8"))
        if fila:
            prontos   = [e for e in fila if e.get("pronto_para_integracao")]
            bloqueados = [e for e in fila if e.get("status") == "bloqueado"]

            print(f"\nFILA EXECUCAO CONTATO — {len(fila)} item(ns):")
            for exec_item in fila:
                status = exec_item.get("status", "?")
                marker = "OK" if exec_item.get("pronto_para_integracao") else "!!"
                print(
                    f"  [{marker}] {exec_item.get('contraparte','?')[:35]:35} | "
                    f"canal={exec_item.get('canal','?'):12} | status={status}"
                )
                if exec_item.get("motivo_bloqueio"):
                    print(f"       Bloqueio: {exec_item['motivo_bloqueio'][:70]}")
                elif exec_item.get("payload_execucao"):
                    payload = exec_item["payload_execucao"]
                    print(f"       Contato: {payload.get('contato_destino','?')} | "
                          f"Acao: {payload.get('acao_sugerida','')[:55]}")

            if prontos:
                print(f"\nPRONTOS PARA INTEGRACAO DE CANAL ({len(prontos)}):")
                print("  Integrar conector real em payload_execucao.canal + contato_destino")

            if bloqueados:
                print(f"\nBLOQUEADOS ({len(bloqueados)}) — requerem correcao de dados:")
                for b in bloqueados:
                    print(f"  {b.get('contraparte','?')[:40]} | {b.get('motivo_bloqueio','?')}")

    # Mostrar impacto nos handoffs
    hf_path = pasta / "handoffs_agentes.json"
    if hf_path.exists():
        hfs = json.loads(hf_path.read_text(encoding="utf-8"))
        em_andamento = [h for h in hfs if h.get("status") == "em_andamento"]
        pendentes    = [h for h in hfs if h.get("status") == "pendente" and
                        h.get("agente_destino") == "agente_executor_contato"]
        print(f"\nHANDOFFS: {len(em_andamento)} em andamento | {len(pendentes)} ainda pendentes")


if __name__ == "__main__":
    main()
