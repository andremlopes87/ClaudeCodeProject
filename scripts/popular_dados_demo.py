"""
scripts/popular_dados_demo.py — Gera dados de demonstração realistas e marcados.

Todos os registros criados têm "demo": true para serem identificáveis e filtráveis.
Os dados são coerentes entre si: IDs se cruzam corretamente entre os arquivos.

Uso:
    python scripts/popular_dados_demo.py            # popula (acumula sobre existentes)
    python scripts/popular_dados_demo.py --limpar   # resetar antes de popular

Dados gerados:
    - 5 contas (lead → cliente_ativo)
    - 3 oportunidades no pipeline (qualificado, negociacao, proposta_enviada)
    - 2 entregas (em_execucao, concluida)
    - 1 contrato ativo com parcelas
    - Memória de agentes com resumos realistas
    - Saúde inicial das contas
    - NPS pendente para cliente com entrega concluída
"""

import sys
import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

PASTA = config.PASTA_DADOS
AGORA = datetime.now()


def _dt(dias: int) -> str:
    """Data relativa a hoje (negativo = passado, positivo = futuro)."""
    return (AGORA + timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S")


def _data(dias: int) -> str:
    return (AGORA + timedelta(days=dias)).strftime("%Y-%m-%d")


def _salvar(nome: str, dados) -> None:
    caminho = PASTA / nome
    PASTA.mkdir(parents=True, exist_ok=True)
    conteudo = json.dumps(dados, ensure_ascii=False, indent=2)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)
    print(f"  ok: {nome} ({len(dados) if isinstance(dados, list) else 'objeto'})")


def _carregar(nome: str, padrao=None):
    caminho = PASTA / nome
    if not caminho.exists():
        return padrao if padrao is not None else []
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return padrao if padrao is not None else []


# ─── IDs fixos dos registros demo ─────────────────────────────────────────────

CONTAS = {
    "lead":         "demo_conta_001",
    "oportunidade": "demo_conta_002",
    "negociacao":   "demo_conta_003",
    "implantacao":  "demo_conta_004",
    "ativo":        "demo_conta_005",
}

OPPS = {
    "qualificado":      "demo_opp_001",
    "negociacao":       "demo_opp_002",
    "proposta_enviada": "demo_opp_003",
}

ENTREGAS = {
    "em_execucao": "demo_ent_001",
    "concluida":   "demo_ent_002",
}

CONTRATOS = {
    "ativo": "demo_ct_001",
}


# ─── Contas ───────────────────────────────────────────────────────────────────

