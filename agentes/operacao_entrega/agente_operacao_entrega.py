"""
agentes/operacao_entrega/agente_operacao_entrega.py

Consome oportunidades ganhas/aprovadas do pipeline comercial.
Abre operacoes de entrega, cria checklist por linha de servico,
registra estado e escala excecoes ao conselho.
Nao executa alteracoes externas reais.

Entradas:
  dados/pipeline_comercial.json
  dados/handoffs_agentes.json
  dados/deliberacoes_conselho.json

Saidas:
  dados/pipeline_entrega.json
  dados/checklists_entrega.json
  dados/historico_entrega.json
  dados/estado_agente_operacao_entrega.json
  logs/agentes/agente_operacao_entrega_{ts}.log
"""

import hashlib
import json
import logging
from datetime import datetime

import config
from core.controle_agente import (
    carregar_estado,
    salvar_estado,
    marcar_processado,
    registrar_execucao,
    configurar_log_agente,
)
from core.deliberacoes import (
    criar_ou_atualizar_deliberacao,
    carregar_deliberacoes,
)
from modulos.entrega.processador_insumos_entrega import (
    carregar_insumos_pendentes,
    aplicar_insumo_na_entrega,
    atualizar_pipeline_entrega_por_checklist,
    marcar_insumo_como_aplicado,
)

NOME_AGENTE = "agente_operacao_entrega"

_ESTAGIOS_APTOS = {"ganho"}
_STATUS_APTOS   = {"onboarding", "aprovado", "pronto_para_implantacao", "pronto_para_entrega"}

# ─── Mapa executor: tipo → configuração ───────────────────────────────────────
# Cada chave é o identificador usado em etapas_execucao[].tipo
MAPA_EXECUTORES: dict[str, dict] = {
    "google_business.criar_perfil": {
        "titulo":            "Criar/atualizar Google Meu Negócio",
        "requer_formulario": "presenca_digital",
        "automatico":        True,
    },
    "google_calendar.criar_agenda": {
        "titulo":            "Criar Google Agenda compartilhada",
        "requer_formulario": "agendamento_digital",
        "automatico":        True,
    },
    "n8n.construir_bot_atendimento": {
        "titulo":            "Configurar bot de atendimento WhatsApp",
        "requer_formulario": "atendimento_whatsapp",
        "automatico":        True,
    },
    "n8n.construir_bot_agendamento": {
        "titulo":            "Configurar bot de agendamento",
        "requer_formulario": "agendamento_digital",
        "automatico":        True,
    },
    "n8n.construir_lembrete": {
        "titulo":            "Configurar lembretes automáticos",
        "requer_formulario": "agendamento_digital",
        "automatico":        True,
    },
    "auto_teste.testar_cenarios": {
        "titulo":            "Testar fluxo completo",
        "requer_formulario": None,
        "automatico":        True,
    },
    "gerar_material_treinamento": {
        "titulo":            "Gerar material de treinamento",
        "requer_formulario": None,
        "automatico":        True,
    },
    "enviar_entrega_cliente": {
        "titulo":            "Entregar e validar com o cliente",
        "requer_formulario": None,
        "automatico":        True,
    },
}


# ─── Ponto de entrada ─────────────────────────────────────────────────────────

