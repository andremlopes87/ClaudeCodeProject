"""
main_agente_financeiro.py — Ponto de entrada do agente financeiro.

Executa o agente financeiro operacional:
  - lê dados financeiros atuais
  - recalcula posição e previsão
  - classifica o que pode tratar sozinho
  - escala o que exige decisão humana

Para uso real:
  - Execute periodicamente (diário ou quando novos dados forem registrados)
  - As saídas ficam em dados/ e logs/agentes/
  - Aprovações humanas vão em dados/aprovacoes.json
  - Agenda do dia consolidada em dados/agenda_do_dia.json
"""

import json
from pathlib import Path

import config
from agentes.financeiro.agente_financeiro import executar


def main() -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    _inicializar_arquivos_base()

    resultado = executar()

    pasta = config.PASTA_DADOS
    print("\n" + "=" * 64)
    print("AGENTE FINANCEIRO")
    print("=" * 64)
    print(f"Saldo atual                    : R$ {resultado['saldo_atual']:>10,.2f}")
    print(f"Saldo previsto                 : R$ {resultado['saldo_previsto']:>10,.2f}")
    print(f"Risco de caixa                 : {'SIM' if resultado['risco_caixa'] else 'nao'}")
    print("---")
    print(f"Riscos identificados           : {resultado['total_riscos']}")
    print(f"Alertas                        : {resultado['total_alertas']}")
    print("---")
    print(f"Itens tratados autonomamente   : {resultado['autonomos']}")
    print(f"Itens escalados ao usuario     : {resultado['escalados']}")
    print(f"Aprovacoes resolvidas          : {resultado['aprovados_nesta_exec']}")
    print("---")
    print("ARQUIVOS ATUALIZADOS:")
    for nome in [
        "posicao_caixa.json",
        "previsao_caixa.json",
        "fila_alertas_financeiros.json",
        "fila_riscos_financeiros.json",
        "fila_decisoes_financeiras.json",
        "fila_decisoes_consolidada.json",
        "agenda_do_dia.json",
        "estado_agente_financeiro.json",
    ]:
        print(f"  {pasta / nome}")
    print(f"Log                            : {resultado['caminho_log']}")
    print("=" * 64)

    # Mostrar itens na agenda do dia
    agenda_path = pasta / "agenda_do_dia.json"
    if agenda_path.exists():
        agenda = json.loads(agenda_path.read_text(encoding="utf-8"))
        itens  = agenda.get("itens", [])
        if itens:
            print(f"\nAGENDA DO DIA ({agenda.get('data', '?')}) — {len(itens)} item(ns) para o usuario:")
            for item in itens:
                prazo = f" | prazo: {item['prazo_sugerido']}" if item.get("prazo_sugerido") else ""
                print(f"  [{item.get('urgencia', '?'):6}] {item.get('tipo', '?')} — {item.get('descricao', '')[:70]}")
                print(f"           Acao: {item.get('acao_sugerida', '')[:80]}{prazo}")
                print(f"           Status: {item.get('status_aprovacao', '?')}")


def _inicializar_arquivos_base() -> None:
    """Cria arquivos base se não existirem (primeira execução)."""
    pasta = config.PASTA_DADOS

    _criar_se_ausente(pasta / "aprovacoes.json", [])
    _criar_se_ausente(pasta / "fila_decisoes_consolidada.json", [])
    _criar_se_ausente(pasta / "agenda_do_dia.json", {
        "data": "",
        "itens": [],
        "gerado_em": "",
    })


def _criar_se_ausente(caminho: Path, padrao) -> None:
    if not caminho.exists():
        caminho.write_text(
            json.dumps(padrao, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
