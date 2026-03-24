"""
core/observabilidade_empresa.py

Consolida dados operacionais da empresa em arquivos padronizados para
consumo pelo Painel do Conselho. Executa ao final de cada ciclo.
Nao modifica dados operacionais. Apenas le e consolida.

Saidas:
  dados/painel_conselho.json
  dados/feed_eventos_empresa.json
  dados/metricas_empresa.json
  dados/metricas_agentes.json
  dados/metricas_areas.json
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_AGENTES_CONHECIDOS = [
    {"agente": "agente_financeiro",              "area": "financeiro"},
    {"agente": "agente_prospeccao",              "area": "prospeccao"},
    {"agente": "agente_marketing",               "area": "marketing"},
    {"agente": "agente_comercial",               "area": "comercial"},
    {"agente": "agente_secretario",              "area": "operacao"},
    {"agente": "agente_executor_contato",        "area": "comercial"},
    {"agente": "integrador_canais",              "area": "comercial"},
    {"agente": "agente_operacao_entrega",        "area": "entrega"},
    {"agente": "gerador_insumos_desde_contato",  "area": "entrega"},
    {"agente": "avaliador_fechamento_comercial", "area": "comercial"},
]


# ─── Ponto de entrada ─────────────────────────────────────────────────────────

def executar_observabilidade() -> dict:
    """
    Gera todos os arquivos de observabilidade + saúde da empresa.
    Retorna resumo de quantos arquivos foram gerados.
    """
    agora = datetime.now().isoformat(timespec="seconds")
    logger.info("[observabilidade] iniciando consolidacao...")

    metricas_emp  = gerar_metricas_empresa()
    metricas_ag   = gerar_metricas_agentes()
    metricas_ar   = gerar_metricas_areas()
    feed          = gerar_feed_eventos_empresa()
    painel        = consolidar_painel_conselho(metricas_emp, metricas_ag, metricas_ar, feed)

    _salvar("metricas_empresa.json",       metricas_emp)
    _salvar("metricas_agentes.json",       metricas_ag)
    _salvar("metricas_areas.json",         metricas_ar)
    _salvar("feed_eventos_empresa.json",   feed)
    _salvar("painel_conselho.json",        painel)

    # Atualizar saúde da empresa após consolidar métricas
    try:
        from core.confiabilidade_empresa import calcular_saude_empresa
        calcular_saude_empresa()
    except Exception as exc:
        logger.warning(f"[observabilidade] saude nao calculada: {exc}")

    logger.info(
        f"[observabilidade] concluido — "
        f"{len(feed['eventos'])} eventos, "
        f"{metricas_emp.get('deliberacoes_pendentes', 0)} deliberacoes pendentes"
    )
    return {
        "agente":           "observabilidade_empresa",
        "arquivos_gerados": 5,
        "eventos_feed":     len(feed["eventos"]),
        "atualizado_em":    agora,
    }


# ─── Painel do Conselho ────────────────────────────────────────────────────────

def consolidar_painel_conselho(
    metricas_emp: dict,
    metricas_ag: list,
    metricas_ar: dict,
    feed: dict,
) -> dict:
    estado  = _ler("estado_empresa.json",    {})
    ciclo   = _ler("ciclo_operacional.json", {})
    delibs  = _ler("deliberacoes_conselho.json", [])
    riscos  = _ler("fila_riscos_financeiros.json", [])
    caixa   = _ler("posicao_caixa.json", {})
    gargalos = resumir_gargalos_criticos(metricas_emp, metricas_ar)

    # Resumo executivo
    n_erros  = metricas_emp.get("erros_ciclo_atual", 0)
    n_etapas = metricas_emp.get("etapas_ciclo_atual", 0)
    delib_p  = metricas_emp.get("deliberacoes_pendentes", 0)
    hoff_p   = metricas_emp.get("total_handoffs_pendentes", 0)
    resumo   = (
        f"Ciclo {ciclo.get('ciclo_id','?')} — {n_etapas} etapas, {n_erros} erros. "
        f"{delib_p} deliberacoes pendentes. {hoff_p} handoffs pendentes."
    )

    # Proximas acoes relevantes
    proximas = _extrair_proximas_acoes(delibs, gargalos, riscos)

    # Saúde da empresa (ler do arquivo se disponível)
    saude = {}
    try:
        saude_arq = config.PASTA_DADOS / "saude_empresa.json"
        if saude_arq.exists():
            with open(saude_arq, "r", encoding="utf-8") as _f:
                saude = json.load(_f)
    except Exception:
        pass

    # Identidade da empresa (resumo para painel)
    identidade_resumo = {}
    try:
        from core.identidade_empresa import carregar_identidade
        _id = carregar_identidade()
        identidade_resumo = {
            "nome_oficial":   _id.get("nome_oficial", ""),
            "nome_exibicao":  _id.get("nome_exibicao", ""),
            "descricao_curta": _id.get("descricao_curta", ""),
        }
    except Exception:
        pass

    return {
        "atualizado_em":    datetime.now().isoformat(timespec="seconds"),
        "status_empresa":   estado.get("status_empresa", "desconhecido"),
        "resumo_executivo": resumo,
        "ultimo_ciclo":     _resumir_ciclo(ciclo),
        "agentes":          metricas_ag,
        "areas":            metricas_ar,
        "gargalos":         gargalos,
        "riscos":           riscos[:10],
        "deliberacoes":     resumir_deliberacoes_conselho(delibs),
        "operacao_comercial":  metricas_ar.get("comercial", {}),
        "operacao_entrega":    metricas_ar.get("entrega", {}),
        "operacao_financeira": metricas_ar.get("financeiro", {}),
        "proximas_acoes_relevantes": proximas,
        "metricas":         metricas_emp,
        "saude":            saude,
        "identidade":       identidade_resumo,
    }


# ─── Feed de eventos ──────────────────────────────────────────────────────────

def gerar_feed_eventos_empresa() -> dict:
    """Constroi feed cronologico unificado a partir dos dados existentes."""
    eventos = []
    ciclo   = _ler("ciclo_operacional.json", {})
    delibs  = _ler("deliberacoes_conselho.json", [])
    pipeline_com = _ler("pipeline_comercial.json", [])
    pipeline_ent = _ler("pipeline_entrega.json", [])
    resultados   = _ler("resultados_contato.json", [])
    riscos       = _ler("fila_riscos_financeiros.json", [])
    historico_fech = _ler("historico_fechamento_comercial.json", [])

    # Ciclo rodado
    if ciclo.get("ciclo_id"):
        eventos.append(_evento(
            tipo="ciclo_rodado",
            agente="orquestrador",
            area="operacao",
            ref=ciclo["ciclo_id"],
            titulo=f"Ciclo operacional: {ciclo['ciclo_id']}",
            descricao=f"Status: {ciclo.get('status_geral','?')} | {len(ciclo.get('etapas',[]))} etapas",
            severidade="info",
            timestamp=ciclo.get("finalizado_em", ""),
        ))
        # Agentes executados neste ciclo
        for etapa in ciclo.get("etapas", []):
            sev = "erro" if etapa["status"] == "erro" else "info"
            eventos.append(_evento(
                tipo="agente_executado",
                agente=etapa["nome_agente"],
                area=_area_do_agente(etapa["nome_agente"]),
                ref=ciclo["ciclo_id"],
                titulo=f"{etapa['nome_agente']} — {etapa['status']}",
                descricao=f"{etapa['duracao_ms']}ms" + (f" | ERRO: {etapa.get('erro','')[:80]}" if etapa.get("erro") else ""),
                severidade=sev,
                timestamp=etapa.get("finalizado_em", ""),
            ))

    # Deliberacoes criadas
    for d in delibs:
        eventos.append(_evento(
            tipo="deliberacao_criada",
            agente=d.get("agente_origem", "?"),
            area="operacao",
            ref=d.get("id", ""),
            titulo=d.get("titulo", "Deliberacao"),
            descricao=d.get("contexto_resumido", d.get("descricao", ""))[:120],
            severidade=_sev_deliberacao(d.get("urgencia", "")),
            timestamp=d.get("criado_em", ""),
        ))

    # Oportunidades promovidas (historico fechamento)
    for h in historico_fech:
        if h.get("acao") in ("ganho", "pronto_para_entrega"):
            eventos.append(_evento(
                tipo="oportunidade_promovida",
                agente="avaliador_fechamento_comercial",
                area="comercial",
                ref=h.get("oportunidade_id", ""),
                titulo=f"Promovida para {h['acao']}: {h.get('oportunidade_id','?')}",
                descricao=f"Score: {h.get('score',0)} | {h.get('motivo','')[:80]}",
                severidade="sucesso",
                timestamp=h.get("registrado_em", ""),
            ))

    # Entregas abertas
    for e in pipeline_ent:
        if e.get("status_entrega") in ("onboarding", "planejada", "em_execucao"):
            eventos.append(_evento(
                tipo="entrega_aberta",
                agente="agente_operacao_entrega",
                area="entrega",
                ref=e.get("id", ""),
                titulo=f"Entrega aberta: {e.get('contraparte','?')}",
                descricao=f"Linha: {e.get('linha_servico','?')} | Status: {e.get('status_entrega','?')} | {e.get('percentual_conclusao',0)}%",
                severidade="info",
                timestamp=e.get("registrado_em", ""),
            ))

    # Resultados de contato recentes (ultimo 15)
    resultados_ordenados = sorted(
        resultados,
        key=lambda r: r.get("data_resultado", ""),
        reverse=True,
    )[:15]
    for r in resultados_ordenados:
        sev = "sucesso" if r.get("tipo_resultado") in ("pediu_proposta", "respondeu_interesse") else "info"
        eventos.append(_evento(
            tipo="resultado_recebido",
            agente="integrador_canais",
            area="comercial",
            ref=r.get("oportunidade_id", ""),
            titulo=f"Resultado: {r.get('tipo_resultado','?')} — {r.get('contraparte','?')}",
            descricao=r.get("resumo_resultado", "")[:100],
            severidade=sev,
            timestamp=r.get("data_resultado", ""),
        ))

    # Riscos financeiros
    for ri in riscos:
        eventos.append(_evento(
            tipo="risco_financeiro_detectado",
            agente="agente_financeiro",
            area="financeiro",
            ref=ri.get("id", ri.get("tipo", "")),
            titulo=f"Risco financeiro: {ri.get('tipo','?')}",
            descricao=ri.get("descricao", "")[:100],
            severidade=_sev_urgencia(ri.get("urgencia", "")),
            timestamp="",
        ))

    # Histórico de expediente de propostas (últimos 20 eventos)
    try:
        hist_exp_arq = config.PASTA_DADOS / "historico_envios_propostas.json"
        if hist_exp_arq.exists():
            with open(hist_exp_arq, "r", encoding="utf-8") as _f:
                hist_exp = json.load(_f)
            _sev_map_exp = {
                "proposta_aceita": "sucesso", "proposta_recusada": "erro",
                "resposta_cliente_registrada": "sucesso",
                "envio_proposta_enfileirado_email": "info",
                "envio_proposta_marcado_como_enviado": "info",
            }
            for hev in hist_exp[-20:]:
                eventos.append(_evento(
                    tipo=hev.get("evento", "expediente_proposta"),
                    agente="expediente_propostas",
                    area="comercial",
                    ref=hev.get("envio_proposta_id", ""),
                    titulo=hev.get("evento", "?").replace("_", " ").title(),
                    descricao=hev.get("descricao", "")[:120],
                    severidade=_sev_map_exp.get(hev.get("evento", ""), "info"),
                    timestamp=hev.get("registrado_em", ""),
                ))
    except Exception:
        pass

    # Incidentes operacionais recentes
    try:
        incidentes_arq = config.PASTA_DADOS / "incidentes_operacionais.json"
        if incidentes_arq.exists():
            with open(incidentes_arq, "r", encoding="utf-8") as _f:
                incidentes_lista = json.load(_f)
            for inc in incidentes_lista[-20:]:  # últimos 20
                sev_map = {"critica": "critico", "alta": "alto", "media": "medio", "baixa": "info"}
                eventos.append(_evento(
                    tipo="incidente_operacional",
                    agente=inc.get("agente", "orquestrador"),
                    area=inc.get("area", "operacao"),
                    ref=inc.get("id", ""),
                    titulo=f"[{inc.get('severidade','?').upper()}] {inc.get('titulo','incidente')}",
                    descricao=inc.get("descricao", "")[:150],
                    severidade=sev_map.get(inc.get("severidade","baixa"), "info"),
                    timestamp=inc.get("detectado_em", ""),
                ))
    except Exception:
        pass

    # Ordenar por timestamp desc, limitar 100
    eventos_ordenados = sorted(
        [e for e in eventos if e["timestamp"]],
        key=lambda x: x["timestamp"],
        reverse=True,
    )[:100]

    return {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "total":     len(eventos_ordenados),
        "eventos":   eventos_ordenados,
    }


# ─── Metricas empresa ─────────────────────────────────────────────────────────

def gerar_metricas_empresa() -> dict:
    pipeline_com = _ler("pipeline_comercial.json", [])
    pipeline_ent = _ler("pipeline_entrega.json", [])
    handoffs     = _ler("handoffs_agentes.json", [])
    delibs       = _ler("deliberacoes_conselho.json", [])
    followups    = _ler("fila_followups.json", [])
    fila_exec    = _ler("fila_execucao_contato.json", [])
    resultados   = _ler("resultados_contato.json", [])
    insumos      = _ler("insumos_entrega.json", [])
    riscos       = _ler("fila_riscos_financeiros.json", [])
    caixa        = _ler("posicao_caixa.json", {})
    ciclo        = _ler("ciclo_operacional.json", {})

    # Pipeline comercial por estagio
    por_estagio: dict = {}
    por_origem: dict = {}
    for o in pipeline_com:
        e = o.get("estagio", "?")
        por_estagio[e] = por_estagio.get(e, 0) + 1
        orig = o.get("origem_oportunidade", o.get("origem", "?"))
        por_origem[orig] = por_origem.get(orig, 0) + 1

    # Entregas
    por_status_ent: dict = {}
    bloqueadas = 0
    pcts = []
    for ent in pipeline_ent:
        s = ent.get("status_entrega", "?")
        por_status_ent[s] = por_status_ent.get(s, 0) + 1
        if ent.get("bloqueios"):
            bloqueadas += 1
        pct = ent.get("percentual_conclusao")
        if pct is not None:
            pcts.append(pct)

    pct_medio = int(sum(pcts) / len(pcts)) if pcts else 0

    # Ciclo atual
    etapas_ciclo = ciclo.get("etapas", [])
    erros_ciclo  = sum(1 for e in etapas_ciclo if e.get("status") == "erro")

    return {
        "oportunidades_no_pipeline":        len(pipeline_com),
        "oportunidades_por_estagio":        por_estagio,
        "oportunidades_por_origem":         por_origem,
        "followups_pendentes":              sum(1 for f in followups if f.get("status") == "pendente"),
        "execucoes_prontas_para_integracao": sum(1 for e in fila_exec if e.get("pronto_para_integracao")),
        "resultados_recebidos_total":       len(resultados),
        "entregas_abertas":                 sum(1 for e in pipeline_ent if e.get("status_entrega") not in ("concluida", "cancelada")),
        "entregas_bloqueadas":              bloqueadas,
        "entregas_por_status":              por_status_ent,
        "percentual_medio_entrega":         pct_medio,
        "deliberacoes_pendentes":           sum(1 for d in delibs if d.get("status") in ("pendente", "em_analise")),
        "deliberacoes_resolvidas":          sum(1 for d in delibs if d.get("status") == "resolvida"),
        "riscos_financeiros_abertos":       len(riscos),
        "caixa_atual":                      caixa.get("saldo_atual_estimado", 0.0),
        "risco_de_caixa":                   caixa.get("risco_caixa", False),
        "total_handoffs_pendentes":         sum(1 for h in handoffs if h.get("status") == "pendente"),
        "total_handoffs_bloqueados":        sum(1 for h in handoffs if h.get("status") == "bloqueado"),
        "insumos_pendentes":                sum(1 for i in insumos if i.get("status_aplicacao") == "pendente"),
        "etapas_ciclo_atual":               len(etapas_ciclo),
        "erros_ciclo_atual":                erros_ciclo,
        "atualizado_em":                    datetime.now().isoformat(timespec="seconds"),
        # Métricas de propostas (melhor esforço)
        **_metricas_propostas(),
        # Métricas de contas/clientes (melhor esforço)
        **_metricas_contas(),
        # Métricas de acompanhamento pós-entrega (melhor esforço)
        **_metricas_acompanhamento(),
    }


# ─── Metricas por agente ──────────────────────────────────────────────────────

def _metricas_propostas() -> dict:
    """Contagens de propostas por status para métricas da empresa."""
    try:
        from core.propostas_empresa import resumir_para_painel as _rp
        r = _rp()
        return {
            "propostas_total":             r["total"],
            "propostas_rascunho":          r["rascunho"] + r["pronta_para_revisao"],
            "propostas_aguardando_conselho": r["aguardando_conselho"],
            "propostas_aprovadas":         r["aprovadas"],
            "propostas_aceitas":           r["aceitas"],
        }
    except Exception:
        return {}


def _metricas_contas() -> dict:
    """Contagens de contas/clientes para métricas da empresa."""
    try:
        from core.contas_empresa import resumir_para_painel as _rc
        r = _rc()
        return {
            "total_contas":                r["total_contas"],
            "total_clientes_ativos":       r["clientes_ativos"] + r["clientes_em_implantacao"],
            "total_clientes_em_implantacao": r["clientes_em_implantacao"],
            "contas_com_risco":            r["com_risco"],
        }
    except Exception:
        return {}


def _metricas_acompanhamento() -> dict:
    """Contagens de acompanhamento pós-entrega para métricas da empresa."""
    try:
        from core.acompanhamento_contas import resumir_para_painel as _ra
        r = _ra()
        return {
            "acompanhamentos_abertos":          r["acompanhamentos_abertos"],
            "contas_em_risco_acomp":            r["contas_em_risco"],
            "contas_com_potencial_expansao":    r["contas_com_potencial_expansao"],
            "oportunidades_expansao_sugeridas": r["oportunidades_expansao_sugeridas"],
            "oportunidades_expansao_convertidas": r["oportunidades_expansao_convertidas"],
        }
    except Exception:
        return {}


def gerar_metricas_agentes() -> list:
    ciclo   = _ler("ciclo_operacional.json", {})
    estado  = _ler("estado_empresa.json", {})

    # Indexar etapas do ciclo por agente (pegar última execucao)
    ultimas: dict = {}
    for etapa in ciclo.get("etapas", []):
        nome = etapa["nome_agente"]
        ultimas[nome] = etapa  # ultima ocorrencia vence

    resultado = []
    for ag_info in _AGENTES_CONHECIDOS:
        nome  = ag_info["agente"]
        etapa = ultimas.get(nome, {})
        resumo_etapa = etapa.get("resumo", {})

        resultado.append({
            "agente":           nome,
            "area":             ag_info["area"],
            "status":           etapa.get("status", "nao_executado"),
            "ultima_execucao":  etapa.get("finalizado_em", "—"),
            "duracao_ms":       etapa.get("duracao_ms", 0),
            "itens_processados": _extrair_itens_processados(nome, resumo_etapa),
            "pendencias":       _extrair_pendencias(nome, resumo_etapa),
            "bloqueios":        etapa.get("erro", None),
            "erros_recentes":   1 if etapa.get("status") == "erro" else 0,
            "resumo":           _resumo_agente_curto(nome, resumo_etapa),
        })

    return resultado


# ─── Metricas por area ────────────────────────────────────────────────────────

def gerar_metricas_areas() -> dict:
    pipeline_com = _ler("pipeline_comercial.json", [])
    pipeline_ent = _ler("pipeline_entrega.json", [])
    followups    = _ler("fila_followups.json", [])
    riscos       = _ler("fila_riscos_financeiros.json", [])
    caixa        = _ler("posicao_caixa.json", {})
    previsao     = _ler("previsao_caixa.json", {})
    resultados   = _ler("resultados_contato.json", [])
    handoffs     = _ler("handoffs_agentes.json", [])
    ciclo        = _ler("ciclo_operacional.json", {})
    agora        = datetime.now().isoformat(timespec="seconds")

    # Prospecção
    prs_hoffs = [h for h in handoffs if h.get("agente_origem") == "agente_prospeccao"]
    prospeccao = {
        "status":           "ativo",
        "volume":           sum(1 for o in pipeline_com if o.get("origem") == "prospeccao"),
        "gargalos":         [] if prs_hoffs else ["sem handoffs recentes de prospeccao"],
        "itens_criticos":   [h["descricao"][:80] for h in prs_hoffs if h.get("status") == "pendente"][:3],
        "ultima_atualizacao": agora,
    }

    # Marketing
    mkt_opps = [o for o in pipeline_com if "marketing" in o.get("linha_servico_sugerida", "").lower()
                or o.get("origem_oportunidade", "") == "marketing"]
    mkt_hoffs = [h for h in handoffs if h.get("agente_origem") == "agente_marketing"]
    marketing = {
        "status":           "ativo" if mkt_opps else "sem_atividade",
        "volume":           len(mkt_opps),
        "gargalos":         ["sem oportunidades de marketing" ] if not mkt_opps else [],
        "itens_criticos":   [h["descricao"][:80] for h in mkt_hoffs if h.get("status") == "pendente"][:3],
        "ultima_atualizacao": agora,
    }

    # Comercial
    ativos_com    = [o for o in pipeline_com if o.get("estagio") not in ("ganho", "perdido", "encerrado")]
    estagnadas    = [o for o in ativos_com if o.get("dias_sem_atividade", 0) > 10]
    followups_p   = [f for f in followups if f.get("status") == "pendente"]
    comercial = {
        "status":           "ativo" if ativos_com else "sem_atividade",
        "volume":           len(pipeline_com),
        "ativos":           len(ativos_com),
        "ganhos":           sum(1 for o in pipeline_com if o.get("estagio") == "ganho"),
        "perdidos":         sum(1 for o in pipeline_com if o.get("estagio") == "perdido"),
        "estagnadas":       len(estagnadas),
        "followups_pendentes": len(followups_p),
        "por_estagio":      _contar_por_campo(pipeline_com, "estagio"),
        "gargalos":         [f"Oportunidade estagnada >10 dias: {o.get('contraparte','?')}" for o in estagnadas[:3]],
        "itens_criticos":   [o.get("contraparte", "?") for o in sorted(ativos_com, key=lambda x: x.get("dias_sem_atividade", 0), reverse=True)[:3]],
        "ultima_atualizacao": agora,
    }

    # Entrega
    ent_bloqueadas = [e for e in pipeline_ent if e.get("bloqueios")]
    ent_ativas     = [e for e in pipeline_ent if e.get("status_entrega") not in ("concluida", "cancelada")]
    pcts           = [e.get("percentual_conclusao", 0) for e in ent_ativas if e.get("percentual_conclusao") is not None]
    entrega = {
        "status":           "ativo" if ent_ativas else "vazio",
        "volume":           len(pipeline_ent),
        "ativas":           len(ent_ativas),
        "bloqueadas":       len(ent_bloqueadas),
        "concluidas":       sum(1 for e in pipeline_ent if e.get("status_entrega") == "concluida"),
        "pct_medio":        int(sum(pcts) / len(pcts)) if pcts else 0,
        "por_status":       _contar_por_campo(pipeline_ent, "status_entrega"),
        "gargalos":         [f"Entrega bloqueada: {e.get('contraparte','?')} — {e.get('bloqueios',[])[0].get('tipo','?') if e.get('bloqueios') else ''}" for e in ent_bloqueadas[:3]],
        "itens_criticos":   [f"{e.get('contraparte','?')} {e.get('percentual_conclusao',0)}%" for e in sorted(ent_ativas, key=lambda x: x.get("percentual_conclusao", 100))[:3]],
        "ultima_atualizacao": agora,
    }

    # Financeiro
    previsao_7d  = previsao.get("janelas", {}).get("7_dias", {})
    previsao_30d = previsao.get("janelas", {}).get("30_dias", {})
    financeiro = {
        "status":           "risco" if caixa.get("risco_caixa") else "normal",
        "caixa_atual":      caixa.get("saldo_atual_estimado", 0.0),
        "risco_caixa":      caixa.get("risco_caixa", False),
        "saldo_previsto_7d":  previsao_7d.get("saldo_projetado", 0.0),
        "saldo_previsto_30d": previsao_30d.get("saldo_projetado", 0.0),
        "risco_7d":         previsao_7d.get("risco_periodo", False),
        "risco_30d":        previsao_30d.get("risco_periodo", False),
        "riscos_abertos":   len(riscos),
        "a_receber":        caixa.get("total_a_receber_aberto", 0.0),
        "a_pagar":          caixa.get("total_a_pagar_aberto", 0.0),
        "vencido":          caixa.get("total_vencido", 0.0),
        "gargalos":         [r.get("descricao", "")[:80] for r in riscos if r.get("urgencia") in ("imediata", "critica")][:3],
        "itens_criticos":   [r.get("descricao", "")[:80] for r in riscos[:3]],
        "ultima_atualizacao": agora,
    }

    return {
        "prospeccao": prospeccao,
        "marketing":  marketing,
        "comercial":  comercial,
        "entrega":    entrega,
        "financeiro": financeiro,
    }


# ─── Gargalos e deliberacoes ──────────────────────────────────────────────────

def resumir_gargalos_criticos(metricas_emp: dict, metricas_ar: dict) -> list:
    gargalos = []

    if metricas_emp.get("risco_de_caixa"):
        gargalos.append({"area": "financeiro", "descricao": "Risco de caixa detectado", "severidade": "critico"})

    if metricas_emp.get("entregas_bloqueadas", 0) > 0:
        gargalos.append({"area": "entrega", "descricao": f"{metricas_emp['entregas_bloqueadas']} entrega(s) bloqueada(s)", "severidade": "alto"})

    if metricas_emp.get("deliberacoes_pendentes", 0) > 5:
        gargalos.append({"area": "operacao", "descricao": f"{metricas_emp['deliberacoes_pendentes']} deliberacoes pendentes acumuladas", "severidade": "alto"})

    if metricas_emp.get("erros_ciclo_atual", 0) > 0:
        gargalos.append({"area": "operacao", "descricao": f"{metricas_emp['erros_ciclo_atual']} erro(s) no ciclo atual", "severidade": "medio"})

    estagnadas = metricas_ar.get("comercial", {}).get("estagnadas", 0)
    if estagnadas > 0:
        gargalos.append({"area": "comercial", "descricao": f"{estagnadas} oportunidade(s) estagnada(s) > 10 dias", "severidade": "medio"})

    com_g = metricas_ar.get("comercial", {}).get("gargalos", [])
    ent_g = metricas_ar.get("entrega", {}).get("gargalos", [])
    fin_g = metricas_ar.get("financeiro", {}).get("gargalos", [])
    for g in com_g + ent_g + fin_g:
        if g:
            gargalos.append({"area": "operacional", "descricao": g[:100], "severidade": "info"})

    return gargalos[:15]


def resumir_deliberacoes_conselho(delibs: list) -> dict:
    pendentes    = [d for d in delibs if d.get("status") in ("pendente", "em_analise")]
    resolvidas   = [d for d in delibs if d.get("status") == "resolvida"]
    aplicadas    = [d for d in delibs if d.get("status") == "aplicada"]

    return {
        "total":      len(delibs),
        "pendentes":  len(pendentes),
        "resolvidas": len(resolvidas),
        "aplicadas":  len(aplicadas),
        "lista_pendentes": [
            {
                "id":       d.get("id"),
                "titulo":   d.get("titulo", "")[:80],
                "tipo":     d.get("tipo", ""),
                "urgencia": d.get("urgencia", ""),
                "impacto":  d.get("impacto", ""),
                "criado_em": d.get("criado_em", ""),
            }
            for d in sorted(pendentes, key=lambda x: x.get("urgencia", ""), reverse=True)[:10]
        ],
    }


# ─── Auxiliares internos ──────────────────────────────────────────────────────

def _evento(tipo, agente, area, ref, titulo, descricao, severidade, timestamp) -> dict:
    return {
        "id":          f"ev_{tipo}_{ref}_{timestamp}"[:60],
        "tipo_evento": tipo,
        "agente_origem": agente,
        "area":        area,
        "referencia_id": ref,
        "titulo":      titulo[:100],
        "descricao":   descricao[:150],
        "severidade":  severidade,
        "timestamp":   timestamp,
    }


def _resumir_ciclo(ciclo: dict) -> dict:
    if not ciclo:
        return {}
    etapas = ciclo.get("etapas", [])
    return {
        "ciclo_id":       ciclo.get("ciclo_id"),
        "status":         ciclo.get("status_geral"),
        "etapas_ok":      sum(1 for e in etapas if e.get("status") == "ok"),
        "etapas_erro":    sum(1 for e in etapas if e.get("status") == "erro"),
        "duracao_total_ms": sum(e.get("duracao_ms", 0) for e in etapas),
        "iniciado_em":    ciclo.get("iniciado_em"),
        "finalizado_em":  ciclo.get("finalizado_em"),
        "resumo_final":   ciclo.get("resumo_final", {}),
    }


def _extrair_proximas_acoes(delibs, gargalos, riscos) -> list:
    acoes = []
    for d in delibs:
        if d.get("status") in ("pendente", "em_analise") and d.get("urgencia") in ("imediata", "alta", "critica"):
            acoes.append(f"[DELIBERAR] {d.get('titulo','?')[:80]}")
    for g in gargalos:
        if g.get("severidade") in ("critico", "alto"):
            acoes.append(f"[GARGALO] {g['descricao'][:80]}")
    for r in riscos[:3]:
        acoes.append(f"[RISCO] {r.get('descricao','?')[:80]}")
    return acoes[:8]


def _extrair_itens_processados(nome: str, resumo: dict) -> int:
    mapeamento = {
        "agente_financeiro":             resumo.get("total_itens", resumo.get("total_lancamentos", 0)),
        "agente_prospeccao":             resumo.get("candidatas_analisadas", resumo.get("total_analisadas", 0)),
        "agente_marketing":              resumo.get("total_processadas", resumo.get("importadas", 0)),
        "agente_comercial":              resumo.get("pipeline_total", 0),
        "agente_secretario":             resumo.get("handoffs_criados", 0),
        "agente_executor_contato":       resumo.get("preparados", 0),
        "integrador_canais":             resumo.get("resultados_gerados", 0),
        "agente_operacao_entrega":       resumo.get("abertas", resumo.get("pipeline_entrega", 0)),
        "gerador_insumos_desde_contato": resumo.get("insumos_gerados", 0),
        "avaliador_fechamento_comercial": resumo.get("candidatas_avaliadas", 0),
    }
    return mapeamento.get(nome, 0) or 0


def _extrair_pendencias(nome: str, resumo: dict) -> int:
    mapeamento = {
        "agente_secretario":     resumo.get("deliberacoes_criadas", 0),
        "agente_executor_contato": resumo.get("preparados", 0),
        "agente_operacao_entrega": resumo.get("insumos_aplicados", 0),
    }
    return mapeamento.get(nome, 0) or 0


def _resumo_agente_curto(nome: str, resumo: dict) -> str:
    if not resumo:
        return "sem execucao neste ciclo"
    partes = []
    for k, v in list(resumo.items())[:4]:
        if isinstance(v, (int, float, bool, str)) and k != "agente":
            partes.append(f"{k}={v}")
    return " | ".join(partes)[:120]


def _area_do_agente(nome: str) -> str:
    for ag in _AGENTES_CONHECIDOS:
        if ag["agente"] == nome:
            return ag["area"]
    return "operacao"


def _sev_deliberacao(urgencia: str) -> str:
    return {"imediata": "critico", "alta": "alto", "media": "medio"}.get(urgencia, "info")


def _sev_urgencia(urgencia: str) -> str:
    return {"imediata": "critico", "critica": "critico", "curto_prazo": "alto"}.get(urgencia, "info")


def _contar_por_campo(itens: list, campo: str) -> dict:
    resultado: dict = {}
    for item in itens:
        v = item.get(campo, "?")
        resultado[v] = resultado.get(v, 0) + 1
    return resultado


def _ler(nome: str, padrao):
    caminho = config.PASTA_DADOS / nome
    if not caminho.exists():
        return padrao
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return padrao


def _salvar(nome: str, dados) -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = config.PASTA_DADOS / nome
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