def executar() -> dict:
    log, caminho_log = configurar_log_agente(NOME_AGENTE)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")

    log.info("=" * 60)
    log.info(f"AGENTE OPERACAO ENTREGA — inicio {ts}")
    log.info("=" * 60)

    estado = carregar_estado(NOME_AGENTE)

    # ── ETAPA 1: Carregar entradas ─────────────────────────────────────────
    entradas = carregar_entradas_entrega(log)

    # ── ETAPA 2: Detectar oportunidades prontas para entrega ───────────────
    aptas = detectar_oportunidades_prontas_para_entrega(entradas["pipeline"])
    log.info(f"  Oportunidades aptas para entrega: {len(aptas)}")

    # ── ETAPA 3: Processar entregas ────────────────────────────────────────
    pipeline_entrega = entradas["pipeline_entrega"]
    checklists       = entradas["checklists"]
    historico        = entradas["historico"]
    todas_delib      = entradas["deliberacoes"]
    handoffs         = entradas["handoffs"]
    insumos          = entradas["insumos"]

    n_abertas      = 0
    n_atualizadas  = 0
    n_checklists   = 0
    n_bloqueadas   = 0
    n_delib        = 0
    n_insumos_aplic = 0

    for opp in aptas:
        opp_id      = opp.get("id", "")
        entrega_key = f"entrega_{opp_id}"

        # Garantir conta_id na opp (cria/encontra conta se não tiver)
        _conta_id = opp.get("conta_id", "")
        if not _conta_id:
            try:
                from core.contas_empresa import encontrar_ou_criar_conta, vincular_oportunidade_a_conta
                _ct = encontrar_ou_criar_conta({
                    "nome_empresa":       opp.get("contraparte", ""),
                    "email_principal":    opp.get("email", ""),
                    "telefone_principal": opp.get("telefone", ""),
                    "whatsapp":           opp.get("whatsapp", ""),
                    "cidade":             opp.get("cidade", ""),
                    "categoria":          opp.get("categoria", ""),
                    "origem_inicial":     opp.get("origem_oportunidade", ""),
                }, origem="agente_operacao_entrega")
                if _ct:
                    opp["conta_id"] = _ct["id"]
                    _conta_id = _ct["id"]
                    vincular_oportunidade_a_conta(opp_id, _conta_id,
                                                  origem="agente_operacao_entrega")
            except Exception as _exc_cnt:
                log.debug(f"  [contas] conta nao associada para {opp_id}: {_exc_cnt}")

        entrega, criada = abrir_ou_atualizar_entrega(opp, pipeline_entrega, log)

        # Propagar conta_id para a entrega e vincular
        if _conta_id:
            entrega["conta_id"] = _conta_id
            try:
                from core.contas_empresa import vincular_entrega_a_conta
                vincular_entrega_a_conta(entrega["id"], _conta_id,
                                         origem="agente_operacao_entrega")
            except Exception:
                pass

        if criada:
            n_abertas += 1
            registrar_historico_entrega(
                entrega["id"], "entrega_aberta",
                f"Entrega aberta para {opp.get('contraparte', '?')} — origem: {opp.get('estagio')}",
                historico,
            )
        else:
            n_atualizadas += 1

        # Checklist: criar se ainda nao existe para esta entrega
        sem_checklist = not any(c.get("entrega_id") == entrega["id"] for c in checklists)
        if sem_checklist:
            # Preferir proposta aprovada/aceita como origem do escopo
            _prop_aprovada = None
            try:
                from core.propostas_empresa import carregar_propostas
                _props = carregar_propostas()
                # Preferir aceita ou aceite_verbal; enviada+aprovada só se sem aceite
                _prop_aceita = next(
                    (p for p in _props
                     if p.get("oportunidade_id") == opp.get("id", "")
                     and p.get("status") == "aceita"),
                    None,
                )
                _prop_aprovada = _prop_aceita or next(
                    (p for p in _props
                     if p.get("oportunidade_id") == opp.get("id", "")
                     and p.get("status") in {"enviada", "aprovada_para_envio", "preparada_para_envio"}),
                    None,
                )
            except Exception:
                pass

            if _prop_aprovada:
                entrega["proposta_id"]     = _prop_aprovada["id"]
                entrega["proposta_status"] = _prop_aprovada["status"]
                entrega["origem_escopo"]   = "proposta_aprovada"
                _oferta_id = _prop_aprovada.get("oferta_id", "") or opp.get("oferta_id", "")
                _pacote_id = _prop_aprovada.get("pacote_id", "") or opp.get("pacote_id", "")
            else:
                entrega["origem_escopo"] = "oferta_catalogo"
                _oferta_id = opp.get("oferta_id", "")
                _pacote_id = opp.get("pacote_id", "")

            _contexto_cliente = _extrair_contexto_digital(opp)
            checklist = criar_checklist_inicial_por_linha_servico(
                entrega["id"],
                opp.get("linha_servico_sugerida", ""),
                oferta_id=_oferta_id,
                pacote_id=_pacote_id,
                contexto_cliente=_contexto_cliente,
            )
            if _prop_aprovada:
                checklist["proposta_id"]   = _prop_aprovada["id"]
                checklist["origem_escopo"] = "proposta_aprovada"
            checklists.append(checklist)
            entrega["checklist_id"] = checklist["id"]
            n_checklists += 1
            registrar_historico_entrega(
                entrega["id"], "checklist_criado",
                f"Checklist '{checklist['id']}' criado — linha: {checklist['linha_servico']} "
                f"({len(checklist['itens'])} itens)",
                historico,
            )
            log.info(
                f"  [checklist] {checklist['id']} | {checklist['linha_servico']} "
                f"| {len(checklist['itens'])} itens"
            )

        # Bloqueios
        bloqueios = detectar_bloqueios_entrega(opp, entrega)
        if bloqueios:
            entrega["bloqueios"] = bloqueios
            if entrega["status_entrega"] in ("nova", "onboarding"):
                entrega["status_entrega"] = "aguardando_insumo"
            if criada:  # só registra eventos de bloqueio na abertura
                n_bloqueadas += 1
                for b in bloqueios:
                    registrar_historico_entrega(
                        entrega["id"], "item_bloqueado",
                        f"Bloqueio [{b['tipo']}]: {b['descricao']}",
                        historico,
                    )
                log.info(f"  [bloqueio] {entrega['id']} — {len(bloqueios)} bloqueio(s)")
        elif entrega["status_entrega"] == "nova":
            entrega["status_entrega"] = "onboarding"
            if criada:
                registrar_historico_entrega(
                    entrega["id"], "onboarding_iniciado",
                    f"Onboarding iniciado para {opp.get('contraparte', '?')}",
                    historico,
                )

        # Handoff comercial → operacao_entrega
        criar_handoff_entrega_se_necessario(entrega, opp, handoffs, log)

        # Deliberacao se necessario
        if criar_deliberacao_entrega_se_necessario(opp, entrega, todas_delib, log):
            n_delib += 1
            registrar_historico_entrega(
                entrega["id"], "deliberacao_entrega_criada",
                f"Deliberacao aberta para {opp.get('contraparte', '?')} — escopo ambiguo ou risco detectado",
                historico,
            )

        marcar_processado(estado, entrega_key)

    # ── ETAPA 3b: Processar insumos pendentes ──────────────────────────────
    pendentes = carregar_insumos_pendentes(insumos)
    log.info(f"  Insumos pendentes para processar: {len(pendentes)}")

    for insumo in pendentes:
        entrega_id  = insumo.get("entrega_id", "")
        opp_id_ins  = insumo.get("oportunidade_id", "")

        # Buscar entrega por entrega_id; fallback por oportunidade_id
        entrega = next((e for e in pipeline_entrega if e["id"] == entrega_id), None)
        if not entrega and opp_id_ins:
            entrega = next((e for e in pipeline_entrega if e.get("oportunidade_id") == opp_id_ins), None)
            if entrega:
                insumo["entrega_id"] = entrega["id"]  # vincular para rastreabilidade

        entrega_id = entrega["id"] if entrega else entrega_id
        checklist  = next((c for c in checklists if c.get("entrega_id") == entrega_id), None)

        if not entrega or not checklist:
            log.info(f"  [insumo ignorado] {insumo.get('id')} — entrega/checklist nao encontrado")
            marcar_insumo_como_aplicado(insumo, False)
            continue

        log.info(f"  [insumo] {insumo.get('tipo_insumo')} → {entrega_id}")
        mudou = aplicar_insumo_na_entrega(insumo, entrega, checklist, historico, log)
        marcar_insumo_como_aplicado(insumo, mudou)

        # Recalcular status_entrega com base no checklist atualizado
        status_mudou = atualizar_pipeline_entrega_por_checklist(entrega, checklist, log)
        if status_mudou:
            historico.append({
                "id":            f"hev_{entrega_id}_transicao_{len(historico)}",
                "entrega_id":    entrega_id,
                "evento":        "status_entrega_atualizado",
                "descricao":     f"Status atualizado para '{entrega['status_entrega']}' — {entrega.get('percentual_conclusao', 0)}% concluido",
                "origem":        NOME_AGENTE,
                "registrado_em": datetime.now().isoformat(timespec="seconds"),
            })

        if mudou:
            n_insumos_aplic += 1

    # ── ETAPA 3c: Acompanhamento pós-entrega e saúde de conta ─────────────
    n_acomp_criados = 0
    n_expansoes_sug = 0
    try:
        from core.acompanhamento_contas import processar_acompanhamentos_entrega
        _res_acomp = processar_acompanhamentos_entrega(pipeline_entrega,
                                                        origem=NOME_AGENTE)
        n_acomp_criados = _res_acomp.get("criados", 0)
        n_expansoes_sug = _res_acomp.get("expansoes_sugeridas", 0)
        if n_acomp_criados or n_expansoes_sug:
            log.info(
                f"  [acompanhamento] {n_acomp_criados} criado(s) | "
                f"{_res_acomp.get('saudes_recalculadas',0)} saúde(s) | "
                f"{n_expansoes_sug} expansão(ões) sugerida(s)"
            )
    except Exception as _exc_acomp:
        log.warning(f"  [acompanhamento] processamento parcial: {_exc_acomp}")

    # ── ETAPA 3d: Refletir status de entrega nos contratos ─────────────────
    try:
        from modulos.financeiro.reconciliador_contratos_faturamento import (
            atualizar_contrato_por_entrega
        )
        for ent in pipeline_entrega:
            _st_ent = ent.get("status_entrega", "")
            if _st_ent in ("concluida", "aguardando_insumo", "em_execucao", "onboarding"):
                atualizar_contrato_por_entrega(
                    entrega_id=ent.get("id", ""),
                    status_entrega=_st_ent,
                    conta_id=ent.get("conta_id", ""),
                    oportunidade_id=ent.get("oportunidade_id", ""),
                    origem=NOME_AGENTE,
                )
    except Exception as _exc_ct:
        log.debug(f"  [contratos] atualizacao operacional ignorada: {_exc_ct}")

    # ── ETAPA 3e: Gerar resumos de onboarding para entregas abertas ──────────
    n_docs_entrega = 0
    try:
        from core.documentos_empresa import gerar_documento_resumo_entrega, obter_ultima_versao_documento, _checksum, detectar_documento_obsoleto
        _STATUS_GERAR = ("onboarding", "em_execucao", "em_andamento", "aguardando_insumo", "concluida")
        for ent in pipeline_entrega:
            _st = ent.get("status_entrega", ent.get("status", ""))
            if _st not in _STATUS_GERAR:
                continue
            _eid = ent.get("id", "")
            if not _eid:
                continue
            _chk = _checksum(ent)
            if detectar_documento_obsoleto(_eid, "resumo_entrega", _chk) \
                    or not obter_ultima_versao_documento(_eid, "resumo_entrega"):
                _doc = gerar_documento_resumo_entrega(_eid, origem=NOME_AGENTE)
                if _doc:
                    n_docs_entrega += 1
    except Exception as _exc_doc:
        log.debug(f"  [documentos] geracao resumo entrega ignorada: {_exc_doc}")

    # ── ETAPA 3f: Executar etapas automáticas ──────────────────────────────
    n_etapas_exec       = 0
    n_lembretes_form    = 0
    n_entregas_concluidas = 0
    try:
        _res_exec = _executar_etapas_automaticas(pipeline_entrega, historico, log)
        n_etapas_exec         = _res_exec.get("etapas_executadas", 0)
        n_lembretes_form       = _res_exec.get("lembretes_enviados", 0)
        n_entregas_concluidas = _res_exec.get("entregas_concluidas", 0)
        if n_etapas_exec or n_lembretes_form or n_entregas_concluidas:
            log.info(
                f"  [execucao] {n_etapas_exec} etapa(s) | "
                f"{n_lembretes_form} lembrete(s) | "
                f"{n_entregas_concluidas} entrega(s) concluída(s)"
            )
    except Exception as _exc_exec:
        log.warning(f"  [execucao_etapas] parcial: {_exc_exec}")

    # ── ETAPA 4: Persistir ─────────────────────────────────────────────────
    _salvar_json("pipeline_comercial.json", pipeline)   # persiste conta_id adicionado às opps
    _salvar_json("pipeline_entrega.json",   pipeline_entrega)
    _salvar_json("checklists_entrega.json", checklists)
    _salvar_json("historico_entrega.json",  historico)
    _salvar_json("handoffs_agentes.json",   handoffs)
    _salvar_json("insumos_entrega.json",    insumos)

    # ── ETAPA 5: Salvar estado ─────────────────────────────────────────────
    resumo_str = (
        f"aptas={len(aptas)} abertas={n_abertas} atualizadas={n_atualizadas} "
        f"checklists={n_checklists} bloqueadas={n_bloqueadas} "
        f"insumos_aplicados={n_insumos_aplic} deliberacoes={n_delib} "
        f"etapas_exec={n_etapas_exec} concluidas={n_entregas_concluidas}"
    )
    hash_exec = hashlib.md5(resumo_str.encode()).hexdigest()[:16]
    registrar_execucao(
        estado,
        saldo=0.0,
        resumo=resumo_str,
        n_escalados=n_delib,
        n_autonomos=n_abertas + n_atualizadas + n_insumos_aplic,
        hash_exec=hash_exec,
    )
    salvar_estado(NOME_AGENTE, estado)

    # ── ETAPA 6: Log final ─────────────────────────────────────────────────
    log.info("=" * 60)
    log.info(f"AGENTE OPERACAO ENTREGA — concluido")
    log.info(f"  aptas para entrega   : {len(aptas)}")
    log.info(f"  entregas abertas     : {n_abertas}")
    log.info(f"  entregas atualizadas : {n_atualizadas}")
    log.info(f"  checklists criados   : {n_checklists}")
    log.info(f"  entregas bloqueadas  : {n_bloqueadas}")
    log.info(f"  insumos aplicados    : {n_insumos_aplic} / {len(pendentes)}")
    log.info(f"  deliberacoes criadas : {n_delib}")
    log.info(f"  etapas exec          : {n_etapas_exec}")
    log.info(f"  entregas concluidas  : {n_entregas_concluidas}")
    log.info("=" * 60)

    return {
        "agente":               NOME_AGENTE,
        "timestamp":            ts,
        "aptas":                len(aptas),
        "abertas":              n_abertas,
        "atualizadas":          n_atualizadas,
        "checklists_criados":   n_checklists,
        "bloqueadas":           n_bloqueadas,
        "insumos_aplicados":    n_insumos_aplic,
        "deliberacoes":         n_delib,
        "acompanhamentos_criados": n_acomp_criados,
        "expansoes_sugeridas":  n_expansoes_sug,
        "documentos_entrega_gerados": n_docs_entrega,
        "etapas_exec":          n_etapas_exec,
        "lembretes_formulario": n_lembretes_form,
        "entregas_concluidas":  n_entregas_concluidas,
        "pipeline_entrega":     len(pipeline_entrega),
        "caminho_log":          str(caminho_log),
    }