def gerar_contas() -> list:
    return [
        {
            "id": CONTAS["lead"],
            "nome_empresa": "Barbearia do Carlos",
            "nome_normalizado": "barbearia do carlos",
            "site": "",
            "instagram": "@barbearia_carlos_sp",
            "email_principal": "carlos@barbearia-carlos.com.br",
            "telefone_principal": "11987651001",
            "whatsapp": "+5511987651001",
            "cidade": "São Paulo",
            "categoria": "beleza",
            "origem_inicial": "prospeccao_marketing",
            "status_relacionamento": "lead",
            "fase_atual": "identificado",
            "oportunidade_ativa": False,
            "cliente_ativo": False,
            "risco_relacionamento": False,
            "valor_total_propostas": 0.0,
            "valor_total_fechado": 0.0,
            "entregas_ativas": 0,
            "oportunidade_ids": [],
            "proposta_ids": [],
            "entrega_ids": [],
            "tags": ["sem_instagram_ativo", "sem_site"],
            "observacoes": "Encontrado via prospecção. Perfil no Instagram desatualizado.",
            "criado_em": _dt(-15),
            "atualizado_em": _dt(-15),
            "faturamento_previsto": 0.0,
            "faturamento_recebido": 0.0,
            "contratos_ativos": 0,
            "contratos_concluidos": 0,
            "status_saude": "novo",
            "score_saude": 50,
            "potencial_expansao": False,
            "cliente_em_risco": False,
            "demo": True,
            "origem": "demo",
        },
        {
            "id": CONTAS["oportunidade"],
            "nome_empresa": "Oficina do Zé Mecânico",
            "nome_normalizado": "oficina do ze mecanico",
            "site": "",
            "instagram": "",
            "email_principal": "ze@oficina-ze.com.br",
            "telefone_principal": "11987652002",
            "whatsapp": "+5511987652002",
            "cidade": "São Paulo",
            "categoria": "automotivo",
            "origem_inicial": "prospeccao_marketing",
            "status_relacionamento": "oportunidade",
            "fase_atual": "diagnostico_enviado",
            "oportunidade_ativa": True,
            "cliente_ativo": False,
            "risco_relacionamento": False,
            "valor_total_propostas": 400.0,
            "valor_total_fechado": 0.0,
            "entregas_ativas": 0,
            "oportunidade_ids": [OPPS["qualificado"]],
            "proposta_ids": [],
            "entrega_ids": [],
            "tags": ["sem_presenca_digital", "alta_demanda_local"],
            "observacoes": "Diagnóstico de presença digital enviado. Aguardando retorno.",
            "criado_em": _dt(-10),
            "atualizado_em": _dt(-3),
            "faturamento_previsto": 400.0,
            "faturamento_recebido": 0.0,
            "contratos_ativos": 0,
            "contratos_concluidos": 0,
            "status_saude": "novo",
            "score_saude": 55,
            "potencial_expansao": False,
            "cliente_em_risco": False,
            "demo": True,
            "origem": "demo",
        },
        {
            "id": CONTAS["negociacao"],
            "nome_empresa": "Restaurante da Dona Maria",
            "nome_normalizado": "restaurante da dona maria",
            "site": "https://restaurante-donamaria.com.br",
            "instagram": "@restaurante_donamaria",
            "email_principal": "contato@restaurante-donamaria.com.br",
            "telefone_principal": "11987653003",
            "whatsapp": "+5511987653003",
            "cidade": "São Paulo",
            "categoria": "alimentacao",
            "origem_inicial": "prospeccao_marketing",
            "status_relacionamento": "oportunidade",
            "fase_atual": "proposta_enviada",
            "oportunidade_ativa": True,
            "cliente_ativo": False,
            "risco_relacionamento": False,
            "valor_total_propostas": 800.0,
            "valor_total_fechado": 0.0,
            "entregas_ativas": 0,
            "oportunidade_ids": [OPPS["negociacao"], OPPS["proposta_enviada"]],
            "proposta_ids": ["demo_prop_001"],
            "entrega_ids": [],
            "tags": ["site_desatualizado", "sem_whatsapp_business"],
            "observacoes": "Proposta de agendamento digital enviada. Negociando prazo de pagamento.",
            "criado_em": _dt(-20),
            "atualizado_em": _dt(-1),
            "faturamento_previsto": 800.0,
            "faturamento_recebido": 0.0,
            "contratos_ativos": 0,
            "contratos_concluidos": 0,
            "status_saude": "novo",
            "score_saude": 60,
            "potencial_expansao": True,
            "cliente_em_risco": False,
            "demo": True,
            "origem": "demo",
        },
        {
            "id": CONTAS["implantacao"],
            "nome_empresa": "Academia Fitness & Saúde",
            "nome_normalizado": "academia fitness e saude",
            "site": "https://academiafitness.com.br",
            "instagram": "@academia_fitness_sp",
            "email_principal": "admin@academiafitness.com.br",
            "telefone_principal": "11987654004",
            "whatsapp": "+5511987654004",
            "cidade": "São Paulo",
            "categoria": "saude_beleza",
            "origem_inicial": "prospeccao_marketing",
            "status_relacionamento": "cliente_em_implantacao",
            "fase_atual": "onboarding",
            "oportunidade_ativa": False,
            "cliente_ativo": True,
            "risco_relacionamento": False,
            "valor_total_propostas": 800.0,
            "valor_total_fechado": 800.0,
            "entregas_ativas": 1,
            "oportunidade_ids": ["demo_opp_implantacao"],
            "proposta_ids": ["demo_prop_002"],
            "entrega_ids": [ENTREGAS["em_execucao"]],
            "tags": ["onboarding_em_andamento"],
            "observacoes": "Contrato assinado. Entrega de agendamento digital em andamento.",
            "criado_em": _dt(-30),
            "atualizado_em": _dt(-2),
            "faturamento_previsto": 800.0,
            "faturamento_recebido": 0.0,
            "contratos_ativos": 1,
            "contratos_concluidos": 0,
            "status_saude": "atencao",
            "score_saude": 65,
            "potencial_expansao": True,
            "cliente_em_risco": False,
            "demo": True,
            "origem": "demo",
        },
        {
            "id": CONTAS["ativo"],
            "nome_empresa": "Padaria Pão & Arte",
            "nome_normalizado": "padaria pao e arte",
            "site": "https://padaria-paoarte.com.br",
            "instagram": "@padaria_paoarte",
            "email_principal": "contato@padaria-paoarte.com.br",
            "telefone_principal": "11987655005",
            "whatsapp": "+5511987655005",
            "cidade": "São Paulo",
            "categoria": "alimentacao",
            "origem_inicial": "prospeccao_marketing",
            "status_relacionamento": "cliente_ativo",
            "fase_atual": "ativo_estavel",
            "oportunidade_ativa": False,
            "cliente_ativo": True,
            "risco_relacionamento": False,
            "valor_total_propostas": 400.0,
            "valor_total_fechado": 400.0,
            "entregas_ativas": 0,
            "oportunidade_ids": ["demo_opp_ativo"],
            "proposta_ids": ["demo_prop_003"],
            "entrega_ids": [ENTREGAS["concluida"]],
            "tags": ["entrega_concluida", "nps_pendente"],
            "observacoes": "Presença digital básica entregue. Cliente satisfeito. NPS pendente.",
            "criado_em": _dt(-45),
            "atualizado_em": _dt(-5),
            "faturamento_previsto": 400.0,
            "faturamento_recebido": 400.0,
            "contratos_ativos": 0,
            "contratos_concluidos": 1,
            "status_saude": "saudavel",
            "score_saude": 82,
            "potencial_expansao": True,
            "cliente_em_risco": False,
            "demo": True,
            "origem": "demo",
        },
    ]


