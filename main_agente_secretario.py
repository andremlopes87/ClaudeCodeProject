"""
main_agente_secretario.py — Ponto de entrada do agente secretário.

Consolida a visão operacional do dia a partir dos agentes existentes:
  - agente_financeiro
  - agente_comercial

Produz:
  - painel_operacional.json          — visão única da empresa
  - handoffs_agentes.json            — dependências entre agentes
  - deliberacoes_conselho.json       — fila de deliberações do conselho
  - historico_deliberacoes.json      — log auditável de eventos
  - estado_agente_secretario.json
"""

import json

import config
from agentes.secretario.agente_secretario import executar


def main() -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)

    resultado = executar()

    pasta = config.PASTA_DADOS
    print("\n" + "=" * 64)
    print("AGENTE SECRETARIO")
    print("=" * 64)
    print(f"Itens operacionais             : {resultado['operacionais']}")
    print(f"Bloqueios detectados           : {resultado['bloqueios']}")
    print(f"Handoffs criados               : {resultado['handoffs_criados']} (total: {resultado['handoffs_total']})")
    print(f"Deliberacoes pendentes         : {resultado['deliberacoes']}")
    print(f"Deliberacoes deliberadas       : {resultado['deliberacoes_deliberadas']}")
    print(f"Deliberacoes aplicadas         : {resultado['deliberacoes_aplicadas']}")
    print("---")
    print("ARQUIVOS ATUALIZADOS:")
    for nome in [
        "painel_operacional.json",
        "handoffs_agentes.json",
        "deliberacoes_conselho.json",
        "historico_deliberacoes.json",
        "estado_agente_secretario.json",
    ]:
        print(f"  {pasta / nome}")
    print(f"Log                            : {resultado['caminho_log']}")
    print("=" * 64)

    # Mostrar painel
    painel_path = pasta / "painel_operacional.json"
    if painel_path.exists():
        painel = json.loads(painel_path.read_text(encoding="utf-8"))

        print(f"\nPAINEL OPERACIONAL — {painel.get('data_referencia', '?')}")
        print(f"  {painel.get('resumo_geral', '')}")

        delib_data = painel.get("deliberacoes_conselho", {})
        pendentes   = delib_data.get("pendentes", []) if isinstance(delib_data, dict) else []
        deliberadas = delib_data.get("deliberadas_aguardando_aplicacao", []) if isinstance(delib_data, dict) else []
        aplicadas   = delib_data.get("aplicadas", []) if isinstance(delib_data, dict) else []

        if pendentes:
            print(f"\nDELIBERACOES PENDENTES — aguardando conselho ({len(pendentes)}):")
            for d in pendentes:
                print(f"  [{d.get('urgencia','?'):8}] {d.get('titulo','')[:65]}")
                print(f"           Recom: {d.get('recomendacao_agente','')[:70]}")

        if deliberadas:
            print(f"\nDELIBERADAS — aguardando aplicacao ({len(deliberadas)}):")
            for d in deliberadas:
                print(f"  [{d.get('urgencia','?'):8}] {d.get('titulo','')[:65]}")
                print(f"           Decisao: {d.get('decisao_conselho','')[:70]}")

        if aplicadas:
            print(f"\nDELIBERADAS — aplicadas ({len(aplicadas)}):")
            for d in aplicadas:
                print(f"  [{d.get('urgencia','?'):8}] {d.get('titulo','')[:65]}")
                print(f"           Decisao: {d.get('decisao_conselho','')[:60]} (aplicada)")

        bloqueios = painel.get("bloqueios", [])
        if bloqueios:
            print(f"\nBLOQUEIOS ({len(bloqueios)}):")
            vistos = set()
            for b in bloqueios[:3]:
                dest = b.get("agente_destino", "?")
                if dest not in vistos:
                    n = sum(1 for x in bloqueios if x.get("agente_destino") == dest)
                    print(f"  {n} item(ns) aguardando {dest} (agente nao implementado)")
                    vistos.add(dest)

        hfs = painel.get("handoffs_pendentes", [])
        if hfs:
            print(f"\nHANDOFFS PENDENTES ({len(hfs)}):")
            for hf in hfs[:5]:
                print(f"  {hf.get('agente_origem','?'):20} -> {hf.get('agente_destino','?'):25} | {hf.get('tipo_handoff','?')}")
                desc = hf.get("descricao", "")
                print(f"           {desc[:85]}")

        status = painel.get("status_por_agente", {})
        if status:
            print("\nSTATUS POR AGENTE:")
            sf = status.get("agente_financeiro", {})
            sc = status.get("agente_comercial",  {})
            print(f"  agente_financeiro : saldo={sf.get('ultimo_saldo')} | pendentes={sf.get('itens_pendentes_escalados')} | ultima_exec={sf.get('ultima_execucao','?')[:19]}")
            print(f"  agente_comercial  : pipeline={sc.get('pipeline_total')} | followups_pend={sc.get('followups_pendentes')} | ultima_exec={sc.get('ultima_execucao','?')[:19]}")


if __name__ == "__main__":
    main()