# ─── Carregamento ─────────────────────────────────────────────────────────────

def carregar_entradas_entrega(log) -> dict:
    pipeline         = _carregar_json("pipeline_comercial.json",  padrao=[])
    pipeline_entrega = _carregar_json("pipeline_entrega.json",    padrao=[])
    checklists       = _carregar_json("checklists_entrega.json",  padrao=[])
    historico        = _carregar_json("historico_entrega.json",   padrao=[])
    handoffs         = _carregar_json("handoffs_agentes.json",    padrao=[])
    insumos          = _carregar_json("insumos_entrega.json",     padrao=[])
    deliberacoes     = carregar_deliberacoes()
    log.info(
        f"Entradas: pipeline={len(pipeline)} | entregas={len(pipeline_entrega)} | "
        f"checklists={len(checklists)} | insumos={len(insumos)} | handoffs={len(handoffs)}"
    )
    return {
        "pipeline":         pipeline,
        "pipeline_entrega": pipeline_entrega,
        "checklists":       checklists,
        "historico":        historico,
        "handoffs":         handoffs,
        "insumos":          insumos,
        "deliberacoes":     deliberacoes,
    }


# ─── Detecção ─────────────────────────────────────────────────────────────────

def detectar_oportunidades_prontas_para_entrega(pipeline: list) -> list:
    """
    Identifica oportunidades aptas para entrega:
      - estagio == "ganho"
      - OU status_operacional in {onboarding, aprovado, pronto_para_implantacao}
    """
    return [
        opp for opp in pipeline
        if opp.get("estagio") in _ESTAGIOS_APTOS
        or opp.get("status_operacional") in _STATUS_APTOS
    ]