# ─── Pipeline comercial ───────────────────────────────────────────────────────

def gerar_pipeline_comercial() -> list:
    return [
        {
            "id": OPPS["qualificado"],
            "contraparte": "Oficina do Zé Mecânico",
            "conta_id": CONTAS["oportunidade"],
            "categoria": "automotivo",
            "cidade": "São Paulo",
            "estagio": "qualificado",
            "canal_sugerido": "email",
            "oferta_id": "presenca_digital_basica",
            "oferta_nome": "Presença Digital Básica",
            "valor_estimado": 400.0,
            "score": 72,
            "data_identificacao": _dt(-10),
            "data_ultimo_contato": _dt(-3),
            "proximo_passo": "enviar_proposta",
            "proximo_passo_em": _data(2),
            "notas": "Cliente interessado após diagnóstico. Sem presença digital nenhuma.",
            "demo": True,
        },
        {
            "id": OPPS["negociacao"],
            "contraparte": "Restaurante da Dona Maria",
            "conta_id": CONTAS["negociacao"],
            "categoria": "alimentacao",
            "cidade": "São Paulo",
            "estagio": "negociacao",
            "canal_sugerido": "whatsapp",
            "oferta_id": "agendamento_digital",
            "oferta_nome": "Agendamento Digital",
            "valor_estimado": 800.0,
            "score": 68,
            "data_identificacao": _dt(-20),
            "data_ultimo_contato": _dt(-2),
            "proximo_passo": "followup_proposta",
            "proximo_passo_em": _data(1),
            "notas": "Proposta enviada. Cliente pediu prazo para decidir. Retornar em 3 dias.",
            "demo": True,
        },
        {
            "id": OPPS["proposta_enviada"],
            "contraparte": "Restaurante da Dona Maria",
            "conta_id": CONTAS["negociacao"],
            "categoria": "alimentacao",
            "cidade": "São Paulo",
            "estagio": "proposta_enviada",
            "canal_sugerido": "email",
            "oferta_id": "atendimento_whatsapp",
            "oferta_nome": "Atendimento via WhatsApp",
            "valor_estimado": 600.0,
            "score": 65,
            "data_identificacao": _dt(-5),
            "data_ultimo_contato": _dt(-1),
            "proximo_passo": "aguardar_resposta",
            "proximo_passo_em": _data(3),
            "notas": "Proposta de WhatsApp Business enviada junto com agendamento. Cross-sell.",
            "demo": True,
        },
    ]


# ─── Pipeline de entrega ──────────────────────────────────────────────────────

