"""
agentes/secretario/agente_secretario.py — Agente secretário/orquestrador.

Lê o estado dos agentes existentes, consolida a visão operacional do dia,
registra handoffs entre agentes e identifica bloqueios e deliberações.

Não recria análise financeira. Não recria pipeline comercial.
Não substitui os agentes operacionais. Não executa contato real.
Apenas consolida, organiza, prioriza e sobe o que é deliberativo.

Agentes conhecidos nesta versão:
  agente_financeiro, agente_comercial
Placeholder futuro:
  agente_executor_contato (destino de follow-ups, ainda não implementado)

Saídas:
  dados/painel_operacional.json
  dados/handoffs_agentes.json
  dados/estado_agente_secretario.json
  logs/agentes/agente_secretario_{ts}.log
"""

import hashlib
import json
import logging
from datetime import date, datetime
from pathlib import Path

import config
from core.controle_agente import (
    carregar_estado,
    salvar_estado,
    ja_processado,
    marcar_processado,
    registrar_execucao,
    configurar_log_agente,
)

NOME_AGENTE = "agente_secretario"

# Agentes cujos estados o secretário lê
_AGENTES_CONHECIDOS = ["agente_financeiro", "agente_comercial"]

# Tipos e urgências que sobem para deliberação do conselho
_TIPOS_DELIBERACAO = {"deliberacao_comercial", "risco_de_caixa", "vencido_sem_resolucao", "vencido_sem_pagamento"}
_URGENCIAS_DELIBERACAO = {"alta", "imediata"}

# Destinos ainda não implementados — geram bloqueio
_AGENTES_FUTUROS = {"agente_executor_contato"}


# ─── Ponto de entrada ────────────────────────────────────────────────────────

def executar() -> dict:
    log, caminho_log = configurar_log_agente(NOME_AGENTE)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")

    log.info("=" * 60)
    log.info(f"AGENTE SECRETARIO — inicio {ts}")
    log.info("=" * 60)

    estado = carregar_estado(NOME_AGENTE)
    log.info(f"Estado: ultima_execucao={estado['ultima_execucao']} | processados={len(estado['itens_processados'])}")

    # ── ETAPA 1: Carregar todos os insumos ────────────────────────────────
    insumos = _carregar_insumos_operacionais(log)

    # ── ETAPA 2: Carregar handoffs existentes ─────────────────────────────
    handoffs_existentes = _carregar_json("handoffs_agentes.json", padrao=[])

    # ── ETAPA 3: Criar novos handoffs (follow-ups → agentes futuros) ──────
    novos_handoffs, n_handoffs_criados = _extrair_handoffs(insumos, handoffs_existentes, estado, log)
    todos_handoffs = handoffs_existentes + novos_handoffs

    # ── ETAPA 4: Detectar bloqueios ────────────────────────────────────────
    bloqueios = _detectar_bloqueios(insumos, todos_handoffs, log)

    # ── ETAPA 5: Separar deliberações do conselho ──────────────────────────
    deliberacoes = _detectar_deliberacoes_conselho(insumos, log)

    # ── ETAPA 6: Itens operacionais prioritários ───────────────────────────
    operacionais = _itens_operacionais(insumos, deliberacoes)

    # ── ETAPA 7: Status por agente ─────────────────────────────────────────
    status_por_agente = _status_por_agente(insumos)

    # ── ETAPA 8: Montar painel operacional ────────────────────────────────
    painel = _consolidar_painel(
        operacionais, bloqueios, todos_handoffs, deliberacoes, status_por_agente
    )

    # ── ETAPA 9: Persistir ────────────────────────────────────────────────
    _salvar_json("painel_operacional.json", painel)
    _salvar_json("handoffs_agentes.json", todos_handoffs)

    # ── ETAPA 10: Salvar estado ────────────────────────────────────────────
    resumo_str = (
        f"operacionais={len(operacionais)} bloqueios={len(bloqueios)} "
        f"deliberacoes={len(deliberacoes)} handoffs={len(todos_handoffs)}"
    )
    hash_exec = _hash_estado(painel)
    registrar_execucao(
        estado,
        saldo       = insumos["estado_financeiro"].get("ultimo_saldo") or 0.0,
        resumo      = resumo_str,
        n_escalados = len(deliberacoes),
        n_autonomos = len(operacionais),
        hash_exec   = hash_exec,
    )
    salvar_estado(NOME_AGENTE, estado)

    # ── ETAPA 11: Log final ────────────────────────────────────────────────
    log.info("=" * 60)
    log.info(f"AGENTE SECRETARIO — concluido")
    log.info(f"  itens operacionais   : {len(operacionais)}")
    log.info(f"  bloqueios            : {len(bloqueios)}")
    log.info(f"  handoffs criados     : {n_handoffs_criados} (total: {len(todos_handoffs)})")
    log.info(f"  deliberacoes conselho: {len(deliberacoes)}")
    log.info("=" * 60)

    return {
        "agente":              NOME_AGENTE,
        "timestamp":           ts,
        "operacionais":        len(operacionais),
        "bloqueios":           len(bloqueios),
        "handoffs_total":      len(todos_handoffs),
        "handoffs_criados":    n_handoffs_criados,
        "deliberacoes":        len(deliberacoes),
        "caminho_log":         str(caminho_log),
    }


