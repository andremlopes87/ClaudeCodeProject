"""
agentes/secretario/agente_secretario.py — Agente secretário/orquestrador.

Lê o estado dos agentes existentes, consolida a visão operacional do dia,
registra handoffs entre agentes e gerencia o ciclo de deliberações do conselho.

Não recria análise financeira. Não recria pipeline comercial.
Não substitui os agentes operacionais. Não executa contato real.
Consolida, organiza, prioriza, escreve deliberacoes_conselho.json
e reflete decisões do conselho no painel_operacional.json.

Agentes conhecidos nesta versão:
  agente_financeiro, agente_comercial
Placeholder futuro:
  agente_executor_contato (destino de follow-ups, ainda não implementado)

Saídas:
  dados/painel_operacional.json
  dados/handoffs_agentes.json
  dados/deliberacoes_conselho.json      (escrito e mantido por este agente)
  dados/historico_deliberacoes.json     (log auditável de eventos)
  dados/estado_agente_secretario.json
  logs/agentes/agente_secretario_{ts}.log
"""

import hashlib
import json
import logging
from datetime import date, datetime
from pathlib import Path

import config
from core.llm_router import LLMRouter
from core.controle_agente import (
    carregar_estado,
    salvar_estado,
    ja_processado,
    marcar_processado,
    registrar_execucao,
    configurar_log_agente,
)
from core.deliberacoes import (
    criar_ou_atualizar_deliberacao,
    consolidar_deliberacoes_equivalentes,
    carregar_deliberacoes,
)

NOME_AGENTE = "agente_secretario"

_AGENTES_CONHECIDOS    = ["agente_financeiro", "agente_comercial"]
_TIPOS_DELIBERACAO     = {"deliberacao_comercial", "risco_de_caixa", "vencido_sem_resolucao", "vencido_sem_pagamento"}
_URGENCIAS_DELIBERACAO = {"alta", "imediata"}
_AGENTES_FUTUROS       = {"agente_executor_contato"}


# ─── Ponto de entrada ────────────────────────────────────────────────────────