def gerar_pipeline_entrega() -> list:
    return [
        {
            "id": ENTREGAS["em_execucao"],
            "oportunidade_id": "demo_opp_implantacao",
            "contraparte": "Academia Fitness & Saúde",
            "conta_id": CONTAS["implantacao"],
            "linha_servico": "marketing_presenca_digital",
            "tipo_entrega": "agendamento_digital",
            "oferta_id": "agendamento_digital",
            "status_entrega": "em_execucao",
            "data_inicio": _dt(-7),
            "data_prevista_conclusao": _data(0),
            "data_conclusao": None,
            "progresso_percentual": 70,
            "etapa_atual": "configuracao_sistema",
            "etapas_concluidas": [
                "levantamento_necessidades",
                "acesso_plataforma",
                "criacao_conta",
            ],
            "etapas_pendentes": [
                "configuracao_sistema",
                "treinamento_cliente",
                "validacao_final",
            ],
            "responsavel": "agente_operacao_entrega",
            "notas": "Cliente enviou credenciais. Configurando sistema de agendamento.",
            "demo": True,
        },
        {
            "id": ENTREGAS["concluida"],
            "oportunidade_id": "demo_opp_ativo",
            "contraparte": "Padaria Pão & Arte",
            "conta_id": CONTAS["ativo"],
            "linha_servico": "marketing_presenca_digital",
            "tipo_entrega": "presenca_digital_basica",
            "oferta_id": "presenca_digital_basica",
            "status_entrega": "concluida",
            "data_inicio": _dt(-40),
            "data_prevista_conclusao": _data(-37),
            "data_conclusao": _dt(-38),
            "progresso_percentual": 100,
            "etapa_atual": "concluido",
            "etapas_concluidas": [
                "levantamento_necessidades",
                "criacao_perfil_google",
                "configuracao_instagram",
                "treinamento_cliente",
                "validacao_final",
            ],
            "etapas_pendentes": [],
            "responsavel": "agente_operacao_entrega",
            "notas": "Entrega concluída com aprovação do cliente. NPS enviado.",
            "demo": True,
        },
    ]


# ─── Contrato ─────────────────────────────────────────────────────────────────

def gerar_contratos() -> list:
    return [
        {
            "id": CONTRATOS["ativo"],
            "conta_id": CONTAS["implantacao"],
            "oportunidade_id": "demo_opp_implantacao",
            "proposta_id": "demo_prop_002",
            "contraparte": "Academia Fitness & Saúde",
            "oferta_id": "agendamento_digital",
            "oferta_nome": "Agendamento Digital",
            "pacote_id": "ag_padrao",
            "pacote_nome": "Padrão",
            "linha_servico": "marketing_presenca_digital",
            "valor_total": 800.0,
            "modelo_cobranca": "avulso",
            "numero_parcelas": 2,
            "periodicidade": "mensal",
            "data_inicio": _data(-7),
            "data_fim_prevista": _data(7),
            "status": "ativo",
            "parcelas": [
                {
                    "numero": 1,
                    "valor": 400.0,
                    "vencimento": _data(-7),
                    "status": "pago",
                    "data_pagamento": _data(-7),
                },
                {
                    "numero": 2,
                    "valor": 400.0,
                    "vencimento": _data(7),
                    "status": "pendente",
                    "data_pagamento": None,
                },
            ],
            "assinado_em": _dt(-7),
            "criado_em": _dt(-8),
            "atualizado_em": _dt(-7),
            "notas": "Contrato assinado digitalmente. Primeira parcela quitada.",
            "demo": True,
        },
    ]


# ─── NPS pendente ──────────────────────────────────────────────────────────────

def gerar_nps_pendentes() -> list:
    return [
        {
            "id": "demo_nps_001",
            "conta_id": CONTAS["ativo"],
            "entrega_id": ENTREGAS["concluida"],
            "contraparte": "Padaria Pão & Arte",
            "email": "contato@padaria-paoarte.com.br",
            "oferta_id": "presenca_digital_basica",
            "enviado_em": _dt(-5),
            "status": "pendente",
            "resposta": None,
            "nota": None,
            "comentario": None,
            "respondido_em": None,
            "demo": True,
        },
    ]


# ─── Saúde das contas ─────────────────────────────────────────────────────────

def gerar_saude_contas() -> list:
    return [
        {
            "conta_id": CONTAS["lead"],
            "score": 50,
            "status": "novo",
            "fatores_positivos": [],
            "fatores_negativos": ["sem_contato_inicial"],
            "em_risco": False,
            "potencial_expansao": False,
            "calculado_em": _dt(-15),
            "demo": True,
        },
        {
            "conta_id": CONTAS["oportunidade"],
            "score": 55,
            "status": "novo",
            "fatores_positivos": ["diagnostico_enviado"],
            "fatores_negativos": ["aguardando_retorno_3_dias"],
            "em_risco": False,
            "potencial_expansao": False,
            "calculado_em": _dt(-3),
            "demo": True,
        },
        {
            "conta_id": CONTAS["negociacao"],
            "score": 60,
            "status": "neutro",
            "fatores_positivos": ["proposta_enviada", "interesse_confirmado"],
            "fatores_negativos": ["negociacao_prolongada"],
            "em_risco": False,
            "potencial_expansao": True,
            "calculado_em": _dt(-1),
            "demo": True,
        },
        {
            "conta_id": CONTAS["implantacao"],
            "score": 65,
            "status": "atencao",
            "fatores_positivos": ["contrato_ativo", "entrega_em_andamento"],
            "fatores_negativos": ["prazo_entrega_proximo"],
            "em_risco": False,
            "potencial_expansao": True,
            "calculado_em": _dt(-2),
            "demo": True,
        },
        {
            "conta_id": CONTAS["ativo"],
            "score": 82,
            "status": "saudavel",
            "fatores_positivos": ["entrega_concluida", "pagamento_em_dia", "cliente_engajado"],
            "fatores_negativos": ["nps_pendente"],
            "em_risco": False,
            "potencial_expansao": True,
            "calculado_em": _dt(-5),
            "demo": True,
        },
    ]


