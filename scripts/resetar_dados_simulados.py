"""
scripts/resetar_dados_simulados.py — Apaga dados runtime gerados em desenvolvimento.

Mantém arquivos de configuração (catálogo, políticas, templates, identidade, canais).
Apaga tudo que é gerado em runtime: contas, pipelines, filas, históricos, logs, etc.

Uso:
    python scripts/resetar_dados_simulados.py          # lista e pede confirmação
    python scripts/resetar_dados_simulados.py --force  # apaga sem confirmar
"""

import sys
import os
import glob
from pathlib import Path

# Ajustar path para importar config
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

PASTA = config.PASTA_DADOS

# ─── Arquivos de CONFIGURAÇÃO — NUNCA apagar ──────────────────────────────────
MANTER = {
    # Catálogo e negócio
    "catalogo_ofertas.json",
    "regras_comerciais_ofertas.json",
    "planos_execucao.json",
    "templates_proposta.json",
    "templates_email.json",
    "exemplos_tom_por_categoria.json",
    "guia_tom_comunicacao.json",
    "playbooks_customer_success.json",
    # Identidade e marca
    "identidade_empresa.json",
    "guia_comunicacao_empresa.json",
    "assinaturas_empresa.json",
    "canais_empresa.json",
    # Políticas
    "politicas_operacionais.json",
    "politicas_ti.json",
    # Configuração de canais
    "config_canal_email.json",
    "config_canal_whatsapp.json",
    "config_canal_telefone.json",
    "config_cenarios_contato.json",
    "config_leitor_respostas.json",
    "checklist_ativacao_email.json",
    # Governança
    "diretrizes_conselho.json",
    # Auth (nunca tocar)
    "auth_painel.json",
}

# ─── Padrões de arquivo que SÃO dados runtime ─────────────────────────────────
# Inclui arquivos com timestamp no nome (resultado_*, eventos_financeiros_*, etc)
PADROES_RUNTIME = [
    # Contas e relacionamento
    "contas_clientes.json",
    "contatos_contas.json",
    "contratos_clientes.json",
    "acompanhamentos_contas.json",
    "jornada_contas.json",
    "saude_contas.json",
    "nps_pendentes.json",
    "nps_respostas.json",
    "acoes_customer_success.json",
    "relatorio_customer_success.json",
    # Pipeline comercial
    "pipeline_comercial.json",
    "pipeline_entrega.json",
    "propostas_comerciais.json",
    "aceites_propostas.json",
    "envios_propostas.json",
    "respostas_propostas.json",
    "checklists_entrega.json",
    "insumos_entrega.json",
    "planos_faturamento.json",
    # Documentos
    "documentos_oficiais.json",
    "envios_documentos.json",
    "respostas_documentos.json",
    # Filas
    "fila_envio_email.json",
    "fila_envio_whatsapp.json",
    "fila_chamadas_telefone.json",
    "fila_followups.json",
    "fila_revisao.json",
    "fila_oportunidades_marketing.json",
    "fila_oportunidades_marketing_agente.json",
    "fila_oportunidades_presenca.json",
    "fila_oportunidades_prospeccao.json",
    "fila_propostas_marketing.json",
    "fila_execucao_comercial.json",
    "fila_execucao_contato.json",
    "fila_decisoes_consolidada.json",
    "fila_decisoes_financeiras.json",
    "fila_alertas_financeiros.json",
    "fila_riscos_financeiros.json",
    # Financeiro
    "contas_a_pagar.json",
    "contas_a_receber.json",
    "posicao_caixa.json",
    "previsao_caixa.json",
    "eventos_financeiros.json",
    "resumo_financeiro_operacional.json",
    "aprovacoes.json",
    # Históricos
    "historico_abordagens.json",
    "historico_acompanhamento_contas.json",
    "historico_aplicacao_politicas.json",
    "historico_auditorias_seguranca.json",
    "historico_cenarios_contato.json",
    "historico_comandos_conselho.json",
    "historico_contas_clientes.json",
    "historico_contatos_contas.json",
    "historico_contratos.json",
    "historico_deliberacoes.json",
    "historico_documentos_oficiais.json",
    "historico_email.json",
    "historico_entrega.json",
    "historico_envios_documentos.json",
    "historico_envios_propostas.json",
    "historico_execucao_contato.json",
    "historico_fechamento_comercial.json",
    "historico_geracao_insumos_entrega.json",
    "historico_identidade_empresa.json",
    "historico_marketing_agente.json",
    "historico_melhorias.json",
    "historico_nps.json",
    "historico_ofertas_empresa.json",
    "historico_propostas_comerciais.json",
    "historico_prospeccao_agente.json",
    "historico_qualidade.json",
    "historico_reconciliacao_contratos.json",
    "historico_respostas_documentos.json",
    # Estado de agentes
    "estado_empresa.json",
    "estado_agente_comercial.json",
    "estado_agente_customer_success.json",
    "estado_agente_executor_contato.json",
    "estado_agente_financeiro.json",
    "estado_agente_marketing.json",
    "estado_agente_operacao_entrega.json",
    "estado_agente_prospeccao.json",
    "estado_agente_secretario.json",
    "estado_canais.json",
    "estado_canal_email.json",
    "estado_governanca_conselho.json",
    "estado_integrador_canais.json",
    "estado_multi_cidade.json",
    # Memória e logs
    "memoria_agentes.json",
    "log_llm.json",
    "resumo_diario_llm.json",
    "feed_eventos_empresa.json",
    "incidentes_operacionais.json",
    "handoffs_agentes.json",
    "handoff_fase3.json",
    # Scheduler e ciclo
    "scheduler_estado.json",
    "scheduler_log.json",
    "ciclo_operacional.json",
    "lock_ciclo_empresa.json",
    "recovery_ciclo.json",
    "agenda_do_dia.json",
    # Métricas e painéis
    "metricas_empresa.json",
    "metricas_agentes.json",
    "metricas_areas.json",
    "metricas_email.json",
    "saude_empresa.json",
    "painel_conselho.json",
    "painel_operacional.json",
    # Prospecção / marketing
    "candidatas_com_canais_digitais.json",
    "prospeccao_historico.json",
    "prospeccao_resumo_execucao.json",
    "oportunidades_expansao.json",
    # Deliberações e comandos
    "deliberacoes_conselho.json",
    "comandos_conselho.json",
    # Contato e respostas
    "respostas_email.json",
    "acoes_respostas.json",
    "resultados_chamadas.json",
    "resultados_contato.json",
    "respostas_simuladas_contato.json",
    # Outros
    "provisionamento_email_real.json",
    "prontidao_canais_reais.json",
    "relatorio_melhorias.json",
    "relatorio_qualidade.json",
    "relatorio_seguranca.json",
    "aprovacoes.json",
]