def executar() -> dict:
    log, caminho_log = configurar_log_agente(NOME_AGENTE)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")

    log.info("=" * 60)
    log.info(f"AGENTE SECRETARIO — inicio {ts}")
    log.info("=" * 60)

    estado = carregar_estado(NOME_AGENTE)
    log.info(f"Estado: ultima_execucao={estado['ultima_execucao']} | processados={len(estado['itens_processados'])}")

    router = LLMRouter()

    # ── ETAPA 1: Carregar todos os insumos ────────────────────────────────
    insumos = _carregar_insumos_operacionais(log)

    # ── ETAPA 2: Carregar handoffs existentes ─────────────────────────────
    handoffs_existentes = _carregar_json("handoffs_agentes.json", padrao=[])

    # ── ETAPA 3: Criar novos handoffs (follow-ups → agentes futuros) ──────
    novos_handoffs, n_handoffs_criados = _extrair_handoffs(insumos, handoffs_existentes, estado, log)
    todos_handoffs = handoffs_existentes + novos_handoffs

    # ── ETAPA 4: Detectar bloqueios ────────────────────────────────────────
    bloqueios = _detectar_bloqueios(insumos, todos_handoffs, log)

    # ── ETAPA 5: Sincronizar deliberações do conselho ─────────────────────
    deliberacoes_dados = _sincronizar_deliberacoes_conselho(insumos, log)

    # ── ETAPA 5b: Detectar estagnação por origem e deliberar ──────────────
    pipeline       = insumos["pipeline"]
    estagnadas_mkt = detectar_estagnacao_marketing(pipeline)
    estagnadas_prs = detectar_estagnacao_prospeccao(pipeline)
    mistas_prio    = detectar_oportunidades_mistas_prioritarias(pipeline)

    todas_delib = carregar_deliberacoes()
    n_delib_mkt = 0
    for est in estagnadas_mkt:
        opp_full = next((o for o in pipeline if o.get("id") == est["id"]), est)
        if criar_deliberacao_estagnacao_marketing_se_necessario(opp_full, todas_delib):
            n_delib_mkt += 1
            log.info(f"  [estag mkt] deliberacao: {est.get('contraparte', '?')[:40]}")

    if n_delib_mkt:
        recarregadas = carregar_deliberacoes()
        deliberacoes_dados = {
            "pendentes":                        [d for d in recarregadas if d["status"] == "pendente"],
            "em_analise":                       [d for d in recarregadas if d["status"] == "em_analise"],
            "deliberadas_aguardando_aplicacao": [d for d in recarregadas if d["status"] == "deliberado"],
            "aplicadas":                        [d for d in recarregadas if d["status"] == "aplicado"],
            "total":                            len(recarregadas),
        }
        log.info(f"  [estag mkt] {n_delib_mkt} deliberacoes de estagnacao criadas")

    if estagnadas_prs:
        log.info(f"  [estag prs] {len(estagnadas_prs)} oportunidades estagnadas (prospeccao)")
    if mistas_prio:
        log.info(f"  [mistas]    {len(mistas_prio)} oportunidades mistas prioritarias")

    # ── ETAPA 5c: Contextualizar deliberações via LLM (ponto 3) ──────────
    _n_delib_enriq = 0
    for _delib in deliberacoes_dados.get("pendentes", []):
        if _delib.get("contexto_llm"):
            continue  # já enriquecida
        _ctx_delib = {
            "tipo":           _delib.get("tipo", ""),
            "urgencia":       _delib.get("urgencia", ""),
            "descricao":      str(_delib.get("descricao", ""))[:300],
            "contraparte":    _delib.get("contraparte", ""),
            "pipeline_total": len(insumos["pipeline"]),
            "saldo_caixa":    insumos["estado_financeiro"].get("ultimo_saldo"),
            "instrucao":      "Analisar deliberação, adicionar contexto expandido, riscos e recomendação preliminar.",
        }
        _res_delib = router.analisar(_ctx_delib)
        _usou_llm_delib = _res_delib["sucesso"] and not _res_delib["fallback_usado"]
        if _usou_llm_delib:
            _delib["contexto_llm"] = _res_delib["resultado"]
            _n_delib_enriq += 1
        log.info(f"  [llm] delib={'LLM' if _usou_llm_delib else 'regra'} | {_delib.get('tipo','?')[:40]}")
    if _n_delib_enriq:
        log.info(f"  [llm] {_n_delib_enriq} deliberacao(oes) enriquecida(s) com contexto LLM")

    # ── ETAPA 6: Itens operacionais prioritários ───────────────────────────
    ids_delib = {
        d.get("id", "")
        for bucket in ["pendentes", "em_analise", "deliberadas_aguardando_aplicacao", "aplicadas"]
        for d in deliberacoes_dados.get(bucket, [])
    }
    operacionais = _itens_operacionais(insumos, ids_delib)

    # ── ETAPA 6b: Classificar gargalos operacionais via LLM (ponto 1) ────
    _gargalos_llm = None
    _snapshot_op = {
        "pipeline_total":         len(insumos["pipeline"]),
        "followups_pendentes":    sum(1 for f in insumos["followups"] if f.get("status") == "pendente_execucao"),
        "operacionais":           len(operacionais),
        "bloqueios":              len(bloqueios),
        "handoffs_pendentes":     sum(1 for h in todos_handoffs if h.get("status") == "pendente"),
        "deliberacoes_pendentes": len(deliberacoes_dados.get("pendentes", [])),
        "estagnadas_marketing":   len(estagnadas_mkt),
        "instrucao":              "Classificar e priorizar gargalos operacionais por severidade com sugestão de ação.",
    }
    _res_classif_op = router.classificar(_snapshot_op)
    _usou_llm_garg = _res_classif_op["sucesso"] and not _res_classif_op["fallback_usado"]
    if _usou_llm_garg:
        _gargalos_llm = _res_classif_op["resultado"]
        log.info(f"  [llm] gargalos LLM: {str(_gargalos_llm)[:80]}")
    log.info(f"  [llm] triagem={'LLM' if _usou_llm_garg else 'regra'}")

    # ── ETAPA 7: Status por agente ─────────────────────────────────────────
    status_por_agente = _status_por_agente(insumos)

    # ── ETAPA 8: Montar painel operacional ────────────────────────────────
    painel = _consolidar_painel(
        operacionais, bloqueios, todos_handoffs, deliberacoes_dados, status_por_agente,
        estagnadas_mkt=estagnadas_mkt,
        estagnadas_prs=estagnadas_prs,
        mistas_prio=mistas_prio,
    )

    # ── ETAPA 8b: Resumo narrativo do ciclo via LLM (ponto 2) ────────────
    _sf = status_por_agente.get("agente_financeiro", {})
    _sc = status_por_agente.get("agente_comercial", {})
    _ctx_resumir = {
        "pipeline_total":         _sc.get("pipeline_total", 0),
        "followups_pendentes":    _sc.get("followups_pendentes", 0),
        "saldo_caixa":            _sf.get("ultimo_saldo"),
        "operacionais":           len(operacionais),
        "bloqueios":              len(bloqueios),
        "deliberacoes_pendentes": len(deliberacoes_dados.get("pendentes", [])),
        "estagnadas_marketing":   len(estagnadas_mkt),
        "estagnadas_prospeccao":  len(estagnadas_prs),
        "handoffs_pendentes":     sum(1 for h in todos_handoffs if h.get("status") == "pendente"),
        "instrucao":              "Gerar resumo executivo do ciclo operacional em linguagem natural para o conselho.",
    }
    _res_resumir = router.resumir(_ctx_resumir)
    _usou_llm_resumo = _res_resumir["sucesso"] and not _res_resumir["fallback_usado"]
    if _usou_llm_resumo:
        _resumo_narrativo = _res_resumir["resultado"]
        painel["resumo_llm"] = _resumo_narrativo
        _salvar_resumo_diario_llm(_resumo_narrativo)
        log.info(f"  [llm] resumo narrativo: {str(_resumo_narrativo)[:80]}")
    if _gargalos_llm:
        painel["gargalos_llm"] = _gargalos_llm
    log.info(f"  [llm] resumo={'LLM' if _usou_llm_resumo else 'regra'}")

    # ── ETAPA 9: Persistir ────────────────────────────────────────────────
    _salvar_json("painel_operacional.json", painel)
    _salvar_json("handoffs_agentes.json", todos_handoffs)

    # ── ETAPA 10: Salvar estado ────────────────────────────────────────────
    n_delib_pendentes   = len(deliberacoes_dados.get("pendentes", []))
    n_delib_deliberadas = len(deliberacoes_dados.get("deliberadas_aguardando_aplicacao", []))
    n_delib_aplicadas   = len(deliberacoes_dados.get("aplicadas", []))

    resumo_str = (
        f"operacionais={len(operacionais)} bloqueios={len(bloqueios)} "
        f"delib_pendentes={n_delib_pendentes} delib_deliberadas={n_delib_deliberadas} "
        f"handoffs={len(todos_handoffs)}"
    )
    hash_exec = _hash_estado(painel)
    registrar_execucao(
        estado,
        saldo       = insumos["estado_financeiro"].get("ultimo_saldo") or 0.0,
        resumo      = resumo_str,
        n_escalados = n_delib_pendentes,
        n_autonomos = len(operacionais),
        hash_exec   = hash_exec,
    )
    salvar_estado(NOME_AGENTE, estado)

    # ── ETAPA 11: Log final ────────────────────────────────────────────────
    log.info("=" * 60)
    log.info(f"AGENTE SECRETARIO — concluido")
    log.info(f"  itens operacionais       : {len(operacionais)}")
    log.info(f"  bloqueios                : {len(bloqueios)}")
    log.info(f"  handoffs criados         : {n_handoffs_criados} (total: {len(todos_handoffs)})")
    log.info(f"  deliberacoes pendentes   : {n_delib_pendentes}")
    log.info(f"  deliberacoes deliberadas : {n_delib_deliberadas}")
    log.info(f"  deliberacoes aplicadas   : {n_delib_aplicadas}")
    log.info(f"  estagnadas marketing     : {len(estagnadas_mkt)}")
    log.info(f"  estagnadas prospeccao    : {len(estagnadas_prs)}")
    log.info(f"  mistas prioritarias      : {len(mistas_prio)}")
    log.info("=" * 60)

    return {
        "agente":                   NOME_AGENTE,
        "timestamp":                ts,
        "operacionais":             len(operacionais),
        "bloqueios":                len(bloqueios),
        "handoffs_total":           len(todos_handoffs),
        "handoffs_criados":         n_handoffs_criados,
        "deliberacoes":             n_delib_pendentes,
        "deliberacoes_deliberadas": n_delib_deliberadas,
        "deliberacoes_aplicadas":   n_delib_aplicadas,
        "estagnadas_marketing":     len(estagnadas_mkt),
        "estagnadas_prospeccao":    len(estagnadas_prs),
        "mistas_prioritarias":      len(mistas_prio),
        "caminho_log":              str(caminho_log),
    }