# ─── Memória de agentes ───────────────────────────────────────────────────────

def gerar_memoria_agentes() -> dict:
    return {
        "versao": "1.0",
        "atualizado_em": _dt(0),
        "demo": True,
        "resumos": {
            "agente_comercial": {
                "ultimo_ciclo": _dt(-1),
                "resumo": (
                    "Pipeline com 3 oportunidades ativas. "
                    "Restaurante da Dona Maria em negociação final — proposta enviada. "
                    "Oficina do Zé Mecânico qualificada, próximo passo: enviar proposta de presença digital."
                ),
                "metricas": {
                    "oportunidades_ativas": 3,
                    "propostas_enviadas": 1,
                    "taxa_conversao_estimada": 0.33,
                },
            },
            "agente_operacao_entrega": {
                "ultimo_ciclo": _dt(-1),
                "resumo": (
                    "1 entrega em execução (Academia Fitness, 70% concluída). "
                    "Prazo de conclusão: hoje. "
                    "1 entrega concluída com sucesso (Padaria Pão & Arte)."
                ),
                "metricas": {
                    "entregas_ativas": 1,
                    "entregas_concluidas_ciclo": 0,
                    "prazo_medio_dias": 3,
                },
            },
            "agente_customer_success": {
                "ultimo_ciclo": _dt(-1),
                "resumo": (
                    "1 cliente ativo saudável (score 82). "
                    "NPS pendente para Padaria Pão & Arte — entrega concluída há 5 dias. "
                    "Academia Fitness em implantação — monitorar prazo."
                ),
                "metricas": {
                    "clientes_saudaveis": 1,
                    "clientes_em_risco": 0,
                    "nps_pendentes": 1,
                },
            },
            "agente_financeiro": {
                "ultimo_ciclo": _dt(-1),
                "resumo": (
                    "Recebíveis: R$400 (parcela 2/2 Academia Fitness, vence em 7 dias). "
                    "Recebido no ciclo: R$400 (parcela 1/2 Academia Fitness). "
                    "Sem inadimplência."
                ),
                "metricas": {
                    "total_recebiveis": 400.0,
                    "total_recebido_ciclo": 400.0,
                    "contratos_ativos": 1,
                },
            },
        },
    }


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    limpar = "--limpar" in sys.argv

    if limpar:
        print("\nResetando dados antes de popular...")
        resultado = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "resetar_dados_simulados.py"), "--force"],
            capture_output=True, text=True
        )
        print(resultado.stdout)
        if resultado.returncode != 0:
            print("ERRO ao resetar:", resultado.stderr)
            sys.exit(1)

    print(f"\n{'-' * 60}")
    print(f"  popular_dados_demo.py")
    print(f"{'-' * 60}")
    print(f"\nGerando dados demo realistas...\n")

    _salvar("contas_clientes.json", gerar_contas())
    _salvar("pipeline_comercial.json", gerar_pipeline_comercial())
    _salvar("pipeline_entrega.json", gerar_pipeline_entrega())
    _salvar("contratos_clientes.json", gerar_contratos())
    _salvar("nps_pendentes.json", gerar_nps_pendentes())
    _salvar("saude_contas.json", gerar_saude_contas())
    _salvar("memoria_agentes.json", gerar_memoria_agentes())

    print(f"\n{'-' * 60}")
    print(f"\nDados demo criados com sucesso!")
    print(f"  - Todos os registros tem 'demo': true")
    print(f"  - 5 contas em diferentes estagios")
    print(f"  - 3 oportunidades no pipeline")
    print(f"  - 2 entregas (1 em execucao, 1 concluida)")
    print(f"  - 1 contrato ativo com 2 parcelas")
    print(f"  - 1 NPS pendente")
    print(f"  - Memoria dos agentes inicializada")
    print(f"\nAcesse o painel em http://localhost:8000 para visualizar.\n")


if __name__ == "__main__":
    main()