# ─── Carregar insumos ────────────────────────────────────────────────────────

def _carregar_insumos_operacionais(log) -> dict:
    """Carrega todos os arquivos relevantes dos agentes existentes."""
    insumos = {
        "fila_consolidada":   _carregar_json("fila_decisoes_consolidada.json", padrao=[]),
        "agenda_hoje":        _carregar_json("agenda_do_dia.json",             padrao={"itens": []}),
        "estado_financeiro":  _carregar_json("estado_agente_financeiro.json",  padrao={}),
        "estado_comercial":   _carregar_json("estado_agente_comercial.json",   padrao={}),
        "pipeline":           _carregar_json("pipeline_comercial.json",        padrao=[]),
        "followups":          _carregar_json("fila_followups.json",            padrao=[]),
        "historico":          _carregar_json("historico_abordagens.json",      padrao=[]),
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
    Não recria handoffs já registrados (dedup por referencia_id).
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
            "id":            hf_id,
            "agente_origem": fu.get("agente_origem", "agente_comercial"),
            "agente_destino": destino,
            "tipo_handoff":  fu.get("tipo_acao", "operacional"),
            "referencia_id": fu_id,
            "descricao":     f"{fu.get('contraparte', '?')} — {fu.get('descricao', '')[:80]}",
            "prioridade":    prioridade,
            "status":        "pendente",
            "depende_de":    fu.get("depende_de"),
            "registrado_em": agora,
            "atualizado_em": agora,
        })
        marcar_processado(estado, hf_id)
        log.info(f"  [hf novo] {hf_id} | {fu.get('agente_origem')} -> {destino} | {fu.get('contraparte', '?')[:40]}")

    return novos, len(novos)


# ─── Bloqueios ───────────────────────────────────────────────────────────────

def _detectar_bloqueios(insumos, handoffs, log) -> list:
    """
    Detecta itens parados sem executor disponível ou sem dono claro.
    Nesta versão: follow-ups com destino em _AGENTES_FUTUROS são bloqueios estruturais.
    """
    bloqueios = []
    vistos    = set()

    # Handoffs pendentes para agentes futuros = bloqueio estrutural
    for hf in handoffs:
        if hf.get("agente_destino") in _AGENTES_FUTUROS and hf.get("status") == "pendente":
            fu_id = hf.get("referencia_id", hf["id"])
            if fu_id in vistos:
                continue
            vistos.add(fu_id)
            # encontrar contraparte
            fu = next((f for f in insumos["followups"] if f.get("id") == fu_id), {})
            bloqueios.append({
                "tipo":          "agente_destino_nao_disponivel",
                "referencia_id": fu_id,
                "handoff_id":    hf["id"],
                "agente_destino": hf["agente_destino"],
                "contraparte":   fu.get("contraparte", hf.get("descricao", "?")[:40]),
                "descricao":     f"Follow-up aguarda {hf['agente_destino']} (ainda nao implementado)",
            })

    if bloqueios:
        log.info(f"  Bloqueios detectados: {len(bloqueios)} (agente_executor_contato nao disponivel)")

    return bloqueios


# ─── Deliberações do conselho ────────────────────────────────────────────────

def _detectar_deliberacoes_conselho(insumos, log) -> list:
    """
    Extrai itens da fila_consolidada que são deliberativos (alta urgência ou tipo sensível).
    Não adiciona à fila — apenas superficia no painel.
    Deduplica por item_id.
    """
    deliberacoes = []
    vistos = set()

    for item in insumos["fila_consolidada"]:
        item_id  = item.get("item_id", "")
        urgencia = item.get("urgencia", "")
        tipo     = item.get("tipo", "")

        if item_id in vistos:
            continue

        if urgencia in _URGENCIAS_DELIBERACAO or tipo in _TIPOS_DELIBERACAO:
            deliberacoes.append({
                "item_id":       item_id,
                "agente_origem": item.get("agente_origem", "?"),
                "tipo":          tipo,
                "descricao":     item.get("descricao", ""),
                "urgencia":      urgencia,
                "acao_sugerida": item.get("acao_sugerida", ""),
                "prazo_sugerido": item.get("prazo_sugerido"),
                "status_aprovacao": item.get("status_aprovacao", "pendente"),
            })
            vistos.add(item_id)
            log.info(f"  [deliberacao] {item_id} | {urgencia} | {tipo}")

    return deliberacoes


# ─── Itens operacionais ──────────────────────────────────────────────────────