# ─── Carregar insumos ────────────────────────────────────────────────────────

def _carregar_insumos_operacionais(log) -> dict:
    """Carrega todos os arquivos relevantes dos agentes existentes."""
    insumos = {
        "fila_consolidada":  _carregar_json("fila_decisoes_consolidada.json", padrao=[]),
        "agenda_hoje":       _carregar_json("agenda_do_dia.json",             padrao={"itens": []}),
        "estado_financeiro": _carregar_json("estado_agente_financeiro.json",  padrao={}),
        "estado_comercial":  _carregar_json("estado_agente_comercial.json",   padrao={}),
        "pipeline":          _carregar_json("pipeline_comercial.json",        padrao=[]),
        "followups":         _carregar_json("fila_followups.json",            padrao=[]),
        "historico":         _carregar_json("historico_abordagens.json",      padrao=[]),
    }
    log.info(
        f"Insumos carregados: fila_consolidada={len(insumos['fila_consolidada'])} | "
        f"agenda={len(insumos['agenda_hoje'].get('itens', []))} | "
        f"pipeline={len(insumos['pipeline'])} | followups={len(insumos['followups'])}"
    )
    return insumos


# ─── Handoffs ────────────────────────────────────────────────────────────────

def _extrair_handoffs(insumos, existentes, estado, log) -> tuple:
    """
    Cria handoffs para follow-ups que dependem de agentes futuros.
    Não recria handoffs já registrados (dedup por referencia_id + estado).
    """
    refs_existentes = {h.get("referencia_id") for h in existentes}
    novos  = []
    agora  = datetime.now().isoformat(timespec="seconds")

    for fu in insumos["followups"]:
        fu_id   = fu.get("id", "")
        destino = fu.get("agente_destino", "")
        if not destino or fu_id in refs_existentes:
            continue

        hf_id = f"hf_{fu_id}"
        if ja_processado(estado, hf_id):
            log.info(f"  [hf skip] {hf_id} — ja registrado")
            continue

        prioridade = "alta" if fu.get("tipo_acao") == "primeiro_contato" else "media"
        novos.append({
            "id":             hf_id,
            "agente_origem":  fu.get("agente_origem", "agente_comercial"),
            "agente_destino": destino,
            "tipo_handoff":   fu.get("tipo_acao", "operacional"),
            "referencia_id":  fu_id,
            "descricao":      f"{fu.get('contraparte', '?')} \u2014 {fu.get('descricao', '')[:80]}",
            "prioridade":     prioridade,
            "status":         "pendente",
            "depende_de":     fu.get("depende_de"),
            "registrado_em":  agora,
            "atualizado_em":  agora,
        })
        marcar_processado(estado, hf_id)
        log.info(f"  [hf novo] {hf_id} | {fu.get('agente_origem')} -> {destino} | {fu.get('contraparte', '?')[:40]}")

    return novos, len(novos)


