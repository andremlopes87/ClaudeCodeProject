"""
core/ofertas_empresa.py

Camada oficial de ofertas, escopos e regras comerciais da Vetor.

Responsabilidades:
  - Carregar e servir o catálogo de ofertas (catalogo_ofertas.json)
  - Sugerir oferta/pacote por oportunidade (linha_servico + sinais)
  - Enriquecer dicts de oportunidade com oferta_id/pacote_id/valor_referencia
  - Fornecer checklist de entrega por oferta e pacote
  - Verificar gatilhos de deliberação (alta customização, valor acima do teto)
  - Verificar critérios de pronto_para_entrega por oferta
  - Registrar histórico de decisões de oferta

Arquivos gerenciados:
  dados/catalogo_ofertas.json
  dados/regras_comerciais_ofertas.json
  dados/templates_proposta.json
  dados/historico_ofertas_empresa.json
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_CATALOGO   = config.PASTA_DADOS / "catalogo_ofertas.json"
_ARQ_REGRAS     = config.PASTA_DADOS / "regras_comerciais_ofertas.json"
_ARQ_TEMPLATES  = config.PASTA_DADOS / "templates_proposta.json"
_ARQ_HISTORICO  = config.PASTA_DADOS / "historico_ofertas_empresa.json"

# ─── Defaults do catálogo (seed embutido) ─────────────────────────────────────

_CATALOGO_PADRAO: dict = {
    "empresa": "Vetor Operações Ltda",
    "versao":  "1.0",
    "criado_em": "2026-03-23",
    "ofertas": [
        {
            "id":          "diagnostico_presenca_digital",
            "nome":        "Diagnóstico de Presença Digital",
            "linha_servico": "marketing_presenca_digital",
            "descricao":   (
                "Mapeamento completo da presença digital da empresa: site, redes sociais, "
                "Google Business, atendimento online e gaps prioritários."
            ),
            "entregaveis_base": [
                "Relatório de diagnóstico digital",
                "Mapa de canais ativos e inativos",
                "Lista priorizada de gaps",
                "Recomendações de ações imediatas",
            ],
            "sinais_qualificadores": ["site_ausente", "redes_fracas", "sem_google_business",
                                       "sem_presenca_digital", "marketing_precario"],
            "pacotes": [
                {
                    "id":     "dpd_essencial",
                    "nome":   "Essencial",
                    "valor_referencia": 890.0,
                    "prazo_dias": 7,
                    "descricao": "Diagnóstico rápido — levantamento de canais e gaps principais.",
                    "entregaveis": ["Relatório de diagnóstico (1 pág.)", "Top 3 recomendações"],
                    "checklist_entrega": [
                        "Levantar canais digitais ativos",
                        "Verificar site e velocidade básica",
                        "Verificar Google Business",
                        "Identificar top 3 gaps",
                        "Redigir relatório de diagnóstico",
                        "Revisar e enviar ao cliente",
                    ],
                },
                {
                    "id":     "dpd_padrao",
                    "nome":   "Padrão",
                    "valor_referencia": 1890.0,
                    "prazo_dias": 14,
                    "descricao": "Diagnóstico completo com mapa de concorrentes locais e plano de ação.",
                    "entregaveis": ["Relatório completo", "Mapa de concorrência local",
                                    "Plano de ação em 30 dias"],
                    "checklist_entrega": [
                        "Levantar todos os canais digitais",
                        "Analisar site (velocidade, SEO básico, UX)",
                        "Analisar redes sociais e engajamento",
                        "Mapear 3 concorrentes locais",
                        "Verificar Google Business e avaliações",
                        "Identificar gaps e oportunidades",
                        "Redigir plano de ação 30 dias",
                        "Revisar e apresentar ao cliente",
                    ],
                },
                {
                    "id":     "dpd_avancado",
                    "nome":   "Avançado",
                    "valor_referencia": 3490.0,
                    "prazo_dias": 21,
                    "descricao": "Diagnóstico + implantação de correções prioritárias + acompanhamento.",
                    "entregaveis": ["Relatório completo", "Implantação das correções prioritárias",
                                    "Acompanhamento por 30 dias", "Relatório de evolução"],
                    "checklist_entrega": [
                        "Levantar todos os canais digitais",
                        "Análise profunda de site, redes e SEO local",
                        "Mapear concorrentes locais (5+)",
                        "Identificar quick wins",
                        "Executar correções prioritárias (site, GMB, redes)",
                        "Redigir plano de ação 60 dias",
                        "Configurar métricas de acompanhamento",
                        "Revisar e apresentar ao cliente",
                        "Acompanhamento semana 2 e 4",
                        "Relatório de evolução final",
                    ],
                },
            ],
        },
        {
            "id":          "operacao_comercial_base",
            "nome":        "Operação Comercial Base",
            "linha_servico": "automacao_atendimento",
            "descricao":   (
                "Estruturação do processo comercial: atendimento por WhatsApp, "
                "qualificação de leads, follow-up automático e pipeline básico."
            ),
            "entregaveis_base": [
                "Fluxo de atendimento estruturado",
                "Scripts de abordagem e follow-up",
                "Configuração de canal WhatsApp Business",
                "Pipeline de vendas básico",
            ],
            "sinais_qualificadores": ["sem_processo_comercial", "atendimento_manual",
                                       "sem_whatsapp_business", "leads_sem_followup"],
            "pacotes": [
                {
                    "id":     "ocb_essencial",
                    "nome":   "Essencial",
                    "valor_referencia": 1290.0,
                    "prazo_dias": 10,
                    "descricao": "Script de atendimento + WhatsApp Business configurado.",
                    "entregaveis": ["Script de atendimento (3 etapas)",
                                    "WhatsApp Business configurado"],
                    "checklist_entrega": [
                        "Entender processo atual de atendimento",
                        "Mapear perfil do cliente ideal",
                        "Redigir script de atendimento (3 etapas)",
                        "Configurar WhatsApp Business",
                        "Testar script com cliente",
                        "Entregar e treinar responsável",
                    ],
                },
                {
                    "id":     "ocb_padrao",
                    "nome":   "Padrão",
                    "valor_referencia": 2490.0,
                    "prazo_dias": 21,
                    "descricao": "Script + pipeline + follow-up automático (sem integração externa).",
                    "entregaveis": ["Script completo", "Pipeline documentado",
                                    "Rotina de follow-up", "Treinamento"],
                    "checklist_entrega": [
                        "Entender processo atual e gargalos",
                        "Definir etapas do pipeline comercial",
                        "Redigir scripts por etapa (abertura, follow-up, fechamento)",
                        "Documentar rotina de follow-up",
                        "Configurar WhatsApp Business + catálogo",
                        "Configurar lembretes de follow-up",
                        "Treinar responsável comercial",
                        "Revisão pós-implantação (7 dias)",
                    ],
                },
                {
                    "id":     "ocb_avancado",
                    "nome":   "Avançado",
                    "valor_referencia": 4490.0,
                    "prazo_dias": 30,
                    "descricao": "Operação comercial completa + automação de follow-up + relatórios.",
                    "entregaveis": ["Pipeline completo", "Automação de follow-up",
                                    "Dashboard de leads", "Relatórios mensais"],
                    "checklist_entrega": [
                        "Diagnóstico comercial completo",
                        "Definir funil e etapas do pipeline",
                        "Redigir scripts por perfil de cliente",
                        "Configurar automação de follow-up",
                        "Integrar canal WhatsApp à rotina",
                        "Configurar planilha/dashboard de leads",
                        "Treinar equipe",
                        "Acompanhar primeira semana de operação",
                        "Ajustar scripts com base em resultados",
                        "Relatório de desempenho mês 1",
                    ],
                },
            ],
        },
        {
            "id":          "estruturacao_financeira_operacional",
            "nome":        "Estruturação Financeira Operacional",
            "linha_servico": "gestao_financeira",
            "descricao":   (
                "Organização do fluxo de caixa, categorização de receitas e despesas, "
                "controle de contas a pagar/receber e visibilidade financeira básica."
            ),
            "entregaveis_base": [
                "Mapa de fluxo de caixa",
                "Categorização de receitas e despesas",
                "Rotina de controle financeiro",
                "Planilha de acompanhamento",
            ],
            "sinais_qualificadores": ["sem_controle_financeiro", "fluxo_desorganizado",
                                       "inadimplencia_alta", "sem_previsibilidade"],
            "pacotes": [
                {
                    "id":     "efo_essencial",
                    "nome":   "Essencial",
                    "valor_referencia": 990.0,
                    "prazo_dias": 7,
                    "descricao": "Mapeamento financeiro básico e planilha de controle.",
                    "entregaveis": ["Planilha de fluxo de caixa", "Categorias definidas"],
                    "checklist_entrega": [
                        "Coletar dados financeiros dos últimos 3 meses",
                        "Categorizar receitas e despesas",
                        "Montar planilha de fluxo de caixa",
                        "Identificar os 3 maiores gargalos financeiros",
                        "Entregar e treinar responsável",
                    ],
                },
                {
                    "id":     "efo_padrao",
                    "nome":   "Padrão",
                    "valor_referencia": 2190.0,
                    "prazo_dias": 21,
                    "descricao": "Controle financeiro + DRE simplificado + rotina de revisão mensal.",
                    "entregaveis": ["DRE simplificado", "Planilha de controle",
                                    "Rotina de revisão mensal", "Treinamento"],
                    "checklist_entrega": [
                        "Coletar dados financeiros dos últimos 6 meses",
                        "Categorizar e classificar lançamentos",
                        "Montar DRE simplificado",
                        "Projetar fluxo de caixa 90 dias",
                        "Definir rotina de revisão mensal",
                        "Montar dashboard financeiro básico",
                        "Treinar responsável financeiro",
                        "Revisão após 30 dias de uso",
                    ],
                },
                {
                    "id":     "efo_avancado",
                    "nome":   "Avançado",
                    "valor_referencia": 3990.0,
                    "prazo_dias": 30,
                    "descricao": "Estruturação financeira completa + controle de inadimplência + relatórios.",
                    "entregaveis": ["DRE completo", "Controle de contas a receber",
                                    "Rotina de cobrança", "Relatórios mensais por 3 meses"],
                    "checklist_entrega": [
                        "Diagnóstico financeiro completo",
                        "Organizar contas a pagar e receber",
                        "Montar DRE e balanço simplificado",
                        "Projetar fluxo de caixa 6 meses",
                        "Implementar rotina de cobrança",
                        "Definir indicadores financeiros chave",
                        "Configurar alertas de inadimplência",
                        "Treinar equipe",
                        "Relatórios mensais (3 meses)",
                        "Revisão trimestral",
                    ],
                },
            ],
        },
        {
            "id":          "acompanhamento_implantacao_operacional",
            "nome":        "Acompanhamento de Implantação",
            "linha_servico": "gestao_comercial",
            "descricao":   (
                "Suporte contínuo pós-implantação: revisões periódicas, ajustes de processo "
                "e relatórios de evolução. Complementar às demais ofertas."
            ),
            "entregaveis_base": [
                "Revisões periódicas agendadas",
                "Relatórios de evolução",
                "Ajustes de processo conforme necessidade",
            ],
            "sinais_qualificadores": ["pediu_acompanhamento", "quer_suporte_continuo"],
            "pacotes": [
                {
                    "id":     "aio_mensal",
                    "nome":   "Mensal",
                    "valor_referencia": 590.0,
                    "prazo_dias": 30,
                    "descricao": "1 revisão mensal + relatório de evolução.",
                    "entregaveis": ["Revisão mensal", "Relatório de evolução"],
                    "checklist_entrega": [
                        "Agendar revisão mensal",
                        "Coletar métricas do período",
                        "Revisar andamento com responsável",
                        "Identificar ajustes necessários",
                        "Redigir relatório de evolução",
                        "Planejar próximo ciclo",
                    ],
                },
                {
                    "id":     "aio_trimestral",
                    "nome":   "Trimestral",
                    "valor_referencia": 1490.0,
                    "prazo_dias": 90,
                    "descricao": "3 revisões mensais + relatório trimestral consolidado.",
                    "entregaveis": ["3 revisões mensais", "Relatório trimestral consolidado"],
                    "checklist_entrega": [
                        "Revisões mensais (×3)",
                        "Consolidar métricas do trimestre",
                        "Identificar evoluções e gargalos",
                        "Propor ajustes estruturais se necessário",
                        "Relatório trimestral consolidado",
                        "Planejamento do próximo trimestre",
                    ],
                },
            ],
        },
    ],
}

_REGRAS_PADRAO: dict = {
    "versao": "1.0",
    "criado_em": "2026-03-23",
    "desconto_maximo_sem_aprovacao_percentual": 15,
    "valor_minimo_sem_deliberacao": 0,
    "valor_maximo_sem_deliberacao": 5000.0,
    "grau_customizacao_alto_exige_deliberacao": True,
    "pacotes_customizaveis": True,
    "prazo_minimo_proposta_dias": 2,
    "regras_por_oferta": {
        "diagnostico_presenca_digital": {
            "desconto_maximo_percentual": 20,
            "exige_escopo_antes_de_ganho": False,
            "permite_parcelamento": False,
        },
        "operacao_comercial_base": {
            "desconto_maximo_percentual": 15,
            "exige_escopo_antes_de_ganho": True,
            "permite_parcelamento": True,
            "max_parcelas": 3,
        },
        "estruturacao_financeira_operacional": {
            "desconto_maximo_percentual": 10,
            "exige_escopo_antes_de_ganho": True,
            "permite_parcelamento": True,
            "max_parcelas": 3,
        },
        "acompanhamento_implantacao_operacional": {
            "desconto_maximo_percentual": 10,
            "exige_escopo_antes_de_ganho": False,
            "permite_parcelamento": False,
        },
    },
}

_TEMPLATES_PADRAO: dict = {
    "versao": "1.0",
    "criado_em": "2026-03-23",
    "templates": {
        "marketing_presenca_digital": {
            "assunto": "Proposta: {nome_oferta} para {nome_empresa}",
            "intro": (
                "Olá, {nome_contato}. Seguindo nossa conversa, preparei uma proposta "
                "de {nome_oferta} pensada para o momento da {nome_empresa}."
            ),
            "corpo": (
                "Com base no que identificamos, a principal oportunidade está em {gap_principal}. "
                "O pacote {nome_pacote} cobre: {entregaveis}. "
                "Investimento: R$ {valor_referencia} | Prazo: {prazo_dias} dias úteis."
            ),
            "fechamento": (
                "Posso ajustar o escopo conforme sua necessidade. "
                "Quando podemos alinhar os próximos passos?"
            ),
        },
        "automacao_atendimento": {
            "assunto": "Proposta: {nome_oferta} para {nome_empresa}",
            "intro": (
                "Olá, {nome_contato}. Conforme conversamos, preparei uma proposta "
                "para estruturar a operação comercial da {nome_empresa}."
            ),
            "corpo": (
                "O foco é {gap_principal}. "
                "O pacote {nome_pacote} entrega: {entregaveis}. "
                "Investimento: R$ {valor_referencia} | Prazo: {prazo_dias} dias úteis."
            ),
            "fechamento": (
                "O objetivo é que a equipe opere com mais fluidez e menos perda de leads. "
                "Quando podemos avançar?"
            ),
        },
        "gestao_financeira": {
            "assunto": "Proposta: {nome_oferta} para {nome_empresa}",
            "intro": (
                "Olá, {nome_contato}. Preparei uma proposta para dar mais clareza "
                "e controle financeiro para a {nome_empresa}."
            ),
            "corpo": (
                "O ponto crítico identificado é {gap_principal}. "
                "O pacote {nome_pacote} resolve isso com: {entregaveis}. "
                "Investimento: R$ {valor_referencia} | Prazo: {prazo_dias} dias úteis."
            ),
            "fechamento": (
                "Com isso, você terá visibilidade real do caixa e dos resultados. "
                "Posso enviar o contrato assim que confirmarmos o escopo."
            ),
        },
        "gestao_comercial": {
            "assunto": "Proposta: {nome_oferta} para {nome_empresa}",
            "intro": "Olá, {nome_contato}. Segue proposta de acompanhamento para {nome_empresa}.",
            "corpo": (
                "Para garantir a continuidade dos resultados, o pacote {nome_pacote} inclui: {entregaveis}. "
                "Investimento: R$ {valor_referencia} | Ciclo: {prazo_dias} dias."
            ),
            "fechamento": "Confirme para programarmos o início.",
        },
        "padrao": {
            "assunto": "Proposta comercial para {nome_empresa}",
            "intro":   "Olá, {nome_contato}. Segue nossa proposta para {nome_empresa}.",
            "corpo":   (
                "Pacote sugerido: {nome_pacote}. Entregáveis: {entregaveis}. "
                "Investimento: R$ {valor_referencia} | Prazo: {prazo_dias} dias úteis."
            ),
            "fechamento": "Estamos disponíveis para ajustar conforme necessário.",
        },
    },
}


# ─── Carregamento ──────────────────────────────────────────────────────────────

def _ler(arq: Path, padrao) -> dict:
    try:
        if arq.exists():
            with open(arq, encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        log.warning(f"[ofertas] falha ao ler {arq.name}: {exc}")
    return padrao if isinstance(padrao, dict) else {}


def _salvar(arq: Path, dados) -> None:
    try:
        arq.parent.mkdir(parents=True, exist_ok=True)
        with open(arq, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.warning(f"[ofertas] falha ao salvar {arq.name}: {exc}")


def carregar_catalogo() -> dict:
    """Carrega catálogo — cria com defaults se ausente."""
    dados = _ler(_ARQ_CATALOGO, {})
    if not dados.get("ofertas"):
        _salvar(_ARQ_CATALOGO, _CATALOGO_PADRAO)
        return _CATALOGO_PADRAO
    return dados


def carregar_regras() -> dict:
    dados = _ler(_ARQ_REGRAS, {})
    if not dados.get("versao"):
        _salvar(_ARQ_REGRAS, _REGRAS_PADRAO)
        return _REGRAS_PADRAO
    return dados


def carregar_templates() -> dict:
    dados = _ler(_ARQ_TEMPLATES, {})
    if not dados.get("versao"):
        _salvar(_ARQ_TEMPLATES, _TEMPLATES_PADRAO)
        return _TEMPLATES_PADRAO
    return dados


# ─── Índices rápidos ──────────────────────────────────────────────────────────

def _indice_por_id(catalogo: dict) -> dict:
    """Retorna {oferta_id: oferta_dict}."""
    return {o["id"]: o for o in catalogo.get("ofertas", [])}


def _indice_pacotes(oferta: dict) -> dict:
    """Retorna {pacote_id: pacote_dict} para uma oferta."""
    return {p["id"]: p for p in oferta.get("pacotes", [])}


def _oferta_por_linha(catalogo: dict, linha: str):
    """Retorna a primeira oferta que corresponde à linha_servico."""
    for o in catalogo.get("ofertas", []):
        if o.get("linha_servico") == linha:
            return o
    return None


# ─── Sugestão de oferta ───────────────────────────────────────────────────────

def sugerir_oferta_por_oportunidade(opp: dict) -> dict:
    """
    Dado um dict de oportunidade, retorna:
    {
      "oferta_id":         str | None,
      "pacote_id":         str | None,
      "nome_oferta":       str,
      "nome_pacote":       str,
      "valor_referencia":  float | None,
      "prazo_dias":        int | None,
      "confianca":         "alta" | "media" | "baixa",
      "motivo":            str,
    }
    """
    catalogo = carregar_catalogo()
    linha    = opp.get("linha_servico_sugerida", "")
    prioridade = opp.get("prioridade", "media")
    score_opp  = opp.get("score_qualificacao", 0)

    oferta = _oferta_por_linha(catalogo, linha)
    if not oferta:
        return {
            "oferta_id": None, "pacote_id": None,
            "nome_oferta": "—", "nome_pacote": "—",
            "valor_referencia": None, "prazo_dias": None,
            "confianca": "baixa",
            "motivo": f"nenhuma oferta mapeada para linha={linha}",
        }

    pacotes = oferta.get("pacotes", [])
    if not pacotes:
        return {
            "oferta_id": oferta["id"], "pacote_id": None,
            "nome_oferta": oferta["nome"], "nome_pacote": "—",
            "valor_referencia": None, "prazo_dias": None,
            "confianca": "media",
            "motivo": "oferta encontrada mas sem pacotes definidos",
        }

    # Selecionar pacote por prioridade / score
    # alta prioridade ou score alto → padrão; muito alta → avancado; baixa → essencial
    if prioridade == "alta" and score_opp >= 6:
        idx_pacote = min(2, len(pacotes) - 1)  # avancado se existir
        confianca  = "alta"
    elif prioridade == "alta" or score_opp >= 3:
        idx_pacote = min(1, len(pacotes) - 1)  # padrao
        confianca  = "alta"
    else:
        idx_pacote = 0   # essencial
        confianca  = "media"

    pacote = pacotes[idx_pacote]
    return {
        "oferta_id":        oferta["id"],
        "pacote_id":        pacote["id"],
        "nome_oferta":      oferta["nome"],
        "nome_pacote":      pacote["nome"],
        "valor_referencia": pacote.get("valor_referencia"),
        "prazo_dias":       pacote.get("prazo_dias"),
        "confianca":        confianca,
        "motivo":           f"linha={linha} | prioridade={prioridade} | score={score_opp}",
    }


# ─── Enriquecimento de oportunidade ──────────────────────────────────────────

def enriquecer_oportunidade_com_oferta(opp: dict) -> dict:
    """
    Adiciona campos de oferta ao dict de oportunidade in-place se ainda não tiver.
    Retorna o dict modificado.
    """
    if opp.get("oferta_id"):
        return opp  # já enriquecida

    sugestao = sugerir_oferta_por_oportunidade(opp)
    if sugestao["oferta_id"]:
        opp["oferta_id"]        = sugestao["oferta_id"]
        opp["pacote_id"]        = sugestao["pacote_id"]
        opp["nome_oferta"]      = sugestao["nome_oferta"]
        opp["nome_pacote"]      = sugestao["nome_pacote"]
        opp["valor_referencia"] = sugestao["valor_referencia"]
        opp["prazo_dias_oferta"] = sugestao["prazo_dias"]
        opp["oferta_confianca"] = sugestao["confianca"]

        registrar_evento_oferta(
            "oferta_sugerida",
            f"Oferta {sugestao['oferta_id']} / pacote {sugestao['pacote_id']} "
            f"sugerida para opp {opp.get('id','?')} ({opp.get('contraparte','?')}) — "
            f"confiança={sugestao['confianca']}",
            origem="agente_comercial",
            opp_id=opp.get("id"),
        )
        log.info(
            f"[ofertas] opp {opp.get('id')} enriquecida: "
            f"{sugestao['oferta_id']}/{sugestao['pacote_id']} "
            f"(R${sugestao['valor_referencia']}) confianca={sugestao['confianca']}"
        )
    return opp


# ─── Checklist de entrega por oferta/pacote ──────────────────────────────────

def obter_checklist_por_oferta_e_pacote(oferta_id: str, pacote_id: str) -> list:
    """
    Retorna lista de strings (descrição dos itens) do checklist de entrega
    para a combinação oferta/pacote. Retorna [] se não encontrado.
    """
    catalogo = carregar_catalogo()
    idx      = _indice_por_id(catalogo)
    oferta   = idx.get(oferta_id)
    if not oferta:
        return []
    pacotes = _indice_pacotes(oferta)
    pacote  = pacotes.get(pacote_id)
    if not pacote:
        return []
    return pacote.get("checklist_entrega", [])


# ─── Grau de customização ─────────────────────────────────────────────────────

def avaliar_grau_customizacao(opp: dict) -> str:
    """
    Retorna "alta", "media" ou "baixa" com base em sinais da oportunidade.
    Alta customização → pode exigir deliberação antes de promover a ganho.
    """
    sinais = opp.get("sinais_detectados", [])
    insumos_tipos = {i.get("tipo_insumo", "") for i in opp.get("insumos", [])}

    marcadores_alta = {
        "escopo_nao_padrao", "customizacao_solicitada", "fora_catalogo",
        "multiplas_areas", "integracao_externa", "pediu_proposta_customizada",
    }
    if marcadores_alta & (set(sinais) | insumos_tipos):
        return "alta"

    # valor muito acima da referência também indica alta customização
    valor_est = opp.get("valor_estimado") or opp.get("valor_referencia")
    valor_ref = opp.get("valor_referencia")
    if valor_est and valor_ref and float(valor_est) > float(valor_ref) * 1.5:
        return "alta"

    if len(sinais) >= 5 or opp.get("prioridade") == "alta":
        return "media"

    return "baixa"


# ─── Gatilho de deliberação ───────────────────────────────────────────────────

def verificar_gatilho_deliberacao_oferta(opp: dict) -> tuple[bool, str]:
    """
    Retorna (True, motivo) se a oportunidade deve gerar deliberação de conselho.
    Condições:
    - grau_customizacao == "alta"
    - valor acima do teto de aprovação automática
    - oferta não mapeada no catálogo
    """
    regras = carregar_regras()
    teto   = regras.get("valor_maximo_sem_deliberacao", 5000.0)
    grau   = avaliar_grau_customizacao(opp)

    if grau == "alta" and regras.get("grau_customizacao_alto_exige_deliberacao", True):
        return True, f"grau_customizacao=alta para opp {opp.get('id','?')}"

    valor = opp.get("valor_estimado") or opp.get("valor_referencia")
    if valor:
        try:
            if float(valor) > teto:
                return True, f"valor_estimado=R${valor} acima do teto=R${teto}"
        except (TypeError, ValueError):
            pass

    if not opp.get("oferta_id"):
        return True, "opp sem oferta_id mapeada — escopo indefinido"

    return False, ""


# ─── Critérios de pronto para entrega ────────────────────────────────────────

def verificar_criterios_pronto_entrega(opp: dict) -> tuple[bool, list]:
    """
    Verifica se a oportunidade atende aos critérios mínimos para ir a ganho/entrega.
    Retorna (True, []) se apto; (False, lista_de_pendencias) se não.
    """
    regras  = carregar_regras()
    oferta_id = opp.get("oferta_id")
    pendencias = []

    if not oferta_id:
        pendencias.append("oferta_id ausente — sugerir oferta antes de promover")

    regras_oferta = regras.get("regras_por_oferta", {}).get(oferta_id, {})
    if regras_oferta.get("exige_escopo_antes_de_ganho"):
        insumos_tipos = {i.get("tipo_insumo", "") for i in opp.get("insumos", [])}
        if "escopo_confirmado" not in insumos_tipos:
            pendencias.append(f"escopo_confirmado obrigatório para oferta {oferta_id}")

    return (len(pendencias) == 0, pendencias)


# ─── Template de proposta ─────────────────────────────────────────────────────

def montar_texto_proposta(opp: dict, nome_contato: str = "", gap_principal: str = "") -> dict:
    """
    Monta dict com assunto, intro, corpo, fechamento de proposta.
    Usa template por linha_servico ou "padrao".
    """
    templates = carregar_templates()
    linha     = opp.get("linha_servico_sugerida", "")
    tmpl      = templates.get("templates", {}).get(linha) or templates.get("templates", {}).get("padrao", {})

    nome_oferta  = opp.get("nome_oferta", "Serviço Vetor")
    nome_pacote  = opp.get("nome_pacote", "")
    valor_ref    = opp.get("valor_referencia", "")
    prazo_dias   = opp.get("prazo_dias_oferta", "")
    contraparte  = opp.get("contraparte", "")

    # Buscar entregaveis do pacote
    entregaveis_lista = obter_checklist_por_oferta_e_pacote(
        opp.get("oferta_id", ""), opp.get("pacote_id", "")
    )
    entregaveis_str = "; ".join(entregaveis_lista[:4]) if entregaveis_lista else nome_pacote

    ctx = {
        "nome_empresa":     contraparte,
        "nome_contato":     nome_contato or contraparte,
        "nome_oferta":      nome_oferta,
        "nome_pacote":      nome_pacote,
        "valor_referencia": f"{float(valor_ref):,.0f}".replace(",", ".") if valor_ref else "a definir",
        "prazo_dias":       str(prazo_dias) if prazo_dias else "a definir",
        "gap_principal":    gap_principal or "os principais gargalos identificados",
        "entregaveis":      entregaveis_str,
    }

    def fmt(s):
        try:
            return s.format(**ctx)
        except (KeyError, ValueError):
            return s

    return {
        "assunto":    fmt(tmpl.get("assunto", "")),
        "intro":      fmt(tmpl.get("intro", "")),
        "corpo":      fmt(tmpl.get("corpo", "")),
        "fechamento": fmt(tmpl.get("fechamento", "")),
    }


# ─── Histórico ────────────────────────────────────────────────────────────────

def registrar_evento_oferta(evento: str, descricao: str,
                             origem: str = "", opp_id: str = "") -> None:
    try:
        historico = []
        if _ARQ_HISTORICO.exists():
            with open(_ARQ_HISTORICO, encoding="utf-8") as f:
                historico = json.load(f)
        historico.append({
            "id":            str(uuid.uuid4())[:8],
            "evento":        evento,
            "descricao":     descricao,
            "opp_id":        opp_id,
            "origem":        origem,
            "registrado_em": datetime.now().isoformat(timespec="seconds"),
        })
        # Manter últimos 500 eventos
        if len(historico) > 500:
            historico = historico[-500:]
        _salvar(_ARQ_HISTORICO, historico)
    except Exception as exc:
        log.warning(f"[ofertas] falha ao registrar histórico: {exc}")


# ─── Resumo para painel ───────────────────────────────────────────────────────

def resumir_para_painel() -> dict:
    """Retorna dict compacto para card na homepage e página /ofertas."""
    catalogo = carregar_catalogo()
    ofertas  = catalogo.get("ofertas", [])
    total_pacotes = sum(len(o.get("pacotes", [])) for o in ofertas)

    # Eventos recentes
    historico = []
    if _ARQ_HISTORICO.exists():
        try:
            with open(_ARQ_HISTORICO, encoding="utf-8") as f:
                historico = json.load(f)
        except Exception:
            pass

    return {
        "total_ofertas":  len(ofertas),
        "total_pacotes":  total_pacotes,
        "linhas_cobertas": list({o.get("linha_servico", "") for o in ofertas}),
        "historico_recente": historico[-10:] if historico else [],
    }