# Padrões glob para arquivos com timestamp (resultado_*, eventos_*, fila_*_2026-*, etc.)
PADROES_GLOB = [
    "resultado_*.json",
    "eventos_financeiros_2*.json",
    "fila_alertas_financeiros_2*.json",
    "fila_decisoes_financeiras_2*.json",
    "fila_oportunidades_marketing_2*.json",
    "fila_propostas_marketing_2*.json",
    "fila_execucao_comercial_2*.json",
    "fila_riscos_financeiros_2*.json",
    "posicao_caixa_2*.json",
    "previsao_caixa_2*.json",
    "resumo_financeiro_operacional_2*.json",
    "contas_a_pagar_2*.json",
    "contas_a_receber_2*.json",
]


def _coletar_alvos() -> list[Path]:
    """Retorna lista de arquivos que serão apagados."""
    alvos = set()

    # Arquivos fixos listados
    for nome in PADROES_RUNTIME:
        p = PASTA / nome
        if p.exists():
            alvos.add(p)

    # Arquivos com timestamp via glob
    for padrao in PADROES_GLOB:
        for p in PASTA.glob(padrao):
            if p.name not in MANTER:
                alvos.add(p)

    # Também apagar .bak e .tmp dos alvos
    extras = set()
    for p in alvos:
        for ext in (".json.bak", ".json.tmp"):
            variante = p.with_suffix("").with_suffix(ext)
            if variante.exists():
                extras.add(variante)

    return sorted(alvos | extras)


def _apagar(alvos: list[Path]) -> int:
    apagados = 0
    for p in alvos:
        try:
            p.unlink()
            apagados += 1
        except OSError as e:
            print(f"  ERRO ao apagar {p.name}: {e}")
    return apagados


def main():
    force = "--force" in sys.argv

    alvos = _coletar_alvos()

    if not alvos:
        print("Nenhum arquivo runtime encontrado em dados/. Nada a fazer.")
        return

    print(f"\n{'-' * 60}")
    print(f"  resetar_dados_simulados.py")
    print(f"{'-' * 60}")
    print(f"\nArquivos que serao APAGADOS ({len(alvos)}):\n")

    # Agrupar por categoria para leitura fácil
    for p in alvos:
        print(f"  - {p.name}")

    print(f"\nArquivos que serao MANTIDOS (configuracao):\n")
    mantidos = sorted(f for f in MANTER if (PASTA / f).exists())
    for nome in mantidos:
        print(f"  + {nome}")

    print(f"\n{'-' * 60}")

    if not force:
        resposta = input("\nConfirmar apagamento? [s/N] ").strip().lower()
        if resposta not in ("s", "sim", "y", "yes"):
            print("Cancelado.")
            return

    apagados = _apagar(alvos)
    print(f"\nOK: {apagados} arquivo(s) apagado(s).")
    print("  Os arquivos de configuracao foram mantidos intactos.")
    print("  Execute python scripts/popular_dados_demo.py para gerar dados demo.\n")


if __name__ == "__main__":
    main()