# ─── Bloqueios ───────────────────────────────────────────────────────────────

def _detectar_bloqueios(insumos, handoffs, log) -> list:
    """
    Detecta itens parados sem executor disponível.
    Follow-ups com destino em _AGENTES_FUTUROS = bloqueio estrutural.
    """
    bloqueios = []
    vistos    = set()

    for hf in handoffs:
        if hf.get("agente_destino") in _AGENTES_FUTUROS and hf.get("status") == "pendente":
            fu_id = hf.get("referencia_id", hf["id"])
            if fu_id in vistos:
                continue
            vistos.add(fu_id)
            fu = next((f for f in insumos["followups"] if f.get("id") == fu_id), {})
            bloqueios.append({
                "tipo":           "agente_destino_nao_disponivel",
                "referencia_id":  fu_id,
                "handoff_id":     hf["id"],
                "agente_destino": hf["agente_destino"],
                "contraparte":    fu.get("contraparte", hf.get("descricao", "?")[:40]),
                "descricao":      f"Follow-up aguarda {hf['agente_destino']} (ainda nao implementado)",
            })

    if bloqueios:
        log.info(f"  Bloqueios detectados: {len(bloqueios)} (agente_executor_contato nao disponivel)")

    return bloqueios


# ─── Deliberações do conselho ────────────────────────────────────────────────