# ─── Entrega ──────────────────────────────────────────────────────────────────

def abrir_ou_atualizar_entrega(opp: dict, pipeline_entrega: list, log) -> tuple:
    """
    Abre nova entrega ou atualiza existente (dedup por oportunidade_id).
    Retorna (entrega_dict, criada: bool). Modifica pipeline_entrega in-place.
    """
    opp_id = opp.get("id", "")
    agora  = datetime.now().isoformat(timespec="seconds")

    existente = next((e for e in pipeline_entrega if e.get("oportunidade_id") == opp_id), None)
    if existente:
        existente["atualizado_em"] = agora
        log.info(f"  [entrega atualizada] {existente['id']} | {opp.get('contraparte', '?')[:40]}")
        return existente, False

    linha = opp.get("linha_servico_sugerida", "") or "nao_definida"
    entrega = {
        "id":               f"ent_{opp_id}",
        "oportunidade_id":  opp_id,
        "contraparte":      opp.get("contraparte", "?"),
        "linha_servico":    linha,
        "tipo_entrega":     _tipo_entrega_por_linha(linha),
        "status_entrega":   "nova",
        "prioridade":       opp.get("prioridade", "media"),
        "etapa_atual":      "onboarding",
        "checklist_id":     None,
        "bloqueios":        [],
        "depende_de":       None,
        "origem_comercial": opp.get("estagio", ""),
        "contato_principal": opp.get("contato_principal", ""),
        "valor_estimado":   opp.get("valor_estimado"),
        "cidade":           opp.get("cidade", ""),
        "registrado_em":    agora,
        "atualizado_em":    agora,
    }
    pipeline_entrega.append(entrega)
    log.info(f"  [entrega nova] {entrega['id']} | {opp.get('contraparte', '?')[:40]} | {linha}")
    return entrega, True


def _tipo_entrega_por_linha(linha: str) -> str:
    return {
        "marketing_presenca_digital": "implantacao_presenca_digital",
        "comercial_base":             "onboarding_comercial",
    }.get(linha, "entrega_padrao")


# ─── Checklist ────────────────────────────────────────────────────────────────

def criar_checklist_inicial_por_linha_servico(
    entrega_id: str,
    linha: str,
    oferta_id: str = "",
    pacote_id: str = "",
    contexto_cliente: dict | None = None,
) -> dict:
    """Cria checklist inicial. Prefere plano de execução da oferta; cai para checklist por linha."""
    agora = datetime.now().isoformat(timespec="seconds")
    itens = []
    if oferta_id:
        itens = _itens_checklist_por_oferta_pacote(oferta_id, pacote_id,
                                                    contexto_cliente=contexto_cliente)
    if not itens:
        itens = _itens_checklist_por_linha(linha)
    return {
        "id":            f"ck_{entrega_id}",
        "entrega_id":    entrega_id,
        "linha_servico": linha or "nao_definida",
        "oferta_id":     oferta_id or None,
        "pacote_id":     pacote_id or None,
        "itens":         itens,
        "status":        "pendente",
        "registrado_em": agora,
        "atualizado_em": agora,
    }


def _itens_checklist_por_oferta_pacote(
    oferta_id: str,
    pacote_id: str,
    contexto_cliente: dict | None = None,
) -> list:
    """
    Retorna itens de checklist enriquecidos a partir do plano de execução da oferta.
    Fallback: itens simples do catálogo de ofertas.
    """
    # 1. Tentar plano de execução concreto
    try:
        from core.planos_entrega import etapas_para_itens_checklist
        itens = etapas_para_itens_checklist(
            oferta_id,
            contexto_cliente=contexto_cliente,
            usar_llm=True,
        )
        if itens:
            return itens
    except Exception as exc:
        logging.getLogger(__name__).debug(
            f"[checklist] plano_execucao falhou para {oferta_id}: {exc}"
        )

    # 2. Fallback: checklist simples do catálogo de ofertas
    try:
        from core.ofertas_empresa import obter_checklist_por_oferta_e_pacote
        itens_raw = obter_checklist_por_oferta_e_pacote(oferta_id, pacote_id)
        agora = datetime.now().isoformat(timespec="seconds")
        return [
            {
                "id":            f"ck_of_{i}",
                "titulo":        item if isinstance(item, str) else item.get("item", str(item)),
                "descricao":     "",
                "obrigatorio":   True,
                "status":        "pendente",
                "depende_de":    None,
                "criado_em":     agora,
                "atualizado_em": agora,
            }
            for i, item in enumerate(itens_raw)
        ]
    except Exception:
        return []


def _itens_checklist_por_linha(linha: str) -> list:
    if linha == "marketing_presenca_digital":
        return [
            _item("ck_ativo_digital",       "Confirmar ativo digital principal",
                  "Identificar se tem site, Google Business, Instagram ou outro canal ativo."),
            _item("ck_canais_existentes",    "Confirmar canais existentes",
                  "Listar todos os canais digitais ativos (WhatsApp, redes sociais, site)."),
            _item("ck_objetivo_prioritario", "Confirmar objetivo prioritario",
                  "Validar o que o cliente quer resolver: mais leads, atendimento, visibilidade."),
            _item("ck_escopo_inicial",       "Validar escopo inicial",
                  "Confirmar escopo acordado comercialmente vs. capacidade de entrega."),
            _item("ck_plano_implantacao",    "Preparar plano de implantacao",
                  "Montar plano de implantacao com etapas e responsabilidades.",
                  depende_de="ck_escopo_inicial"),
        ]
    elif linha == "comercial_base":
        return [
            _item("ck_contato_principal",   "Confirmar contato principal",
                  "Validar nome, telefone e melhor horario de contato."),
            _item("ck_expectativa",         "Confirmar expectativa de entrega",
                  "Alinhar o que sera entregue e em qual prazo."),
            _item("ck_escopo_basico",       "Validar escopo basico",
                  "Confirmar que o escopo acordado e factivel."),
            _item("ck_kick_off",            "Agendar kick-off",
                  "Marcar reuniao ou ligacao de inicio formal.",
                  obrigatorio=False, depende_de="ck_escopo_basico"),
        ]
    else:
        return [
            _item("ck_contato_responsavel", "Confirmar contato responsavel",
                  "Identificar quem representa o cliente nesta entrega."),
            _item("ck_escopo_servico",      "Validar escopo do servico",
                  "Garantir clareza do servico a entregar para ambos os lados."),
            _item("ck_prazo_inicio",        "Definir prazo de inicio",
                  "Acordar data de inicio da implantacao."),
            _item("ck_revisao_inicial",     "Agendar revisao inicial",
                  "Marcar revisao pos-onboarding em 7 ou 14 dias.",
                  obrigatorio=False),
        ]


