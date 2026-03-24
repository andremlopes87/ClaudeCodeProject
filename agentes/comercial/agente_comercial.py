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
from core.politicas_empresa import carregar_politicas
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
    enriquecer_oportunidade_com_marketing,
    detectar_handoffs_marketing_para_enriquecimento,
    detectar_pipeline_sem_contexto_marketing,
)

NOME_AGENTE      = "agente_comercial"
_ARQ_LEADS       = "fila_execucao_comercial.json"
_ARQ_HANDOFFS    = "handoffs_agentes.json"
_ARQ_MKT_PROP    = "fila_propostas_marketing.json"


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

    # ── ETAPA 0: Carregar políticas operacionais e identidade ─────────────
    politicas = carregar_politicas()
    linhas_priorizadas = politicas.get("linhas_priorizadas", [])
    foco_curto_prazo   = politicas.get("comercial", {}).get("foco_curto_prazo", False)
    modo_empresa = politicas.get("modo_empresa", "normal")
    log.info(f"Politicas carregadas: modo={modo_empresa} | linhas_prio={linhas_priorizadas} | foco_curto={foco_curto_prazo}")

    try:
        from core.identidade_empresa import obter_contexto_comercial
        contexto_empresa = obter_contexto_comercial()
        log.info(
            f"Identidade carregada: empresa='{contexto_empresa['nome_empresa']}' | "
            f"tom='{contexto_empresa['tom_voz']}'"
        )
    except Exception as _exc_id:
        contexto_empresa = {}
        log.warning(f"Identidade nao carregada: {_exc_id}")

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

    # ── ETAPA 3c: Aplicar respostas de propostas pendentes ────────────────
    n_respostas_aplicadas = 0
    try:
        from core.expediente_propostas import (
            respostas_pendentes_de_aplicacao, aplicar_resposta_proposta
        )
        respostas_pendentes = respostas_pendentes_de_aplicacao()
        for resp in respostas_pendentes:
            resultado = aplicar_resposta_proposta(resp)
            if resultado.get("aplicado"):
                n_respostas_aplicadas += 1
                log.info(
                    f"  [resposta_proposta] {resp['tipo_resposta']} aplicada "
                    f"para opp {resp.get('oportunidade_id','?')} "
                    f"— efeitos: {resultado.get('efeitos', [])}"
                )
    except Exception as _exc_resp:
        log.warning(f"  [respostas_propostas] aplicação parcial: {_exc_resp}")

    # ── ETAPA 3d: Converter expansões prontas em oportunidades ───────────
    n_expansoes_convertidas = 0
    try:
        from core.acompanhamento_contas import processar_expansoes_para_handoff
        # pipeline ainda não carregado aqui — carregamos preview mínimo
        _pipe_preview = carregar_pipeline()
        _res_exp = processar_expansoes_para_handoff(_pipe_preview,
                                                    origem=NOME_AGENTE)
        n_expansoes_convertidas = _res_exp.get("convertidas", 0)
        if n_expansoes_convertidas:
            log.info(f"  [expansao] {n_expansoes_convertidas} expansao(oes) convertida(s) em oportunidade")
    except Exception as _exc_exp:
        log.warning(f"  [expansao] conversao parcial: {_exc_exp}")

    # ── ETAPA 4: Carregar dados ────────────────────────────────────────────
    leads     = _carregar_leads(log)
    pipeline  = carregar_pipeline()
    followups = carregar_followups()
    historico = carregar_historico()
    handoffs  = _carregar_handoffs(log)
    log.info(
        f"Dados carregados: {len(leads)} leads | "
        f"{len(pipeline)} opp no pipeline | "
        f"{len(followups)} follow-ups | "
        f"{len(handoffs)} handoffs"
    )

    # ── ETAPA 4b: Aplicar resultados de contato registrados ───────────────
    res_stats = _aplicar_resultados_contato(pipeline, followups, historico, log)

    # ── ETAPA 5: Importar oportunidades novas ─────────────────────────────
    novas_opps    = []
    novos_fus     = []
    novos_eventos = []

    candidatas = importar_oportunidades_novas(leads, pipeline, handoffs)
    leads_idx  = {str(l.get("osm_id", "")): l for l in leads}

    # Ordenar candidatas: linhas priorizadas primeiro; dentro delas, foco_curto_prazo
    # prioriza menor prazo de fechamento esperado.
    if linhas_priorizadas:
        candidatas = sorted(
            candidatas,
            key=lambda o: (
                0 if o.get("linha_servico_sugerida") in linhas_priorizadas else 1,
                0 if foco_curto_prazo and o.get("prioridade") == "alta" else 1,
            )
        )
        log.info(f"  [politica] candidatas reordenadas por linhas priorizadas: {linhas_priorizadas}")

    for opp in candidatas:
        if ja_processado(estado, opp["id"]):
            log.info(f"  [skip] {opp['id']} — ja importado em execucao anterior")
            continue

        lead   = leads_idx.get(opp["origem_id"], {})
        fu     = criar_followup_inicial(opp, lead, followups + novos_fus)
        origem = opp.get("origem_oportunidade", "prospeccao")

        # Vincular follow-up à oportunidade
        opp["depende_de"] = fu["id"]

        # Enriquecer com oferta do catálogo (melhor esforço — não bloqueia)
        try:
            from core.ofertas_empresa import enriquecer_oportunidade_com_oferta
            enriquecer_oportunidade_com_oferta(opp)
        except Exception as _exc_of:
            log.debug(f"  [ofertas] enriquecimento ignorado: {_exc_of}")

        # Associar conta mestra (melhor esforço — não bloqueia)
        try:
            from core.contas_empresa import encontrar_ou_criar_conta, vincular_oportunidade_a_conta
            _conta = encontrar_ou_criar_conta({
                "nome_empresa":       opp.get("contraparte", ""),
                "email_principal":    opp.get("email", ""),
                "telefone_principal": opp.get("telefone", ""),
                "whatsapp":           opp.get("whatsapp", ""),
                "instagram":          opp.get("instagram", ""),
                "site":               opp.get("site", ""),
                "cidade":             opp.get("cidade", ""),
                "categoria":          opp.get("categoria", ""),
                "origem_inicial":     opp.get("origem_oportunidade", origem),
            }, origem="agente_comercial")
            if _conta:
                opp["conta_id"] = _conta["id"]
                vincular_oportunidade_a_conta(opp["id"], _conta["id"],
                                              origem="agente_comercial")
        except Exception as _exc_cnt:
            log.debug(f"  [contas] vinculacao ignorada: {_exc_cnt}")

        novas_opps.append(opp)
        novos_fus.append(fu)
        marcar_processado(estado, opp["id"])

        # Histórico com tipo específico por origem
        tipo_ev_import = f"oportunidade_importada_{origem}"
        tipo_ev_fu     = f"followup_criado_{origem}"

        novos_eventos.append(criar_evento_historico(
            opp["id"], opp["contraparte"],
            tipo_ev_import,
            (
                f"Importada de fila_execucao_comercial | origem={origem} | "
                f"prioridade={opp['prioridade']} | canal={opp['canal_sugerido']} | "
                f"abordagem={opp.get('abordagem_inicial_tipo', '?')} | "
                f"linha={opp.get('linha_servico_sugerida', '?')}"
            ),
        ))
        novos_eventos.append(criar_evento_historico(
            opp["id"], opp["contraparte"],
            tipo_ev_fu,
            f"Follow-up inicial criado: {fu['id']} | origem={origem} | descricao={fu['descricao'][:100]}",
        ))

        log.info(
            f"  [importado/{origem}] {opp['id']} — {opp['contraparte']} | "
            f"prioridade={opp['prioridade']} | abordagem={opp.get('abordagem_inicial_tipo')}"
        )
        log.info(f"  [followup/{origem}] {fu['id']} → {fu['agente_destino']}")

    # ── ETAPA 5b: Enriquecer oportunidades com dados de marketing ─────────
    n_enriquecidas = 0
    mkt_props  = _carregar_propostas_marketing(log)
    mkt_por_osm = {str(p.get("osm_id", "")): p for p in mkt_props}

    # 5b-i: via handoffs ativos de marketing (empresas novas com handoff)
    pares_handoff = detectar_handoffs_marketing_para_enriquecimento(pipeline, handoffs)
    for opp_idx, osm_id, handoff_mkt in pares_handoff:
        lead_mkt = mkt_por_osm.get(osm_id, leads_idx.get(osm_id, {}))
        opp      = pipeline[opp_idx]
        if enriquecer_oportunidade_com_marketing(opp, lead_mkt):
            novos_eventos.append(criar_evento_historico(
                opp["id"], opp["contraparte"],
                "oportunidade_enriquecida_marketing",
                f"Via handoff {handoff_mkt['id']} | linha={opp.get('linha_servico_sugerida')} | prio={opp.get('prioridade')}",
            ))
            n_enriquecidas += 1
            log.info(f"  [enriquecido/handoff_mkt] {opp['id']} — {opp['contraparte']}")

    # 5b-ii: itens sem contexto de origem que têm dados em fila_propostas_marketing
    sem_ctx = detectar_pipeline_sem_contexto_marketing(pipeline)
    for opp_idx, osm_id in sem_ctx:
        opp = pipeline[opp_idx]
        # Determinar origem via handoffs
        origem_info = detectar_origem_handoff_opp(osm_id, handoffs, mkt_por_osm)
        _aplicar_contexto_origem(opp, origem_info, mkt_por_osm.get(osm_id, leads_idx.get(osm_id, {})))
        if opp.get("origem_oportunidade"):
            novos_eventos.append(criar_evento_historico(
                opp["id"], opp["contraparte"],
                f"contexto_origem_aplicado_{opp['origem_oportunidade']}",
                f"Campos de origem preenchidos retroativamente | origem={opp['origem_oportunidade']} | abordagem={opp.get('abordagem_inicial_tipo')}",
            ))
            n_enriquecidas += 1

    if n_enriquecidas:
        log.info(f"  [enriquecimento] {n_enriquecidas} oportunidades com contexto de origem atualizado")

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

    # ── ETAPA 8b: Gerar propostas formais para oportunidades qualificadas ──
    n_propostas_geradas = 0
    try:
        from core.propostas_empresa import (
            gerar_proposta_comercial, vincular_proposta_ao_pipeline
        )
        for opp in pipeline:
            if opp.get("estagio") in {"ganho", "perdido", "encerrado"}:
                continue
            if opp.get("proposta_id"):
                continue  # já vinculada
            if not opp.get("oferta_id"):
                continue  # sem oferta — não gerar ainda
            proposta = gerar_proposta_comercial(opp, origem="agente_comercial")
            if proposta:
                vincular_proposta_ao_pipeline(opp, proposta)
                n_propostas_geradas += 1
                novos_eventos.append(criar_evento_historico(
                    opp["id"], opp["contraparte"],
                    "proposta_gerada",
                    f"Proposta {proposta['id']} gerada | status={proposta['status']} | "
                    f"valor=R${proposta.get('proposta_valor')} | oferta={proposta['oferta_id']}",
                ))
                log.info(f"  [proposta] {proposta['id']} para {opp['contraparte']} status={proposta['status']}")
    except Exception as _exc_prop:
        log.warning(f"  [propostas] geração parcial falhou: {_exc_prop}")

    if n_propostas_geradas:
        log.info(f"  [propostas] {n_propostas_geradas} propostas geradas neste ciclo")

    # ── ETAPA 8c: Gerar contratos para propostas aceitas ──────────────────
    n_contratos_gerados = 0
    n_planos_gerados    = 0
    try:
        from core.contratos_empresa import processar_contratos_pendentes
        _res_ct = processar_contratos_pendentes(origem=NOME_AGENTE)
        n_contratos_gerados = _res_ct.get("contratos_gerados", 0)
        n_planos_gerados    = _res_ct.get("planos_gerados", 0)
        if n_contratos_gerados:
            log.info(f"  [contratos] {n_contratos_gerados} contrato(s) | {n_planos_gerados} plano(s)")
    except Exception as _exc_ct:
        log.warning(f"  [contratos] geracao parcial: {_exc_ct}")

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
        "enriquecidas_marketing": n_enriquecidas,
        "casos_revisao":         len(revisoes),
        "escalados_conselho":    len(itens_para_consolidada),
        "propostas_geradas":        n_propostas_geradas,
        "respostas_prop_aplicadas": n_respostas_aplicadas,
        "aprovados_nesta_exec":     aprovados_agora,
        "resultados_aplicados":  res_stats["aplicados"],
        "followups_de_resultado": res_stats["novos_followups"],
        "contas_vinculadas":       sum(1 for o in novas_opps if o.get("conta_id")),
        "expansoes_convertidas":   n_expansoes_convertidas,
        "contratos_gerados":       n_contratos_gerados,
        "planos_gerados":          n_planos_gerados,
        "caminho_log":             str(caminho_log),
    }

    log.info("=" * 60)
    log.info(f"AGENTE COMERCIAL — concluido")
    log.info(f"  leads lidos        : {len(leads)}")
    log.info(f"  oportunidades novas: {len(novas_opps)}")
    log.info(f"  pipeline total     : {len(pipeline)}")
    log.info(f"  follow-ups criados : {len(novos_fus)}")
    log.info(f"  resultados aplicados: {res_stats['aplicados']} | novos follow-ups: {res_stats['novos_followups']}")
    log.info(f"  enriquecidas marketing: {n_enriquecidas}")
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