def _sincronizar_deliberacoes_conselho(insumos, log) -> dict:
    """
    Sincroniza deliberações do conselho:
    1. Cria/atualiza deliberacoes_conselho.json a partir da fila_consolidada
    2. Consolida deliberações equivalentes (mesmo tipo + contraparte)
    3. Retorna deliberações separadas por status para o painel

    Esta é a fonte autoritativa — não superficia apenas, escreve e mantém.
    """
    for item in insumos["fila_consolidada"]:
        urgencia = item.get("urgencia", "")
        tipo     = item.get("tipo", "")
        if urgencia in _URGENCIAS_DELIBERACAO or tipo in _TIPOS_DELIBERACAO:
            criar_ou_atualizar_deliberacao(item)
            log.info(f"  [delib sync] {item.get('item_id')} | {urgencia} | {tipo}")

    n_consol = consolidar_deliberacoes_equivalentes()
    if n_consol:
        log.info(f"  [delib consolidar] {n_consol} deliberacoes consolidadas")

    todas = carregar_deliberacoes()
    pendentes   = [d for d in todas if d["status"] == "pendente"]
    em_analise  = [d for d in todas if d["status"] == "em_analise"]
    deliberadas = [d for d in todas if d["status"] == "deliberado"]
    aplicadas   = [d for d in todas if d["status"] == "aplicado"]

    log.info(
        f"  Deliberacoes: pendentes={len(pendentes)} em_analise={len(em_analise)} "
        f"deliberadas={len(deliberadas)} aplicadas={len(aplicadas)}"
    )

    return {
        "pendentes":                        pendentes,
        "em_analise":                       em_analise,
        "deliberadas_aguardando_aplicacao": deliberadas,
        "aplicadas":                        aplicadas,
        "total":                            len(todas),
    }


# ─── Itens operacionais ──────────────────────────────────────────────────────

def _itens_operacionais(insumos, ids_deliberacao: set) -> list:
    """
    Itens operacionais prioritários = follow-ups pendentes + pipeline aguardando execução.
    ids_deliberacao: set de IDs de deliberações (reservado para exclusão futura se necessário).
    """
    operacionais = []

    for fu in insumos["followups"]:
        if fu.get("status") == "pendente_execucao":
            operacionais.append({
                "tipo":           "followup_pendente",
                "referencia_id":  fu["id"],
                "contraparte":    fu.get("contraparte", "?"),
                "canal":          fu.get("canal", "?"),
                "acao":           fu.get("tipo_acao", "?"),
                "agente_destino": fu.get("agente_destino", "?"),
                "descricao":      fu.get("descricao", "")[:100],
            })

    for opp in insumos["pipeline"]:
        if opp.get("status_operacional") == "aguardando_execucao":
            operacionais.append({
                "tipo":           "oportunidade_aguardando_execucao",
                "referencia_id":  opp["id"],
                "contraparte":    opp.get("contraparte", "?"),
                "estagio":        opp.get("estagio", "?"),
                "prioridade":     opp.get("prioridade", "?"),
                "canal_sugerido": opp.get("canal_sugerido", "?"),
                "depende_de":     opp.get("depende_de", "?"),
                "descricao":      f"Oportunidade {opp.get('estagio')} aguardando agente_executor_contato",
            })

    return operacionais


# ─── Status por agente ───────────────────────────────────────────────────────