def _item(id_sufixo, titulo, descricao, obrigatorio=True, depende_de=None) -> dict:
    agora = datetime.now().isoformat(timespec="seconds")
    return {
        "id":                  id_sufixo,
        "titulo":              titulo,
        "descricao":           descricao,
        "obrigatorio":         obrigatorio,
        "status":              "pendente",
        "depende_de":          depende_de,
        "observacoes":         "",
        "criterios_conclusao": f"Insumo do tipo correspondente registrado e validado.",
        "evidencias":          [],
        "atualizado_em":       agora,
    }


# ─── Bloqueios ────────────────────────────────────────────────────────────────

def detectar_bloqueios_entrega(opp: dict, entrega: dict) -> list:
    """
    Detecta bloqueios objetivos que impedem inicio ou avanco da entrega.
    """
    bloqueios = []

    if not opp.get("contato_principal"):
        bloqueios.append({
            "tipo":      "sem_contato_principal",
            "descricao": "Contato principal nao registrado — necessario para iniciar onboarding.",
            "gravidade": "alta",
        })

    if opp.get("valor_estimado") is None:
        bloqueios.append({
            "tipo":      "valor_nao_definido",
            "descricao": "Valor estimado ausente — confirmar antes de iniciar entrega.",
            "gravidade": "media",
        })

    if (opp.get("linha_servico_sugerida") == "marketing_presenca_digital"
            and not opp.get("contexto_origem")):
        bloqueios.append({
            "tipo":      "sem_contexto_digital",
            "descricao": "Contexto de presenca digital ausente — necessario para plano de implantacao.",
            "gravidade": "media",
        })

    return bloqueios


# ─── Handoff ──────────────────────────────────────────────────────────────────

def criar_handoff_entrega_se_necessario(entrega: dict, opp: dict, handoffs: list, log) -> bool:
    """
    Cria handoff agente_comercial → agente_operacao_entrega se nao existir.
    Retorna True se criou novo.
    """
    ref_id = f"hf_entrega_{entrega['id']}"
    if any(h.get("id") == ref_id for h in handoffs):
        return False

    agora = datetime.now().isoformat(timespec="seconds")
    handoffs.append({
        "id":             ref_id,
        "agente_origem":  "agente_comercial",
        "agente_destino": "agente_operacao_entrega",
        "tipo_handoff":   "entrega_onboarding",
        "referencia_id":  entrega["id"],
        "descricao":      f"{opp.get('contraparte', '?')[:60]} — {entrega['tipo_entrega']}",
        "prioridade":     entrega.get("prioridade", "media"),
        "status":         "em_execucao",
        "depende_de":     None,
        "registrado_em":  agora,
        "atualizado_em":  agora,
    })
    log.info(f"  [handoff] {ref_id} | comercial → operacao_entrega")
    return True


# ─── Deliberação ──────────────────────────────────────────────────────────────

def criar_deliberacao_entrega_se_necessario(opp: dict, entrega: dict, deliberacoes: list, log) -> bool:
    """
    Escala ao conselho quando ha ambiguidade de escopo ou risco relevante.
    Nao cria duplicata para o mesmo entrega_id.
    """
    entrega_id = entrega["id"]
    delib_id   = f"delib_risco_entrega_{entrega_id}"
    for d in deliberacoes:
        if d.get("id") == delib_id and d.get("status") in ("pendente", "em_analise"):
            return False

    motivo = None

    if not opp.get("contato_principal") and opp.get("valor_estimado") is None:
        motivo = (
            f"Entrega iniciada sem contato principal nem valor definido para "
            f"'{opp.get('contraparte', '?')}' — escopo ambiguo para onboarding."
        )
    elif (opp.get("linha_servico_sugerida") == "marketing_presenca_digital"
          and not opp.get("contexto_origem")
          and opp.get("valor_estimado") is None):
        motivo = (
            f"Entrega de presenca digital sem contexto nem valor — "
            f"risco de implantar fora do escopo para '{opp.get('contraparte', '?')}'."
        )

    if not motivo:
        return False

    criar_ou_atualizar_deliberacao({
        "item_id":       f"risco_entrega_{entrega_id}",
        "tipo":          "risco_entrega",
        "urgencia":      "alta",
        "contraparte":   opp.get("contraparte", "?"),
        "descricao":     motivo,
        "referencias":   [entrega_id],
        "linha_servico": opp.get("linha_servico_sugerida", ""),
    })
    log.info(f"  [deliberacao] risco_entrega | {opp.get('contraparte', '?')[:40]}")
    return True


# ─── Histórico ────────────────────────────────────────────────────────────────

def registrar_historico_entrega(entrega_id: str, evento: str, descricao: str, historico: list) -> None:
    """Adiciona evento ao historico de entrega (in-place)."""
    historico.append({
        "id":            f"hev_{entrega_id}_{evento}_{len(historico)}",
        "entrega_id":    entrega_id,
        "evento":        evento,
        "descricao":     descricao,
        "origem":        NOME_AGENTE,
        "registrado_em": datetime.now().isoformat(timespec="seconds"),
    })


# ─── Contexto do cliente ──────────────────────────────────────────────────────

def _extrair_contexto_digital(opp: dict) -> dict:
    """
    Extrai sinais digitais da oportunidade para uso na adaptação do plano
    de execução (ex: pular etapas de configuração já cumpridas).

    Lê de `opp.get("sinais_digitais")` ou `opp.get("sinais")`, que são
    dicts populados pelo agente de prospecção ao analisar a empresa.
    """
    sinais = opp.get("sinais_digitais") or opp.get("sinais") or {}
    return {
        "tem_whatsapp_business": bool(sinais.get("tem_whatsapp_business")
                                      or sinais.get("whatsapp_business")),
        "tem_google_meu_negocio": bool(sinais.get("tem_google_meu_negocio")
                                       or sinais.get("google_meu_negocio")
                                       or sinais.get("tem_google")),
        "tem_site":               bool(sinais.get("tem_site") or sinais.get("site")),
        "tem_instagram":          bool(sinais.get("tem_instagram") or sinais.get("instagram")),
        "nome_empresa":           opp.get("contraparte", ""),
        "categoria":              opp.get("categoria", ""),
    }


# ─── Persistência ─────────────────────────────────────────────────────────────

def _carregar_json(nome: str, padrao):
    caminho = config.PASTA_DADOS / nome
    if not caminho.exists():
        return padrao
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def _salvar_json(nome: str, dados) -> None:
    import os
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = config.PASTA_DADOS / nome
    conteudo = json.dumps(dados, ensure_ascii=False, indent=2)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)
    logging.getLogger(__name__).info(
        f"Salvo: {caminho} ({len(dados) if isinstance(dados, list) else 1} registro(s))"
    )


# ─── Motor de execução autônoma ───────────────────────────────────────────────

