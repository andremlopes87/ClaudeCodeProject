"""
agentes/comercial/agente_comercial.py — Agente comercial operacional.

Lê oportunidades qualificadas, mantém o pipeline, gera follow-ups internos
e escala deliberações estratégicas para o conselho.

Modelo operacional:
  - Não envia mensagens reais.
  - Não avança estágio por inferência ou tempo — só por eventos registrados por outros agentes.
  - Gera follow-ups como handoffs para agente_executor_contato (futuro).
  - Sobe para deliberação do conselho apenas exceções estratégicas.
  - Registra histórico de tudo que foi decidido.

Integrações:
  - Lê: dados/fila_execucao_comercial.json
  - Escreve: pipeline_comercial, fila_followups, historico_abordagens, estado, agenda, fila_consolidada
  - Reutiliza: core/controle_agente.py
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import config
from core.controle_agente import (
    carregar_estado,
    salvar_estado,
    ja_processado,
    esta_pendente,
    marcar_processado,
    marcar_pendente,
    resolver_pendente,
    registrar_execucao,
    gerar_hash_execucao,
    registrar_na_fila_consolidada,
    atualizar_agenda,
    carregar_aprovacoes,
    configurar_log_agente,
)
from core.deliberacoes import buscar_deliberacao_por_item_id, marcar_como_aplicada
from modulos.comercial.pipeline_manager import (
    carregar_pipeline,
    carregar_followups,
    carregar_historico,
    importar_oportunidades_novas,
    criar_followup_inicial,
    atualizar_metricas_pipeline,
    detectar_casos_para_revisao,
    detectar_casos_para_escalamento,
    criar_evento_historico,
    salvar_pipeline,
    salvar_followups,
    salvar_historico,
    persistir_arquivos_base,
)

NOME_AGENTE = "agente_comercial"
_ARQ_LEADS  = "fila_execucao_comercial.json"


def executar() -> dict:
    """
    Executa o agente comercial completo.
    Retorna dict com resumo da execução.
    """
    log, caminho_log = configurar_log_agente(NOME_AGENTE)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")

    log.info("=" * 60)
    log.info(f"AGENTE COMERCIAL — inicio {ts}")
    log.info("=" * 60)

    # ── ETAPA 1: Garantir arquivos base ───────────────────────────────────
    persistir_arquivos_base()

    # ── ETAPA 2: Carregar estado ───────────────────────────────────────────
    estado = carregar_estado(NOME_AGENTE)
    log.info(
        f"Estado carregado: ultima_execucao={estado['ultima_execucao']} | "
        f"processados={len(estado['itens_processados'])} | "
        f"pendentes={len(estado['itens_pendentes_escalados'])}"
    )

    # ── ETAPA 3: Verificar aprovações do conselho ──────────────────────────
    aprovacoes = carregar_aprovacoes()
    aprovados_agora = _processar_aprovacoes(aprovacoes, estado, log)

    # ── ETAPA 3b: Verificar deliberações do conselho resolvidas ───────────
    aprovados_agora += _processar_deliberacoes_resolvidas(estado, log)

    # ── ETAPA 4: Carregar dados ────────────────────────────────────────────
    leads     = _carregar_leads(log)
    pipeline  = carregar_pipeline()
    followups = carregar_followups()
    historico = carregar_historico()
    log.info(
        f"Dados carregados: {len(leads)} leads | "
        f"{len(pipeline)} opp no pipeline | "
        f"{len(followups)} follow-ups"
    )

    # ── ETAPA 4b: Aplicar resultados de contato registrados ───────────────
    res_stats = _aplicar_resultados_contato(pipeline, followups, historico, log)

    # ── ETAPA 5: Importar oportunidades novas ─────────────────────────────
    novas_opps    = []
    novos_fus     = []
    novos_eventos = []

    candidatas = importar_oportunidades_novas(leads, pipeline)
    leads_idx  = {str(l.get("osm_id", "")): l for l in leads}

    for opp in candidatas:
        if ja_processado(estado, opp["id"]):
            log.info(f"  [skip] {opp['id']} — ja importado em execucao anterior")
            continue

        lead = leads_idx.get(opp["origem_id"], {})
        fu   = criar_followup_inicial(opp, lead, followups + novos_fus)

        # Vincular follow-up à oportunidade
        opp["depende_de"] = fu["id"]

        novas_opps.append(opp)
        novos_fus.append(fu)
        marcar_processado(estado, opp["id"])

        # Histórico: oportunidade importada
        novos_eventos.append(criar_evento_historico(
            opp["id"], opp["contraparte"],
            "oportunidade_importada",
            f"Importada de fila_execucao_comercial | prioridade={opp['prioridade']} | canal={opp['canal_sugerido']}",
        ))
        # Histórico: follow-up criado
        novos_eventos.append(criar_evento_historico(
            opp["id"], opp["contraparte"],
            "followup_criado",
            f"Follow-up inicial criado: {fu['id']} | destino={fu['agente_destino']} | canal={fu['canal']}",
        ))

        log.info(
            f"  [importado] {opp['id']} — {opp['contraparte']} | "
            f"prioridade={opp['prioridade']} | canal={opp['canal_sugerido']}"
        )
        log.info(f"  [followup ] {fu['id']} → {fu['agente_destino']}")

    # Consolidar
    pipeline  = pipeline  + novas_opps
    followups = followups + novos_fus
    historico = historico + novos_eventos

    # ── ETAPA 6: Atualizar métricas ────────────────────────────────────────
    pipeline = atualizar_metricas_pipeline(pipeline)

    # ── ETAPA 7: Detectar casos para revisão interna ───────────────────────
    revisoes = detectar_casos_para_revisao(pipeline)
    for caso in revisoes:
        log.info(f"  [revisao] {caso['oportunidade_id']} — {caso['motivo']}")
        historico.append(criar_evento_historico(
            caso["oportunidade_id"], caso.get("contraparte", "?"),
            "marcado_revisao",
            caso["motivo"],
        ))

    # ── ETAPA 8: Detectar e escalar deliberações para o conselho ──────────
    escalamentos = detectar_casos_para_escalamento(pipeline)
    itens_para_consolidada = []

    for item in escalamentos:
        item_id = item["item_id"]
        if esta_pendente(estado, item_id):
            log.info(f"  [aguardando conselho] {item_id} — ja escalado")
            continue
        itens_para_consolidada.append(item)
        marcar_pendente(estado, item_id)
        log.info(f"  [ESCALAR conselho] {item_id} — {item['descricao'][:70]}")

        # Histórico: escalamento
        opp_id = item_id.replace("esc_", "")
        historico.append(criar_evento_historico(
            opp_id, item["descricao"].split("—")[0].strip(),
            "escalado_conselho",
            item["descricao"],
        ))

    if itens_para_consolidada:
        registrar_na_fila_consolidada(itens_para_consolidada)
        # Itens urgentes vão para agenda
        urgentes = [i for i in itens_para_consolidada if i.get("urgencia") == "alta"]
        if urgentes:
            atualizar_agenda(urgentes)

    # ── ETAPA 9: Persistir arquivos ────────────────────────────────────────
    salvar_pipeline(pipeline)
    salvar_followups(followups)
    salvar_historico(historico)

    # ── ETAPA 10: Salvar estado ────────────────────────────────────────────
    resultado_para_hash = {
        "posicao": {"saldo_atual_estimado": 0},  # placeholder para reutilizar gerar_hash_execucao
        "fila_riscos": escalamentos,
        "alertas": revisoes,
        "resumo": {"resumo_curto": f"pipeline={len(pipeline)} followups={len(followups)}"},
    }
    hash_exec = gerar_hash_execucao(resultado_para_hash)
    registrar_execucao(
        estado,
        saldo       = 0.0,
        resumo      = f"pipeline={len(pipeline)} | novas={len(novas_opps)} | escalados={len(itens_para_consolidada)}",
        n_escalados = len(itens_para_consolidada),
        n_autonomos = len(novas_opps),
        hash_exec   = hash_exec,
    )
    salvar_estado(NOME_AGENTE, estado)

    # ── ETAPA 11: Resumo final ─────────────────────────────────────────────
    resumo = {
        "agente":                NOME_AGENTE,
        "timestamp":             ts,
        "leads_lidos":           len(leads),
        "oportunidades_novas":   len(novas_opps),
        "pipeline_total":        len(pipeline),
        "followups_criados":     len(novos_fus),
        "followups_total":       len(followups),
        "casos_revisao":         len(revisoes),
        "escalados_conselho":    len(itens_para_consolidada),
        "aprovados_nesta_exec":  aprovados_agora,
        "resultados_aplicados":  res_stats["aplicados"],
        "followups_de_resultado": res_stats["novos_followups"],
        "caminho_log":           str(caminho_log),
    }

    log.info("=" * 60)
    log.info(f"AGENTE COMERCIAL — concluido")
    log.info(f"  leads lidos        : {len(leads)}")
    log.info(f"  oportunidades novas: {len(novas_opps)}")
    log.info(f"  pipeline total     : {len(pipeline)}")
    log.info(f"  follow-ups criados : {len(novos_fus)}")
    log.info(f"  resultados aplicados: {res_stats['aplicados']} | novos follow-ups: {res_stats['novos_followups']}")
    log.info(f"  casos para revisao : {len(revisoes)}")
    log.info(f"  escalados conselho : {len(itens_para_consolidada)}")
    log.info("=" * 60)

    return resumo


# ─── Aprovações do conselho ──────────────────────────────────────────────────

def _processar_aprovacoes(aprovacoes: list, estado: dict, log) -> int:
    """
    Verifica aprovações/rejeições do conselho para itens escalados por este agente.
    Resolve pendentes que foram respondidos.
    """
    pendentes = set(estado.get("itens_pendentes_escalados", []))
    resolvidos = 0
    for ap in aprovacoes:
        if ap.get("item_id") in pendentes and ap.get("decisao") in ("aprovado", "rejeitado"):
            resolver_pendente(estado, ap["item_id"])
            resolvidos += 1
            log.info(
                f"  [resolvido conselho] {ap['item_id']} — {ap['decisao']} "
                f"em {ap.get('data_decisao', '?')}"
            )
    return resolvidos


# ─── Resultados de contato ───────────────────────────────────────────────────

def _aplicar_resultados_contato(pipeline: list, followups: list, historico: list, log) -> dict:
    """
    Lê resultados_contato.json e aplica cada resultado pendente ao estado comercial.
    Modifica pipeline, followups e historico in-place.
    Marca resultados como aplicados no arquivo.
    Retorna stats: {aplicados, novos_followups}.
    """
    from modulos.comercial.processador_resultados_contato import (
        carregar_resultados_pendentes,
        aplicar_resultado_contato,
        marcar_resultado_como_aplicado,
    )

    pendentes = carregar_resultados_pendentes()
    if not pendentes:
        log.info("Resultados de contato: nenhum pendente")
        return {"aplicados": 0, "novos_followups": 0}

    log.info(f"Resultados de contato pendentes: {len(pendentes)}")
    novos_followups = 0

    for resultado in pendentes:
        tipo        = resultado.get("tipo_resultado", "?")
        contraparte = resultado.get("contraparte", "?")
        log.info(f"  [resultado] {tipo} | {contraparte[:40]}")

        acoes = aplicar_resultado_contato(resultado, pipeline, followups, historico, log)

        if acoes.get("novo_fu"):
            followups.append(acoes["novo_fu"])
            novos_followups += 1

        marcar_resultado_como_aplicado(resultado["id"])

    log.info(f"Resultados aplicados: {len(pendentes)} | novos follow-ups gerados: {novos_followups}")
    return {"aplicados": len(pendentes), "novos_followups": novos_followups}


# ─── Deliberações do conselho ────────────────────────────────────────────────

def _processar_deliberacoes_resolvidas(estado: dict, log) -> int:
    """
    Verifica se alguma deliberação do conselho foi decidida para itens pendentes deste agente.
    Resolve pendentes e marca deliberações como aplicadas.
    Retorna número de itens resolvidos.
    """
    pendentes  = list(estado.get("itens_pendentes_escalados", []))
    resolvidos = 0
    for item_id in pendentes:
        d = buscar_deliberacao_por_item_id(item_id)
        if d and d.get("status") == "deliberado":
            resolver_pendente(estado, item_id)
            marcar_como_aplicada(d["id"])
            resolvidos += 1
            log.info(
                f"  [deliberado] {item_id} — decisao={str(d.get('decisao_conselho', '?'))[:60]}"
            )
    if resolvidos:
        log.info(f"Deliberacoes aplicadas: {resolvidos} itens fechados pelo comercial")
    return resolvidos


# ─── Carga de leads ──────────────────────────────────────────────────────────

def _carregar_leads(log) -> list:
    caminho = config.PASTA_DADOS / _ARQ_LEADS
    if not caminho.exists():
        log.warning(f"Arquivo de leads nao encontrado: {caminho}")
        return []
    with open(caminho, "r", encoding="utf-8") as f:
        leads = json.load(f)
    log.info(f"Leads carregados: {len(leads)} de {caminho}")
    return leads
