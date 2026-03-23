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
_STATUS_APTOS   = {"onboarding", "aprovado", "pronto_para_implantacao"}


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

        entrega, criada = abrir_ou_atualizar_entrega(opp, pipeline_entrega, log)

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
            checklist = criar_checklist_inicial_por_linha_servico(
                entrega["id"], opp.get("linha_servico_sugerida", "")
            )
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
        entrega_id = insumo.get("entrega_id", "")
        entrega    = next((e for e in pipeline_entrega if e["id"] == entrega_id), None)
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

    # ── ETAPA 4: Persistir ─────────────────────────────────────────────────
    _salvar_json("pipeline_entrega.json",   pipeline_entrega)
    _salvar_json("checklists_entrega.json", checklists)
    _salvar_json("historico_entrega.json",  historico)
    _salvar_json("handoffs_agentes.json",   handoffs)
    _salvar_json("insumos_entrega.json",    insumos)

    # ── ETAPA 5: Salvar estado ─────────────────────────────────────────────
    resumo_str = (
        f"aptas={len(aptas)} abertas={n_abertas} atualizadas={n_atualizadas} "
        f"checklists={n_checklists} bloqueadas={n_bloqueadas} "
        f"insumos_aplicados={n_insumos_aplic} deliberacoes={n_delib}"
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
    log.info("=" * 60)

    return {
        "agente":             NOME_AGENTE,
        "timestamp":          ts,
        "aptas":              len(aptas),
        "abertas":            n_abertas,
        "atualizadas":        n_atualizadas,
        "checklists_criados": n_checklists,
        "bloqueadas":         n_bloqueadas,
        "insumos_aplicados":  n_insumos_aplic,
        "deliberacoes":       n_delib,
        "pipeline_entrega":   len(pipeline_entrega),
        "caminho_log":        str(caminho_log),
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

def criar_checklist_inicial_por_linha_servico(entrega_id: str, linha: str) -> dict:
    """Cria checklist inicial com itens especificos por linha de servico."""
    agora = datetime.now().isoformat(timespec="seconds")
    return {
        "id":            f"ck_{entrega_id}",
        "entrega_id":    entrega_id,
        "linha_servico": linha or "nao_definida",
        "itens":         _itens_checklist_por_linha(linha),
        "status":        "pendente",
        "registrado_em": agora,
        "atualizado_em": agora,
    }


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


# ─── Persistência ─────────────────────────────────────────────────────────────

def _carregar_json(nome: str, padrao):
    caminho = config.PASTA_DADOS / nome
    if not caminho.exists():
        return padrao
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def _salvar_json(nome: str, dados) -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = config.PASTA_DADOS / nome
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    logging.getLogger(__name__).info(
        f"Salvo: {caminho} ({len(dados) if isinstance(dados, list) else 1} registro(s))"
    )