def _executar_etapas_automaticas(
    pipeline_entrega: list,
    historico: list,
    log,
) -> dict:
    """
    Para cada entrega em andamento:
      1. Inicializa etapas de execução se ainda não existirem
      2. Verifica formulários necessários (dados mínimos para executar)
      3. Executa próxima etapa pendente via executor mapeado
      4. Marca concluída quando todas as etapas OK
      5. Ao concluir: abre CS + programa NPS
    """
    n_etapas    = 0
    n_lembretes = 0
    n_concluidas = 0
    agora = datetime.now().isoformat(timespec="seconds")

    pipeline = _carregar_json("pipeline_comercial.json", padrao=[])
    opp_por_id = {o.get("id", ""): o for o in pipeline}

    for entrega in pipeline_entrega:
        status = entrega.get("status_entrega", "")
        if status in ("concluida", "cancelada"):
            continue

        opp_id = entrega.get("oportunidade_id", "")
        opp = opp_por_id.get(opp_id, {})

        # Inicializar etapas_execucao se ainda não existem
        if "etapas_execucao" not in entrega:
            etapas = _inicializar_etapas_execucao(entrega, opp)
            if not etapas:
                continue
            entrega["etapas_execucao"] = etapas
            entrega["atualizado_em"] = agora

        etapas = entrega["etapas_execucao"]

        for etapa in etapas:
            if etapa["status"] in ("concluida", "escalada"):
                continue

            tipo = etapa["tipo"]
            cfg  = MAPA_EXECUTORES.get(tipo, {})

            # Verificar formulário
            tipo_form = cfg.get("requer_formulario")
            if tipo_form:
                form_ok, form_dados = _verificar_formulario(tipo_form, entrega, opp)
                if not form_ok:
                    if etapa.get("lembrete_enviado_em") is None:
                        _enviar_lembrete_formulario(entrega, opp, tipo_form, log)
                        etapa["lembrete_enviado_em"] = agora
                        n_lembretes += 1
                    etapa["status"] = "aguardando_formulario"
                    continue
            else:
                form_dados = {}

            # Verificar máximo de tentativas
            if etapa.get("tentativas", 0) >= 2:
                if etapa["status"] != "escalada":
                    etapa["status"] = "escalada"
                    log.warning(f"  [execucao] {entrega['id']} | {tipo} — escalada após 2 tentativas")
                    registrar_historico_entrega(
                        entrega["id"], "etapa_escalada",
                        f"Etapa '{tipo}' falhou 2x — escalada para revisão",
                        historico,
                    )
                continue

            # Executar
            etapa["status"]          = "em_execucao"
            etapa["tentativas"]      = etapa.get("tentativas", 0) + 1
            etapa["ultima_tentativa"] = agora

            try:
                resultado = _despachar_executor(tipo, entrega, opp, form_dados, log)
            except Exception as exc:
                resultado = {"status": "erro", "erro": str(exc)}

            if resultado.get("status") == "ok":
                etapa["status"]    = "concluida"
                etapa["resultado"] = resultado
                n_etapas += 1
                _propagar_resultado_etapa(tipo, resultado, entrega)
                registrar_historico_entrega(
                    entrega["id"], "etapa_concluida",
                    f"Etapa '{cfg.get('titulo', tipo)}' concluída: {resultado.get('resumo', '')}",
                    historico,
                )
                log.info(f"  [execucao] {entrega['id']} | {tipo} — OK")
            else:
                etapa["status"] = "pendente"  # retry na próxima execução
                etapa["erro"]   = resultado.get("erro", "erro desconhecido")
                log.warning(f"  [execucao] {entrega['id']} | {tipo} — falhou: {etapa['erro']}")

        # Verificar conclusão total
        pendentes = [e for e in etapas if e["status"] not in ("concluida", "escalada")]
        if not pendentes and etapas:
            _finalizar_entrega_completa(entrega, opp, historico, log)
            n_concluidas += 1

    return {
        "etapas_executadas":   n_etapas,
        "lembretes_enviados":  n_lembretes,
        "entregas_concluidas": n_concluidas,
    }


def _inicializar_etapas_execucao(entrega: dict, opp: dict) -> list:
    """Determina quais etapas de execução se aplicam à entrega."""
    oferta_id = entrega.get("oferta_id") or opp.get("oferta_id", "")
    linha     = entrega.get("linha_servico", "")
    texto     = f"{oferta_id} {linha}".lower()

    tipos: list[str] = []

    if "presenca" in texto or "google" in texto or "marketing" in texto:
        tipos.append("google_business.criar_perfil")

    if "whatsapp" in texto or "atendimento" in texto or "chat" in texto:
        tipos.append("n8n.construir_bot_atendimento")

    if "agendamento" in texto or "agenda" in texto or "booking" in texto:
        tipos.append("google_calendar.criar_agenda")
        tipos.append("n8n.construir_bot_agendamento")
        tipos.append("n8n.construir_lembrete")

    if not tipos:
        return []

    tipos += ["auto_teste.testar_cenarios", "gerar_material_treinamento", "enviar_entrega_cliente"]
    agora = datetime.now().isoformat(timespec="seconds")
    return [
        {
            "tipo":               t,
            "titulo":             MAPA_EXECUTORES.get(t, {}).get("titulo", t),
            "status":             "pendente",
            "tentativas":         0,
            "ultima_tentativa":   None,
            "lembrete_enviado_em": None,
            "resultado":          None,
            "erro":               None,
            "criado_em":          agora,
        }
        for t in tipos
    ]


def _verificar_formulario(tipo: str, entrega: dict, opp: dict) -> tuple[bool, dict]:
    """
    Verifica dados necessários para executar uma etapa.
    Em dry-run: sempre ok com dados mínimos derivados da opp.
    Em real: exige formulario_{tipo} preenchido no entrega ou dados básicos da opp.
    """
    nome   = opp.get("contraparte", "") or entrega.get("contraparte", "Negócio")
    cat    = opp.get("categoria", "")
    cidade = opp.get("cidade", "")
    tel    = opp.get("whatsapp", "") or opp.get("telefone", "")
    email  = opp.get("email", "")
    conta  = entrega.get("conta_id", entrega.get("id", ""))

    form_exp = entrega.get(f"formulario_{tipo}", {})

    if tipo == "presenca_digital":
        dados = {
            "nome_negocio":       nome,
            "categoria":          cat,
            "cidade":             cidade,
            "telefone_principal": tel,
            "email":              email,
            **form_exp,
        }
        return bool(nome), dados

    elif tipo == "atendimento_whatsapp":
        instance = (
            form_exp.get("evolution_instance")
            or ("vetor-" + "".join(c for c in conta.lower() if c.isalnum() or c == "-")[:16])
        )
        dados = {
            "nome_negocio":          nome,
            "evolution_instance":    instance,
            "faqs":                  form_exp.get("faqs", _faqs_padrao(cat)),
            "horarios":              form_exp.get("horarios", {"seg-sex": {"inicio": "09:00", "fim": "18:00"}}),
            "numero_encaminhamento": form_exp.get("numero_encaminhamento", tel),
            **form_exp,
        }
        return bool(nome), dados

    elif tipo == "agendamento_digital":
        dados = {
            "nome_negocio":  nome,
            "servicos":      form_exp.get("servicos", _servicos_padrao(cat)),
            "profissionais": form_exp.get("profissionais", [nome]),
            "duracao_padrao": form_exp.get("duracao_padrao", 30),
            "horarios":      form_exp.get("horarios", {"seg-sex": {"inicio": "09:00", "fim": "18:00"}}),
            **form_exp,
        }
        if entrega.get("google_calendar_id"):
            dados["calendar_id"] = entrega["google_calendar_id"]
        return bool(nome), dados

    return True, form_exp