# ─── Carga de leads e handoffs ───────────────────────────────────────────────

def _carregar_leads(log) -> list:
    caminho = config.PASTA_DADOS / _ARQ_LEADS
    if not caminho.exists():
        log.warning(f"Arquivo de leads nao encontrado: {caminho}")
        return []
    with open(caminho, "r", encoding="utf-8") as f:
        leads = json.load(f)
    log.info(f"Leads carregados: {len(leads)} de {caminho}")
    return leads


def _carregar_handoffs(log) -> list:
    caminho = config.PASTA_DADOS / _ARQ_HANDOFFS
    if not caminho.exists():
        return []
    with open(caminho, "r", encoding="utf-8") as f:
        handoffs = json.load(f)
    log.info(f"Handoffs carregados: {len(handoffs)}")
    return handoffs


def _carregar_propostas_marketing(log) -> list:
    caminho = config.PASTA_DADOS / _ARQ_MKT_PROP
    if not caminho.exists():
        return []
    with open(caminho, "r", encoding="utf-8") as f:
        props = json.load(f)
    log.info(f"Propostas marketing carregadas: {len(props)}")
    return props


def detectar_origem_handoff_opp(osm_id: str, handoffs: list, mkt_por_osm: dict) -> dict:
    """Detecta origem de uma oportunidade já no pipeline via handoffs + dados de marketing."""
    from modulos.comercial.pipeline_manager import detectar_origem_handoff
    info = detectar_origem_handoff(osm_id, handoffs)
    # Se não detectado via handoffs mas tem dados de marketing, assume marketing+prospeccao
    if info["origem"] == "prospeccao" and osm_id in mkt_por_osm:
        return {"origem": "prospeccao_e_marketing", "tipo_handoff": "dupla_origem", "handoff_id": None}
    return info


def _aplicar_contexto_origem(opp: dict, origem_info: dict, lead: dict) -> None:
    """Aplica campos de contexto de origem a oportunidade existente no pipeline."""
    from modulos.comercial.pipeline_manager import montar_contexto_comercial_por_origem
    origem = origem_info.get("origem", "prospeccao")

    # Para prospeccao_e_marketing, usar contexto de marketing
    info_efetiva = {"origem": "marketing" if "marketing" in origem else "prospeccao",
                    "tipo_handoff": origem_info.get("tipo_handoff", "")}
    ctx = montar_contexto_comercial_por_origem(lead, info_efetiva)

    opp["origem_oportunidade"]    = origem
    opp["tipo_handoff"]           = ctx["tipo_handoff"]
    opp["contexto_origem"]        = ctx["contexto_origem"]
    opp["linha_servico_sugerida"] = ctx["linha_servico_sugerida"]
    opp["abordagem_inicial_tipo"] = ctx["abordagem_inicial_tipo"]
    opp["atualizado_em"]          = datetime.now().isoformat(timespec="seconds")