def _status_por_agente(insumos) -> dict:
    ef = insumos["estado_financeiro"]
    ec = insumos["estado_comercial"]
    pipeline  = insumos["pipeline"]
    followups = insumos["followups"]

    por_estagio = {}
    for opp in pipeline:
        e = opp.get("estagio", "desconhecido")
        por_estagio[e] = por_estagio.get(e, 0) + 1

    por_origem = {k: len(v) for k, v in classificar_pipeline_por_origem(pipeline).items()}
    por_linha  = {k: len(v) for k, v in classificar_pipeline_por_linha_servico(pipeline).items()}

    return {
        "agente_financeiro": {
            "ultima_execucao":           ef.get("ultima_execucao"),
            "ultimo_saldo":              ef.get("ultimo_saldo"),
            "ultimo_resumo":             ef.get("ultimo_resumo", "")[:120],
            "itens_pendentes_escalados": len(ef.get("itens_pendentes_escalados", [])),
            "itens_processados":         len(ef.get("itens_processados", [])),
        },
        "agente_comercial": {
            "ultima_execucao":            ec.get("ultima_execucao"),
            "pipeline_total":             len(pipeline),
            "pipeline_por_estagio":       por_estagio,
            "pipeline_por_origem":        por_origem,
            "pipeline_por_linha_servico": por_linha,
            "followups_pendentes":        sum(1 for f in followups if f.get("status") == "pendente_execucao"),
            "itens_pendentes_escalados":  len(ec.get("itens_pendentes_escalados", [])),
            "itens_processados":          len(ec.get("itens_processados", [])),
        },
    }


# ─── Classificação e estagnação por origem ───────────────────────────────────

def classificar_pipeline_por_origem(pipeline: list) -> dict:
    """
    Classifica o pipeline em buckets por origem_oportunidade.
    Retorna dict com listas de oportunidades por origem.
    """
    buckets: dict = {
        "prospeccao":               [],
        "marketing_presenca_digital": [],
        "prospeccao_e_marketing":   [],
        "outros":                   [],
    }
    for opp in pipeline:
        origem = opp.get("origem_oportunidade", "")
        linha  = opp.get("linha_servico_sugerida", "")
        if origem == "prospeccao_e_marketing":
            buckets["prospeccao_e_marketing"].append(opp)
        elif origem == "marketing" or linha == "marketing_presenca_digital":
            buckets["marketing_presenca_digital"].append(opp)
        elif origem == "prospeccao":
            buckets["prospeccao"].append(opp)
        else:
            buckets["outros"].append(opp)
    return buckets


def classificar_pipeline_por_linha_servico(pipeline: list) -> dict:
    """
    Agrupa pipeline por linha_servico_sugerida.
    Entradas sem campo recebem chave 'nao_definida'.
    """
    resultado: dict = {}
    for opp in pipeline:
        linha = opp.get("linha_servico_sugerida") or "nao_definida"
        resultado.setdefault(linha, []).append(opp)
    return resultado


def detectar_estagnacao_prospeccao(pipeline: list) -> list:
    """
    Detecta estagnação em oportunidades de prospecção pura.
    Regras genéricas: dias_sem_atividade >= 14 OU tentativas_contato >= 3.
    """
    estagnadas = []
    for opp in pipeline:
        origem = opp.get("origem_oportunidade", "")
        if origem not in ("prospeccao", ""):  # só prospeccao pura ou legado
            continue
        if opp.get("estagio") in ("fechado", "perdido"):
            continue
        dias       = opp.get("dias_sem_atividade", 0) or 0
        tentativas = opp.get("tentativas_contato", 0) or 0
        if dias >= 14 or tentativas >= 3:
            estagnadas.append({
                "id":                opp.get("id"),
                "contraparte":       opp.get("contraparte"),
                "estagio":           opp.get("estagio"),
                "dias_sem_atividade": dias,
                "tentativas_contato": tentativas,
                "origem":            "prospeccao",
                "motivo_estagnacao": "dias_sem_atividade" if dias >= 14 else "muitas_tentativas",
            })
    return estagnadas