def _faqs_padrao(categoria: str) -> list:
    base = [
        {"pergunta": "Qual o horário de funcionamento?",
         "resposta": "Funcionamos de segunda a sexta, das 9h às 18h."},
        {"pergunta": "Como entrar em contato?",
         "resposta": "Pode falar comigo aqui mesmo pelo WhatsApp!"},
    ]
    if categoria in ("barber", "barbearia", "beauty", "hairdresser", "salao_de_beleza"):
        base += [
            {"pergunta": "Qual o preço do corte?",
             "resposta": "Corte a partir de R$30. Manda 'agendar' para marcar seu horário."},
        ]
    elif categoria in ("dentist", "doctors", "clinica"):
        base += [
            {"pergunta": "Como marcar consulta?",
             "resposta": "Manda 'agendar' aqui e te ajudo a marcar o horário."},
        ]
    return base


def _servicos_padrao(categoria: str) -> list:
    _mapa = {
        "barber":             [{"nome": "Corte masculino", "duracao_min": 30}],
        "barbearia":          [{"nome": "Corte masculino", "duracao_min": 30}],
        "beauty":             [{"nome": "Corte feminino", "duracao_min": 60}, {"nome": "Escova", "duracao_min": 45}],
        "hairdresser":        [{"nome": "Corte feminino", "duracao_min": 60}],
        "salao_de_beleza":    [{"nome": "Corte feminino", "duracao_min": 60}, {"nome": "Escova", "duracao_min": 45}],
        "dentist":            [{"nome": "Consulta", "duracao_min": 60}, {"nome": "Limpeza", "duracao_min": 45}],
        "fitness_centre":     [{"nome": "Avaliação física", "duracao_min": 60}],
        "physiotherapist":    [{"nome": "Consulta", "duracao_min": 50}],
    }
    return _mapa.get(categoria, [{"nome": "Atendimento", "duracao_min": 30}])


def _despachar_executor(tipo: str, entrega: dict, opp: dict, dados: dict, log) -> dict:
    """Roteia o tipo de etapa para a função executora correta."""
    conta_id = entrega.get("conta_id", entrega.get("id", ""))
    nome     = opp.get("contraparte", "") or entrega.get("contraparte", "")

    if tipo == "google_business.criar_perfil":
        try:
            from conectores.google_business import GoogleBusinessConnector
            cidade = dados.get("cidade", opp.get("cidade", ""))
            res = GoogleBusinessConnector().criar_perfil({
                "nome_negocio":       dados.get("nome_negocio", nome),
                "categoria":          dados.get("categoria", opp.get("categoria", "")),
                "endereco_cidade":    cidade,
                "cidade":             cidade,
                "telefone_principal": dados.get("telefone_principal", dados.get("telefone", "")),
                "email":              dados.get("email", ""),
            })
            return {"status": "ok", "resumo": f"perfil_id={res.get('perfil_id','')}", "dados": res}
        except Exception as exc:
            return {"status": "erro", "erro": str(exc)}

    elif tipo == "google_calendar.criar_agenda":
        try:
            from conectores.google_calendar import GoogleCalendarConnector
            res = GoogleCalendarConnector().criar_agenda(
                nome=dados.get("nome_negocio", nome),
                timezone="America/Sao_Paulo",
            )
            return {"status": "ok", "resumo": f"calendar_id={res.get('calendar_id','')}", "dados": res}
        except Exception as exc:
            return {"status": "erro", "erro": str(exc)}

    elif tipo == "n8n.construir_bot_atendimento":
        try:
            from agentes.ti.agente_construtor_n8n import AgenteConstrutorN8N
            res = AgenteConstrutorN8N().construir_bot_atendimento(conta_id, dados)
            st  = "ok" if res.get("status") == "ok" else "erro"
            return {"status": st, "resumo": f"wf_id={res.get('workflow_id','')}", "dados": res,
                    "erro": res.get("motivo")}
        except Exception as exc:
            return {"status": "erro", "erro": str(exc)}

    elif tipo == "n8n.construir_bot_agendamento":
        try:
            from agentes.ti.agente_construtor_n8n import AgenteConstrutorN8N
            d = dict(dados)
            if entrega.get("google_calendar_id") and not d.get("calendar_id"):
                d["calendar_id"] = entrega["google_calendar_id"]
            res = AgenteConstrutorN8N().construir_bot_agendamento(conta_id, d)
            st  = "ok" if res.get("status") == "ok" else "erro"
            return {"status": st, "resumo": f"wf_id={res.get('workflow_id','')}", "dados": res,
                    "erro": res.get("motivo")}
        except Exception as exc:
            return {"status": "erro", "erro": str(exc)}

    elif tipo == "n8n.construir_lembrete":
        try:
            from agentes.ti.agente_construtor_n8n import AgenteConstrutorN8N
            cal_id   = entrega.get("google_calendar_id", "")
            instance = dados.get("evolution_instance", conta_id)
            res = AgenteConstrutorN8N().construir_lembrete(conta_id, cal_id, instance)
            st  = "ok" if res.get("status") == "ok" else "erro"
            return {"status": st, "resumo": f"wf_id={res.get('workflow_id','')}", "dados": res,
                    "erro": res.get("motivo")}
        except Exception as exc:
            return {"status": "erro", "erro": str(exc)}

    elif tipo == "auto_teste.testar_cenarios":
        try:
            from core.auto_teste_entrega import testar_cenarios
            res = testar_cenarios(conta_id, entrega)
            if not res.get("testes_ok", False):
                falhas = [d["tipo"] for d in res.get("detalhes", []) if not d.get("ok")]
                return {"status": "erro", "erro": f"testes falharam: {falhas}"}
            return {"status": "ok", "resumo": f"passou={res.get('passou',0)}", "dados": res}
        except Exception as exc:
            return {"status": "erro", "erro": str(exc)}

    elif tipo == "gerar_material_treinamento":
        try:
            from core.material_treinamento import gerar_material_treinamento
            res = gerar_material_treinamento(
                entrega_id=entrega.get("id", ""),
                nome_negocio=nome,
                servicos_entregues=_listar_servicos_entregues(entrega),
                nicho=opp.get("categoria", ""),
            )
            return {"status": "ok", "resumo": f"arquivo={res.get('arquivo_salvo','')}", "dados": res}
        except Exception as exc:
            return {"status": "erro", "erro": str(exc)}

    elif tipo == "enviar_entrega_cliente":
        return _executar_enviar_entrega(entrega, opp, log)

    return {"status": "erro", "erro": f"executor desconhecido: {tipo}"}