def _itens_operacionais(insumos, deliberacoes) -> list:
    """
    Itens operacionais prioritários = follow-ups pendentes + pipeline em revisão.
    Exclui itens que já são deliberações do conselho.
    """
    ids_deliberacao = {d["item_id"] for d in deliberacoes}
    operacionais = []

    # Follow-ups pendentes de execução
    for fu in insumos["followups"]:
        if fu.get("status") == "pendente_execucao":
            operacionais.append({
                "tipo":          "followup_pendente",
                "referencia_id": fu["id"],
                "contraparte":   fu.get("contraparte", "?"),
                "canal":         fu.get("canal", "?"),
                "acao":          fu.get("tipo_acao", "?"),
                "agente_destino": fu.get("agente_destino", "?"),
                "descricao":     fu.get("descricao", "")[:100],
            })

    # Pipeline em aguardando_execucao (sem executor)
    for opp in insumos["pipeline"]:
        if opp.get("status_operacional") == "aguardando_execucao":
            operacionais.append({
                "tipo":          "oportunidade_aguardando_execucao",
                "referencia_id": opp["id"],
                "contraparte":   opp.get("contraparte", "?"),
                "estagio":       opp.get("estagio", "?"),
                "prioridade":    opp.get("prioridade", "?"),
                "canal_sugerido": opp.get("canal_sugerido", "?"),
                "depende_de":    opp.get("depende_de", "?"),
                "descricao":     f"Oportunidade {opp.get('estagio')} aguardando agente_executor_contato",
            })

    return operacionais


# ─── Status por agente ───────────────────────────────────────────────────────

def _status_por_agente(insumos) -> dict:
    ef = insumos["estado_financeiro"]
    ec = insumos["estado_comercial"]
    pipeline   = insumos["pipeline"]
    followups  = insumos["followups"]

    por_estagio = {}
    for opp in pipeline:
        e = opp.get("estagio", "desconhecido")
        por_estagio[e] = por_estagio.get(e, 0) + 1

    return {
        "agente_financeiro": {
            "ultima_execucao":         ef.get("ultima_execucao"),
            "ultimo_saldo":            ef.get("ultimo_saldo"),
            "ultimo_resumo":           ef.get("ultimo_resumo", "")[:120],
            "itens_pendentes_escalados": len(ef.get("itens_pendentes_escalados", [])),
            "itens_processados":       len(ef.get("itens_processados", [])),
        },
        "agente_comercial": {
            "ultima_execucao":         ec.get("ultima_execucao"),
            "pipeline_total":          len(pipeline),
            "pipeline_por_estagio":    por_estagio,
            "followups_pendentes":     sum(1 for f in followups if f.get("status") == "pendente_execucao"),
            "itens_pendentes_escalados": len(ec.get("itens_pendentes_escalados", [])),
            "itens_processados":       len(ec.get("itens_processados", [])),
        },
    }


# ─── Painel operacional ──────────────────────────────────────────────────────

def _consolidar_painel(operacionais, bloqueios, handoffs, deliberacoes, status_por_agente) -> dict:
    hoje = date.today().isoformat()
    agora = datetime.now().isoformat(timespec="seconds")

    handoffs_pendentes = [h for h in handoffs if h.get("status") == "pendente"]

    resumo = _resumo_geral(operacionais, bloqueios, deliberacoes, status_por_agente)

    return {
        "data_referencia":              hoje,
        "gerado_em":                    agora,
        "resumo_geral":                 resumo,
        "itens_operacionais_prioritarios": operacionais,
        "bloqueios":                    bloqueios,
        "handoffs_pendentes":           handoffs_pendentes,
        "deliberacoes_conselho":        deliberacoes,
        "status_por_agente":            status_por_agente,
    }


def _resumo_geral(operacionais, bloqueios, deliberacoes, status_por_agente) -> str:
    partes = []
    sf = status_por_agente.get("agente_financeiro", {})
    sc = status_por_agente.get("agente_comercial", {})

    saldo = sf.get("ultimo_saldo")
    if saldo is not None:
        partes.append(f"Caixa: R$ {saldo:,.2f}")

    pipeline_total = sc.get("pipeline_total", 0)
    if pipeline_total:
        partes.append(f"Pipeline: {pipeline_total} oportunidade(s)")

    if deliberacoes:
        partes.append(f"{len(deliberacoes)} deliberacao(oes) aguardando conselho")

    if bloqueios:
        partes.append(f"{len(bloqueios)} bloqueio(s) aguardando agente futuro")

    fu_pend = sc.get("followups_pendentes", 0)
    if fu_pend:
        partes.append(f"{fu_pend} follow-up(s) prontos para execucao")

    return " | ".join(partes) if partes else "Sistema inicializado"


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
    logging.getLogger(__name__).info(f"Salvo: {caminho} ({len(dados) if isinstance(dados, list) else 1} registros)")


def _hash_estado(painel: dict) -> str:
    chave = json.dumps({
        "operacionais":  len(painel.get("itens_operacionais_prioritarios", [])),
        "bloqueios":     len(painel.get("bloqueios", [])),
        "deliberacoes":  len(painel.get("deliberacoes_conselho", [])),
        "handoffs":      len(painel.get("handoffs_pendentes", [])),
    }, sort_keys=True)
    return hashlib.md5(chave.encode()).hexdigest()[:16]