def detectar_estagnacao_marketing(pipeline: list) -> list:
    """
    Detecta estagnação em oportunidades com componente marketing.
    Regras mais sensíveis: marketing é mais quente — sinal de sem_resposta
    com 2+ tentativas já indica problema de abordagem.
    """
    _ESTAGIOS_CRITICOS   = {"qualificando", "aguardando_proposta", "primeiro_contato"}
    _RESPOSTAS_NEGATIVAS = {"sem_resposta", "pediu_retorno_futuro", "nao_respondeu"}

    estagnadas = []
    vistos: set = set()

    for opp in pipeline:
        origem = opp.get("origem_oportunidade", "")
        if "marketing" not in origem:
            continue
        if opp.get("estagio") in ("fechado", "perdido"):
            continue

        opp_id     = opp.get("id", "")
        dias       = opp.get("dias_sem_atividade", 0) or 0
        tentativas = opp.get("tentativas_contato", 0) or 0
        estagio    = opp.get("estagio", "")
        ultima_rsp = opp.get("ultima_resposta_tipo", "")

        motivo = None
        if tentativas >= 2 and ultima_rsp in _RESPOSTAS_NEGATIVAS and estagio in _ESTAGIOS_CRITICOS:
            motivo = "marketing_sem_avanco"
        elif dias >= 10:
            motivo = "marketing_inativo"

        if motivo and opp_id not in vistos:
            vistos.add(opp_id)
            estagnadas.append({
                "id":                 opp_id,
                "contraparte":        opp.get("contraparte"),
                "estagio":            estagio,
                "dias_sem_atividade": dias,
                "tentativas_contato": tentativas,
                "ultima_resposta_tipo": ultima_rsp,
                "linha_servico":      opp.get("linha_servico_sugerida", ""),
                "contexto_origem":    opp.get("contexto_origem", ""),
                "origem":             origem,
                "motivo_estagnacao":  motivo,
            })
    return estagnadas


def detectar_oportunidades_mistas_prioritarias(pipeline: list) -> list:
    """
    Retorna oportunidades prospeccao_e_marketing com prioridade alta/crítica
    que ainda não foram fechadas/perdidas.
    """
    return [
        opp for opp in pipeline
        if opp.get("origem_oportunidade") == "prospeccao_e_marketing"
        and opp.get("prioridade") in ("alta", "muito_alta", "critica")
        and opp.get("estagio") not in ("fechado", "perdido")
    ]


def criar_deliberacao_estagnacao_marketing_se_necessario(opp: dict, deliberacoes: list) -> bool:
    """
    Cria deliberação de estagnação de marketing para a oportunidade, se ainda não existir.
    Não cria duplicatas: verifica deliberações pendentes/em_analise do mesmo tipo para o mesmo id.
    Retorna True se criou, False se já existia.
    """
    opp_id = opp.get("id", "")
    for d in deliberacoes:
        if (
            d.get("status") in ("pendente", "em_analise")
            and opp_id in d.get("referencias", [])
            and d.get("tipo") == "estagnacao_marketing"
        ):
            return False

    item = {
        "item_id":    f"estag_mkt_{opp_id}",
        "tipo":       "estagnacao_marketing",
        "urgencia":   "alta",
        "contraparte": opp.get("contraparte", "?"),
        "descricao": (
            f"Oportunidade de marketing estagnada em '{opp.get('estagio', '?')}' "
            f"para {opp.get('contraparte', '?')}. "
            f"Tentativas: {opp.get('tentativas_contato', 0)}. "
            f"Contexto: {str(opp.get('contexto_origem', ''))[:120]}"
        ),
        "referencias": [opp_id],
        "linha_servico": opp.get("linha_servico_sugerida", ""),
    }
    criar_ou_atualizar_deliberacao(item)
    return True


# ─── Painel operacional ──────────────────────────────────────────────────────