def _propagar_resultado_etapa(tipo: str, resultado: dict, entrega: dict) -> None:
    """Salva dados relevantes do resultado de volta ao dict de entrega."""
    dados = resultado.get("dados", {})
    if tipo == "google_calendar.criar_agenda":
        cal_id = dados.get("calendar_id")
        if cal_id:
            entrega["google_calendar_id"] = cal_id
    elif tipo == "google_business.criar_perfil":
        pid = dados.get("perfil_id")
        if pid:
            entrega["google_business_id"] = pid
    elif tipo in ("n8n.construir_bot_atendimento", "n8n.construir_bot_agendamento", "n8n.construir_lembrete"):
        wf_id = dados.get("workflow_id")
        if wf_id:
            sufixo = tipo.split(".")[-1].replace("construir_", "wf_")
            entrega[sufixo] = wf_id


def _listar_servicos_entregues(entrega: dict) -> list:
    """Retorna lista de tipos de serviço concluídos para gerar o material."""
    _mapa = {
        "google_business.criar_perfil":  "presenca_digital",
        "n8n.construir_bot_atendimento": "atendimento_whatsapp",
        "google_calendar.criar_agenda":  "agendamento_digital",
        "n8n.construir_bot_agendamento": "agendamento_digital",
    }
    servicos: set[str] = set()
    for etapa in entrega.get("etapas_execucao", []):
        if etapa.get("status") == "concluida":
            srv = _mapa.get(etapa["tipo"])
            if srv:
                servicos.add(srv)
    return list(servicos)


def _executar_enviar_entrega(entrega: dict, opp: dict, log=None) -> dict:
    """Envia notificação de entrega ao cliente via email e/ou WhatsApp."""
    _log = log or logging.getLogger(__name__)
    nome     = opp.get("contraparte", "") or entrega.get("contraparte", "Cliente")
    email    = opp.get("email", "")
    whatsapp = opp.get("whatsapp", "") or opp.get("telefone", "")

    etapas_ok = [
        e.get("titulo", e["tipo"])
        for e in entrega.get("etapas_execucao", [])
        if e["status"] == "concluida" and e["tipo"] != "enviar_entrega_cliente"
    ]
    cal_id = entrega.get("google_calendar_id", "")
    corpo = (
        f"Olá {nome},\n\n"
        f"Sua implantação digital está pronta!\n\n"
        f"O que entregamos:\n"
        + "".join(f"✓ {t}\n" for t in etapas_ok)
        + ("\nSua agenda digital: " + cal_id + "\n" if cal_id else "")
        + "\nQualquer dúvida, estamos aqui.\n\nEquipe Vetor"
    )

    enviou_email = False
    enviou_wpp   = False

    if email:
        try:
            from core.canais import preparar_envio
            res = preparar_envio("email", {
                "contato_destino":        email,
                "roteiro_base":           corpo,
                "abordagem_inicial_tipo": "entrega_cliente",
                "contexto_oportunidade":  {"contraparte": nome},
            })
            enviou_email = res.get("status") not in ("", None, "erro")
        except Exception:
            pass

    if whatsapp:
        try:
            from core.canais import preparar_envio
            res = preparar_envio("whatsapp", {
                "contato_destino":        whatsapp,
                "roteiro_base":           corpo[:300],
                "abordagem_inicial_tipo": "entrega_cliente",
                "contexto_oportunidade":  {"contraparte": nome},
            })
            enviou_wpp = res.get("status") not in ("", None, "erro")
        except Exception:
            pass

    _log.info(f"  [entrega_cliente] {entrega['id']} | email={enviou_email} wpp={enviou_wpp}")
    return {
        "status":       "ok",
        "resumo":       f"email={enviou_email} wpp={enviou_wpp}",
        "enviou_email": enviou_email,
        "enviou_wpp":   enviou_wpp,
    }


def _enviar_lembrete_formulario(entrega: dict, opp: dict, tipo_form: str, log) -> None:
    """Avisa o cliente que faltam dados para prosseguir com a implantação."""
    nome     = opp.get("contraparte", "") or entrega.get("contraparte", "Cliente")
    email    = opp.get("email", "")
    whatsapp = opp.get("whatsapp", "") or opp.get("telefone", "")

    _textos = {
        "presenca_digital":    "confirmar os dados do seu negócio para o Google Meu Negócio",
        "atendimento_whatsapp": "as perguntas frequentes e horários para o bot de WhatsApp",
        "agendamento_digital":  "a lista de serviços e horários para o sistema de agendamento",
    }
    item = _textos.get(tipo_form, "algumas informações para prosseguir")
    corpo = (
        f"Olá {nome},\n\n"
        f"Para avançar com sua implantação, precisamos de {item}.\n\n"
        f"Entre em contato para passarmos os detalhes.\n\nEquipe Vetor"
    )

    for canal, destino in [("email", email), ("whatsapp", whatsapp)]:
        if not destino:
            continue
        try:
            from core.canais import preparar_envio
            preparar_envio(canal, {
                "contato_destino":        destino,
                "roteiro_base":           corpo[:300],
                "abordagem_inicial_tipo": "lembrete_formulario",
                "contexto_oportunidade":  {"contraparte": nome},
            })
        except Exception:
            pass

    log.info(f"  [lembrete_form] {entrega['id']} tipo={tipo_form}")


def _finalizar_entrega_completa(entrega: dict, opp: dict, historico: list, log) -> None:
    """Marca entrega como concluída, abre acompanhamento CS e programa NPS."""
    agora = datetime.now().isoformat(timespec="seconds")
    entrega["status_entrega"] = "concluida"
    entrega["concluida_em"]   = agora
    entrega["atualizado_em"]  = agora

    registrar_historico_entrega(
        entrega["id"], "entrega_concluida",
        "Todas as etapas de execução concluídas automaticamente.",
        historico,
    )
    log.info(f"  [execucao] {entrega['id']} — ENTREGA CONCLUÍDA")

    conta_id = entrega.get("conta_id", "")

    # Abrir acompanhamento CS
    try:
        from core.acompanhamento_contas import criar_acompanhamento
        criar_acompanhamento(entrega, conta_id, "validacao_resultado", origem=NOME_AGENTE)
    except Exception as exc:
        log.debug(f"  [cs] acompanhamento não aberto: {exc}")

    # Programar NPS para 7 dias
    try:
        from core.nps_feedback import programar_nps
        programar_nps(conta_id, gatilho="pos_entrega")
    except Exception as exc:
        log.debug(f"  [nps] não programado: {exc}")
