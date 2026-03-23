"""
modulos/comercial/pipeline_manager.py — Gerenciamento do pipeline comercial.

Funções puras de leitura, transformação e persistência do pipeline.
Sem lógica de agente aqui — o agente chama essas funções e decide o que fazer.

Arquivos gerenciados:
  dados/pipeline_comercial.json
  dados/fila_followups.json
  dados/historico_abordagens.json
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_ARQ_PIPELINE  = "pipeline_comercial.json"
_ARQ_FOLLOWUPS = "fila_followups.json"
_ARQ_HISTORICO = "historico_abordagens.json"

# Estágios que indicam oportunidade encerrada
_ESTAGIOS_ENCERRADOS = {"ganho", "perdido"}


# ─── Carga ──────────────────────────────────────────────────────────────────

def carregar_pipeline() -> list:
    return _carregar(_ARQ_PIPELINE, padrao=[])


def carregar_followups() -> list:
    return _carregar(_ARQ_FOLLOWUPS, padrao=[])


def carregar_historico() -> list:
    return _carregar(_ARQ_HISTORICO, padrao=[])


# ─── Origem do handoff ──────────────────────────────────────────────────────

def detectar_origem_handoff(osm_id: str, handoffs: list) -> dict:
    """
    Encontra o handoff mais recente destinado ao agente_comercial para este osm_id.
    Retorna dict com {origem, tipo_handoff, handoff_id} ou defaults de prospeccao.
    """
    candidatos = []
    for h in handoffs:
        if h.get("agente_destino") != "agente_comercial":
            continue
        ref = h.get("referencia_id", "") or ""
        hid = h.get("id", "") or ""
        if osm_id in ref or osm_id in hid:
            candidatos.append(h)

    if not candidatos:
        return {"origem": "prospeccao", "tipo_handoff": "prospeccao_fria", "handoff_id": None}

    # Preferir marketing sobre prospeccao se ambos existirem
    for h in candidatos:
        if h.get("agente_origem") == "agente_marketing":
            return {
                "origem":      "marketing",
                "tipo_handoff": h.get("tipo_handoff", "oportunidade_marketing"),
                "handoff_id":  h.get("id"),
            }

    h = candidatos[-1]
    return {
        "origem":      "prospeccao",
        "tipo_handoff": h.get("tipo_handoff", "prospeccao_fria"),
        "handoff_id":  h.get("id"),
    }


def montar_contexto_comercial_por_origem(lead: dict, origem_info: dict) -> dict:
    """
    Retorna campos de contexto que enriquecem a oportunidade no pipeline
    conforme a origem (prospeccao | marketing).
    """
    origem = origem_info.get("origem", "prospeccao")

    if origem == "marketing":
        return {
            "origem_oportunidade":   "marketing",
            "tipo_handoff":          origem_info.get("tipo_handoff", "oportunidade_marketing"),
            "contexto_origem":       (
                lead.get("resumo_oportunidade_marketing")
                or lead.get("oportunidade_marketing_principal")
                or lead.get("principal_gargalo_presenca", "")
            ),
            "linha_servico_sugerida": "marketing_presenca_digital",
            "abordagem_inicial_tipo": "consultiva_diagnostica",
        }
    else:
        return {
            "origem_oportunidade":   "prospeccao",
            "tipo_handoff":          origem_info.get("tipo_handoff", "prospeccao_fria"),
            "contexto_origem":       lead.get("motivo_prioridade", ""),
            "linha_servico_sugerida": "comercial_base",
            "abordagem_inicial_tipo": "exploratoria",
        }


def definir_abordagem_inicial_por_origem(origem: str, lead: dict) -> dict:
    """
    Retorna {tipo_acao, descricao_base} para o follow-up inicial
    conforme a origem do handoff.
    """
    if origem == "marketing":
        oportunidade = (
            lead.get("oportunidade_marketing_principal")
            or lead.get("oportunidade_presenca_principal")
            or "gargalo digital identificado"
        )
        empresa = lead.get("nome", "empresa")
        return {
            "tipo_acao":     "primeiro_contato",
            "descricao_base": (
                f"Retomar oportunidade detectada no digital — {oportunidade} | "
                f"Apresentar diagnóstico resumido para {empresa} | "
                f"Validar interesse em resolver gargalo específico | "
                f"Avançar para proposta quando fizer sentido"
            ),
        }
    else:
        empresa = lead.get("nome", "empresa")
        return {
            "tipo_acao":     "primeiro_contato",
            "descricao_base": (
                f"Mapear interesse e validar dor — abrir conversa inicial com {empresa} | "
                f"Confirmar contexto básico e qualificar interesse | "
                f"{lead.get('proxima_acao_comercial', 'Identificar dor principal e encaixe do serviço')}"
            ),
        }


def enriquecer_oportunidade_com_marketing(opp: dict, lead: dict) -> bool:
    """
    Atualiza oportunidade existente no pipeline com contexto de marketing.
    Eleva prioridade se warranted. Retorna True se houve mudança.
    """
    agora = datetime.now().isoformat(timespec="seconds")
    mudou = False

    # Só enriquece se ainda não tem origem marketing
    if opp.get("origem_oportunidade") == "marketing":
        return False

    opp["origem_oportunidade"]    = "prospeccao_e_marketing"
    opp["linha_servico_sugerida"] = "marketing_presenca_digital"
    opp["abordagem_inicial_tipo"] = "consultiva_diagnostica"
    opp["contexto_origem"]        = (
        lead.get("resumo_oportunidade_marketing")
        or lead.get("oportunidade_marketing_principal", "")
    )

    # Elevar prioridade de media→alta quando há proposta pronta
    if (
        lead.get("prioridade_execucao_marketing") == "alta"
        and opp.get("prioridade") != "alta"
    ):
        opp["prioridade"] = "alta"

    # Atualizar proxima_acao com contexto de marketing se mais específica
    oferta = lead.get("oferta_principal_comercial", "")
    if oferta and oferta not in opp.get("proxima_acao", ""):
        opp["proxima_acao"] = (
            f"[Marketing] {oferta} | {opp.get('proxima_acao', '')}"
        )

    opp["atualizado_em"] = agora
    return True


def detectar_handoffs_marketing_para_enriquecimento(pipeline: list, handoffs: list) -> list:
    """
    Encontra pares (opp_idx, osm_id, handoff) onde:
    - A oportunidade já existe no pipeline
    - Existe handoff de marketing para a mesma empresa (pelo osm_id)
    - O pipeline ainda não tem contexto de marketing

    Retorna lista de (opp_idx, osm_id, handoff_dict).
    """
    opp_por_osm = {opp.get("origem_id", ""): idx for idx, opp in enumerate(pipeline) if opp.get("origem_id")}

    pares = []
    for h in handoffs:
        if h.get("agente_origem") != "agente_marketing":
            continue
        if h.get("agente_destino") != "agente_comercial":
            continue
        if h.get("status") in ("concluido", "cancelado"):
            continue
        ref    = h.get("referencia_id", "")
        osm_id = ref.replace("mkt_", "")
        if osm_id in opp_por_osm:
            idx = opp_por_osm[osm_id]
            if pipeline[idx].get("origem_oportunidade") not in ("marketing", "prospeccao_e_marketing"):
                pares.append((idx, osm_id, h))

    return pares


def detectar_pipeline_sem_contexto_marketing(pipeline: list) -> list:
    """
    Encontra oportunidades no pipeline sem campos de origem preenchidos
    (foram importadas antes da especialização por origem).
    Retorna lista de (opp_idx, osm_id).
    """
    return [
        (idx, opp.get("origem_id", ""))
        for idx, opp in enumerate(pipeline)
        if not opp.get("origem_oportunidade") and opp.get("origem_id")
    ]


# ─── Importação de novas oportunidades ──────────────────────────────────────

def importar_oportunidades_novas(leads: list, pipeline: list, handoffs: list | None = None) -> list:
    """
    Para cada lead em fila_execucao_comercial.json que ainda não está no pipeline,
    cria um dict de oportunidade com estagio='qualificado'.

    Detecta a origem do handoff (prospeccao | marketing) para personalizar
    a oportunidade desde a importação.

    Critérios de importação:
      - lead.abordavel_agora = True
      - ID (oport_{osm_id}) não existe no pipeline atual

    Retorna lista de novas oportunidades criadas (não persiste aqui).
    """
    handoffs = handoffs or []
    ids_existentes    = {o["id"] for o in pipeline}
    origens_existentes = {o.get("origem_id") for o in pipeline}
    novas = []

    for lead in leads:
        if not lead.get("abordavel_agora", False):
            continue
        osm_id = str(lead.get("osm_id", ""))
        opp_id = f"oport_{osm_id}"
        if opp_id in ids_existentes or osm_id in origens_existentes:
            continue
        origem_info = detectar_origem_handoff(osm_id, handoffs)
        novas.append(_lead_para_oportunidade(lead, origem_info))

    return novas


def criar_followup_inicial(opp: dict, lead: dict, followups_existentes: list) -> dict:
    """
    Cria o follow-up de primeiro_contato para uma oportunidade recém-importada.
    A descricao e tipo_acao variam conforme a origem (prospeccao | marketing).

    agente_destino = "agente_executor_contato"
    status = "pendente_execucao"
    """
    seq   = _proxima_seq(opp["id"], followups_existentes)
    fu_id = f"fu_{opp['id']}_{seq}"
    agora = datetime.now().isoformat(timespec="seconds")

    origem  = opp.get("origem_oportunidade", "prospeccao")
    ab      = definir_abordagem_inicial_por_origem(origem, lead)

    return {
        "id":                fu_id,
        "oportunidade_id":   opp["id"],
        "contraparte":       opp["contraparte"],
        "canal":             opp.get("canal_sugerido", ""),
        "tipo_acao":         ab["tipo_acao"],
        "descricao":         ab["descricao_base"],
        "origem_followup":   origem,
        "prazo_sugerido":    None,
        "status":            "pendente_execucao",
        "agente_origem":     "agente_comercial",
        "agente_destino":    "agente_executor_contato",
        "depende_de":        None,
        "registrado_em":     agora,
        "atualizado_em":     agora,
    }


# ─── Métricas e estado do pipeline ──────────────────────────────────────────

def atualizar_metricas_pipeline(pipeline: list) -> list:
    """
    Recalcula dias_sem_atividade para cada oportunidade ativa.
    Não altera estágio. Não toma decisões.
    """
    hoje = date.today()
    for opp in pipeline:
        if opp.get("estagio") in _ESTAGIOS_ENCERRADOS:
            continue
        ultima = opp.get("ultima_atividade")
        if ultima:
            try:
                delta = (hoje - date.fromisoformat(ultima)).days
                opp["dias_sem_atividade"] = delta
            except ValueError:
                opp["dias_sem_atividade"] = 0
        opp["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    return pipeline


# ─── Detecção de casos ──────────────────────────────────────────────────────

def detectar_casos_para_revisao(pipeline: list) -> list:
    """
    Retorna oportunidades que precisam de atenção interna mas não exigem conselho:
      - Ativas há mais de COMERCIAL_DIAS_SEM_ATIVIDADE_REVISAO dias sem atividade
      - Com tentativas_contato >= COMERCIAL_TENTATIVAS_MAXIMAS (sugerir encerramento)

    Retorna lista de dicts com opp + motivo.
    """
    casos = []
    for opp in pipeline:
        if opp.get("estagio") in _ESTAGIOS_ENCERRADOS:
            continue
        dias = opp.get("dias_sem_atividade", 0)
        tent = opp.get("tentativas_contato", 0)

        if tent >= config.COMERCIAL_TENTATIVAS_MAXIMAS:
            casos.append({
                "oportunidade_id": opp["id"],
                "contraparte":     opp["contraparte"],
                "motivo":          f"tentativas_esgotadas ({tent} tentativas sem resposta registrada)",
                "tipo":            "sugerir_perdido",
            })
        elif dias >= config.COMERCIAL_DIAS_SEM_ATIVIDADE_REVISAO:
            casos.append({
                "oportunidade_id": opp["id"],
                "contraparte":     opp["contraparte"],
                "motivo":          f"sem_atividade_ha_{dias}_dias",
                "tipo":            "marcar_revisao",
            })
    return casos


def detectar_casos_para_escalamento(pipeline: list) -> list:
    """
    Retorna oportunidades que devem subir para deliberação do conselho:
      - Travadas em aguardando_decisao além do limite
      - Valor estimado acima do threshold
      - Campo explícito de escopo customizado ou sensibilidade

    Retorna lista de dicts prontos para fila_decisoes_consolidada.
    """
    casos = []
    for opp in pipeline:
        if opp.get("estagio") in _ESTAGIOS_ENCERRADOS:
            continue

        motivos = []

        # Travada em aguardando_decisao
        if (
            opp.get("estagio") == "aguardando_decisao"
            and opp.get("dias_sem_atividade", 0) > config.COMERCIAL_DIAS_LIMITE_DECISAO
        ):
            motivos.append(
                f"aguardando_decisao ha {opp['dias_sem_atividade']} dias "
                f"(limite: {config.COMERCIAL_DIAS_LIMITE_DECISAO})"
            )

        # Valor acima do threshold (quando informado)
        valor = opp.get("valor_estimado")
        if valor and float(valor) > config.COMERCIAL_THRESHOLD_PROPOSTA:
            motivos.append(
                f"valor estimado R$ {valor:,.2f} acima do threshold "
                f"R$ {config.COMERCIAL_THRESHOLD_PROPOSTA:,.2f}"
            )

        if motivos:
            casos.append({
                "item_id":        f"esc_{opp['id']}",
                "agente_origem":  "agente_comercial",
                "tipo":           "deliberacao_comercial",
                "descricao":      f"{opp['contraparte']} — {' | '.join(motivos)}",
                "urgencia":       "alta" if opp.get("estagio") == "aguardando_decisao" else "media",
                "acao_sugerida":  "revisar oportunidade e definir proximo passo ou encerrar",
                "prazo_sugerido": None,
                "status_aprovacao": "pendente",
            })
    return casos


# ─── Histórico ──────────────────────────────────────────────────────────────

def criar_evento_historico(opp_id: str, contraparte: str, tipo_evento: str, descricao: str) -> dict:
    """Cria um evento de histórico. Não persiste — quem chama decide quando salvar."""
    ts = datetime.now().isoformat(timespec="seconds")
    ts_curto = datetime.now().strftime("%Y%m%d%H%M%S")
    return {
        "id":                f"ev_{opp_id}_{ts_curto}",
        "oportunidade_id":   opp_id,
        "contraparte":       contraparte,
        "tipo_evento":       tipo_evento,
        "descricao":         descricao,
        "origem":            "agente_comercial",
        "agente_responsavel": "agente_comercial",
        "registrado_em":     ts,
    }


# ─── Persistência ───────────────────────────────────────────────────────────

def salvar_pipeline(pipeline: list) -> None:
    _salvar(_ARQ_PIPELINE, pipeline)


def salvar_followups(followups: list) -> None:
    _salvar(_ARQ_FOLLOWUPS, followups)


def salvar_historico(historico: list) -> None:
    _salvar(_ARQ_HISTORICO, historico)


def persistir_arquivos_base() -> None:
    """Cria arquivos base se não existirem (primeira execução do agente)."""
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    for nome, padrao in [
        (_ARQ_PIPELINE,  []),
        (_ARQ_FOLLOWUPS, []),
        (_ARQ_HISTORICO, []),
    ]:
        caminho = config.PASTA_DADOS / nome
        if not caminho.exists():
            _salvar(nome, padrao)
            logger.info(f"Arquivo base criado: {caminho}")


# ─── Internos ────────────────────────────────────────────────────────────────

def _lead_para_oportunidade(lead: dict, origem_info: dict | None = None) -> dict:
    osm_id  = str(lead.get("osm_id", ""))
    agora   = datetime.now().isoformat(timespec="seconds")
    ctx     = montar_contexto_comercial_por_origem(lead, origem_info or {})
    return {
        "id":                  f"oport_{osm_id}",
        "contraparte":         lead.get("nome", ""),
        "categoria":           lead.get("categoria_id", ""),
        "cidade":              f"{lead.get('cidade', '')}/{lead.get('estado', '')}",
        "estagio":             "qualificado",
        "canal_sugerido":      lead.get("canal_abordagem_sugerido", ""),
        "contato_principal":   lead.get("contato_principal", ""),
        "valor_estimado":      None,
        "prioridade":          lead.get("nivel_prioridade_comercial", "media"),
        "proxima_acao":        lead.get("proxima_acao_comercial", ""),
        "proxima_acao_em":     None,
        "ultima_atividade":    date.today().isoformat(),
        "dias_sem_atividade":  0,
        "tentativas_contato":  0,
        "motivo_perda":        None,
        "origem":              "fila_execucao_comercial",
        "origem_id":           osm_id,
        "origem_oportunidade": ctx["origem_oportunidade"],
        "tipo_handoff":        ctx["tipo_handoff"],
        "contexto_origem":     ctx["contexto_origem"],
        "linha_servico_sugerida": ctx["linha_servico_sugerida"],
        "abordagem_inicial_tipo": ctx["abordagem_inicial_tipo"],
        "observacoes":         lead.get("observacoes_comerciais", ""),
        "status_operacional":  "aguardando_execucao",
        "depende_de":          None,   # preenchido após criar follow-up
        "bloqueios":           [],
        "registrado_em":       agora,
        "atualizado_em":       agora,
    }


def _proxima_seq(opp_id: str, followups: list) -> int:
    """Retorna o próximo número de sequência para follow-ups de uma oportunidade."""
    existentes = [f for f in followups if f.get("oportunidade_id") == opp_id]
    return len(existentes) + 1


def _carregar(nome: str, padrao):
    caminho = config.PASTA_DADOS / nome
    if not caminho.exists():
        return padrao
    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)
    logger.info(f"Carregado: {caminho} ({len(dados)} registros)")
    return dados


def _salvar(nome: str, dados) -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = config.PASTA_DADOS / nome
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    logger.info(f"Salvo: {caminho} ({len(dados)} registros)")