def _consolidar_painel(
    operacionais, bloqueios, handoffs, deliberacoes_dados, status_por_agente,
    estagnadas_mkt=None, estagnadas_prs=None, mistas_prio=None,
) -> dict:
    hoje  = date.today().isoformat()
    agora = datetime.now().isoformat(timespec="seconds")

    handoffs_pendentes = [h for h in handoffs if h.get("status") == "pendente"]
    resumo = _resumo_geral(operacionais, bloqueios, deliberacoes_dados, status_por_agente)
    sc = status_por_agente.get("agente_comercial", {})

    return {
        "data_referencia":               hoje,
        "gerado_em":                     agora,
        "resumo_geral":                  resumo,
        "itens_operacionais_prioritarios": operacionais,
        "bloqueios":                     bloqueios,
        "handoffs_pendentes":            handoffs_pendentes,
        "deliberacoes_conselho": {
            "pendentes":                        deliberacoes_dados.get("pendentes", []),
            "deliberadas_aguardando_aplicacao": deliberacoes_dados.get("deliberadas_aguardando_aplicacao", []),
            "aplicadas":                        deliberacoes_dados.get("aplicadas", []),
        },
        "status_por_agente":                   status_por_agente,
        "pipeline_por_origem":                 sc.get("pipeline_por_origem", {}),
        "pipeline_por_linha_servico":          sc.get("pipeline_por_linha_servico", {}),
        "oportunidades_estagnadas_marketing":  estagnadas_mkt or [],
        "oportunidades_estagnadas_prospeccao": estagnadas_prs or [],
        "oportunidades_mistas_prioritarias":   mistas_prio or [],
    }


def _resumo_geral(operacionais, bloqueios, deliberacoes_dados, status_por_agente) -> str:
    partes = []
    sf = status_por_agente.get("agente_financeiro", {})
    sc = status_por_agente.get("agente_comercial", {})

    saldo = sf.get("ultimo_saldo")
    if saldo is not None:
        partes.append(f"Caixa: R$ {saldo:,.2f}")

    pipeline_total = sc.get("pipeline_total", 0)
    if pipeline_total:
        partes.append(f"Pipeline: {pipeline_total} oportunidade(s)")

    pendentes   = deliberacoes_dados.get("pendentes", [])
    deliberadas = deliberacoes_dados.get("deliberadas_aguardando_aplicacao", [])
    if pendentes:
        partes.append(f"{len(pendentes)} deliberacao(oes) pendente(s) no conselho")
    if deliberadas:
        partes.append(f"{len(deliberadas)} deliberacao(oes) aguardando aplicacao")

    if bloqueios:
        partes.append(f"{len(bloqueios)} bloqueio(s) aguardando agente futuro")

    fu_pend = sc.get("followups_pendentes", 0)
    if fu_pend:
        partes.append(f"{fu_pend} follow-up(s) prontos para execucao")

    return " | ".join(partes) if partes else "Sistema inicializado"


# ─── Resumo diário LLM ───────────────────────────────────────────────────────

def _salvar_resumo_diario_llm(resumo: str) -> None:
    """Append resumo narrativo do ciclo a dados/resumo_diario_llm.json (por data)."""
    caminho = config.PASTA_DADOS / "resumo_diario_llm.json"
    try:
        if caminho.exists():
            with open(caminho, "r", encoding="utf-8") as f:
                historico = json.load(f)
        else:
            historico = []
        historico.append({
            "data":      date.today().isoformat(),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "resumo":    resumo,
            "agente":    NOME_AGENTE,
        })
        config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump(historico, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logging.getLogger(__name__).warning(f"  [llm] erro ao salvar resumo_diario_llm: {exc}")


# ─── Persistência ────────────────────────────────────────────────────────────

def _carregar_json(nome, padrao):
    caminho = config.PASTA_DADOS / nome
    if not caminho.exists():
        return padrao
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def _salvar_json(nome, dados) -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = config.PASTA_DADOS / nome
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    logging.getLogger(__name__).info(
        f"Salvo: {caminho} ({len(dados) if isinstance(dados, list) else 1} registros)"
    )


def _hash_estado(painel: dict) -> str:
    delib = painel.get("deliberacoes_conselho", {})
    chave = json.dumps({
        "operacionais": len(painel.get("itens_operacionais_prioritarios", [])),
        "bloqueios":    len(painel.get("bloqueios", [])),
        "delib_pend":   len(delib.get("pendentes", [])),
        "delib_delib":  len(delib.get("deliberadas_aguardando_aplicacao", [])),
        "handoffs":     len(painel.get("handoffs_pendentes", [])),
    }, sort_keys=True)
    return hashlib.md5(chave.encode()).hexdigest()[:16]
