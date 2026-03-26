"""
agentes/executor_contato/agente_executor_contato.py — Executor operacional de contato.

Primeiro executor operacional real da arquitetura.
Consome handoffs e follow-ups destinados a este agente,
prepara execucoes internas estruturadas e deixa tudo pronto
para futura integracao com canais reais (telefone, WhatsApp, email).

Nao envia mensagem real. Nao liga. Nao negocia. Nao movimenta dinheiro.
Registra apenas fatos internos reais.

Saidas:
  dados/fila_execucao_contato.json      — execucoes preparadas por tentativa
  dados/historico_execucao_contato.json — log auditavel de eventos internos
  dados/estado_agente_executor_contato.json
  logs/agentes/agente_executor_contato_{ts}.log

Ponto de integracao futura:
  fila_execucao_contato.json com pronto_para_integracao=True
  e payload_execucao preenchido e validado.
"""

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path

import config
from core.llm_router import LLMRouter
from core.controle_agente import (
    carregar_estado,
    salvar_estado,
    ja_processado,
    marcar_processado,
    registrar_execucao,
    gerar_hash_execucao,
    configurar_log_agente,
)

NOME_AGENTE     = "agente_executor_contato"
_DESTINO_AGENTE = "agente_executor_contato"
_CANAIS_VALIDOS = {"telefone", "whatsapp", "email", "presencial"}


# ─── Ponto de entrada ────────────────────────────────────────────────────────

def executar() -> dict:
    log, caminho_log = configurar_log_agente(NOME_AGENTE)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")

    log.info("=" * 60)
    log.info(f"AGENTE EXECUTOR CONTATO — inicio {ts}")
    log.info("=" * 60)

    estado = carregar_estado(NOME_AGENTE)
    log.info(
        f"Estado: ultima_execucao={estado['ultima_execucao']} | "
        f"processados={len(estado.get('itens_processados', []))}"
    )

    router = LLMRouter()

    # ── ETAPA 0: Carregar identidade da empresa ────────────────────────────
    try:
        from core.identidade_empresa import obter_contexto_remetente
        _remetente = obter_contexto_remetente()
        log.info(
            f"Identidade carregada: remetente='{_remetente['nome_remetente']}' | "
            f"email='{_remetente['email_comercial'] or 'pendente'}' | "
            f"status_email='{_remetente['status_email']}'"
        )
    except Exception as _exc_id:
        _remetente = {}
        log.warning(f"Identidade nao carregada: {_exc_id}")

    # ── ETAPA 1: Carregar insumos ──────────────────────────────────────────
    handoffs  = _carregar_json("handoffs_agentes.json",        padrao=[])
    followups = _carregar_json("fila_followups.json",          padrao=[])
    pipeline  = _carregar_json("pipeline_comercial.json",      padrao=[])
    hist_abord = _carregar_json("historico_abordagens.json",   padrao=[])

    fila_exec  = _carregar_json("fila_execucao_contato.json",        padrao=[])
    hist_exec  = _carregar_json("historico_execucao_contato.json",   padrao=[])

    # Índices para busca rápida
    idx_followup = {fu["id"]: fu for fu in followups}
    idx_pipeline = {opp["id"]: opp for opp in pipeline}
    idx_exec     = {e["id"]: i for i, e in enumerate(fila_exec)}

    pendentes = carregar_handoffs_pendentes(handoffs)
    log.info(
        f"Insumos: {len(handoffs)} handoffs | {len(pendentes)} pendentes para este agente | "
        f"{len(followups)} follow-ups | {len(pipeline)} opps"
    )

    # ── ETAPA 1b: Classificar respostas recebidas via LLM (ponto 5) ───────
    n_classif_llm = _classificar_resultados_contato_llm(router, log)
    if n_classif_llm:
        log.info(f"  [llm] {n_classif_llm} resposta(s) de contato classificada(s)")

    # ── ETAPA 2: Processar cada handoff ───────────────────────────────────
    n_preparados = 0
    n_bloqueados = 0
    n_skip       = 0

    for handoff in pendentes:
        exec_id = f"exec_{handoff['referencia_id']}"

        if ja_processado(estado, exec_id):
            log.info(f"  [skip] {exec_id} — ja processado")
            n_skip += 1
            continue

        fu  = localizar_followup_relacionado(handoff, idx_followup)
        if fu is None:
            log.warning(f"  [bloqueado] {exec_id} — follow-up nao encontrado: {handoff.get('referencia_id')}")
            _registrar_bloqueio_sem_fu(handoff, fila_exec, hist_exec, idx_exec, log)
            n_bloqueados += 1
            marcar_processado(estado, exec_id)
            continue

        opp = _localizar_oportunidade(fu, idx_pipeline)

        ok, motivo = validar_followup_para_execucao(fu, opp, handoff)

        if ok:
            abordagem = detectar_abordagem_execucao(fu, opp)
            payload   = montar_payload_execucao(fu, opp)
            enriquecer_payload_execucao(payload, abordagem, fu, opp)

            # LLM: Redigir corpo de email personalizado (ponto 4 — fallback = roteiro_base existente)
            if payload.get("canal") == "email":
                _ctx_email = {
                    "empresa":       fu.get("contraparte", ""),
                    "abordagem":     abordagem,
                    "canal":         "email",
                    "roteiro_base":  payload.get("roteiro_base", "")[:200],
                    "linha_servico": payload.get("linha_servico_sugerida", ""),
                    "instrucao":     "Redigir corpo de email profissional para primeiro contato com empresa.",
                }
                _empresa_id_email = opp.get("conta_id", "") if opp else ""
                try:
                    from core.contatos_contas import obter_contato_principal
                    if _empresa_id_email:
                        _ct = obter_contato_principal(_empresa_id_email)
                        if _ct:
                            _ctx_email["nome_contato"] = _ct.get("nome", "")
                except Exception:
                    pass
                _res_email = router.redigir(_ctx_email, empresa_id=_empresa_id_email or None)
                _usou_llm_email = _res_email["sucesso"] and not _res_email["fallback_usado"]
                if _usou_llm_email:
                    payload["corpo_email_llm"] = _res_email["resultado"]
                    payload["roteiro_base"]    = _res_email["resultado"]
                log.info(f"  [llm] email={'LLM' if _usou_llm_email else 'regra'} | {fu.get('contraparte','?')[:40]}")

            # Enriquecer com identidade da empresa (remetente, assinatura)
            if _remetente:
                payload["remetente"] = {
                    "nome_empresa":    _remetente.get("nome_empresa", ""),
                    "nome_remetente":  _remetente.get("nome_remetente", ""),
                    "cargo":           _remetente.get("cargo_remetente", ""),
                    "email_comercial": _remetente.get("email_comercial", ""),
                    "whatsapp_oficial": _remetente.get("whatsapp_oficial", ""),
                    "assinatura":      _remetente.get("assinatura_comercial", ""),
                }

            execucao = criar_execucao_contato(handoff, fu, opp, payload,
                                              status="aguardando_integracao_canal",
                                              motivo_bloqueio=None,
                                              exec_id=exec_id,
                                              abordagem=abordagem)
            _upsert_execucao(fila_exec, idx_exec, execucao)

            ev_prep = f"execucao_preparada_{abordagem}"
            registrar_historico_execucao(hist_exec, execucao, "handoff_recebido",
                f"Handoff {handoff['id']} recebido de {handoff.get('agente_origem','?')}")
            registrar_historico_execucao(hist_exec, execucao, ev_prep,
                f"Payload montado | abordagem={abordagem} | canal={payload['canal']} | contato={payload['contato_destino']}")
            registrar_historico_execucao(hist_exec, execucao, "pronto_para_integracao",
                f"Aguardando conector de canal real ({payload['canal']})")

            atualizar_statuses_relacionados(handoff, fu, opp, pipeline, followups,
                                            status_handoff="em_andamento",
                                            status_followup="aguardando_integracao_canal",
                                            status_operacional="aguardando_integracao_canal")
            _registrar_evento_historico_abordagens(hist_abord, fu, opp, exec_id, abordagem)

            # Memória: registrar canal tentado na conta (melhor esforço)
            if opp and opp.get("conta_id"):
                try:
                    from core.llm_memoria import atualizar_memoria_conta
                    atualizar_memoria_conta(opp["conta_id"], {
                        "contexto_comercial": f"execucao preparada | canal={payload.get('canal','?')} | abordagem={abordagem}",
                        "canais_tentados":    [payload.get("canal")] if payload.get("canal") else [],
                    })
                except Exception:
                    pass

            n_preparados += 1
            log.info(
                f"  [preparado/{abordagem}] {exec_id} | {fu.get('contraparte','?')[:40]} | "
                f"canal={payload['canal']} | contato={payload['contato_destino']}"
            )
        else:
            execucao = criar_execucao_contato(handoff, fu, opp, payload={},
                                              status="bloqueado",
                                              motivo_bloqueio=motivo,
                                              exec_id=exec_id)
            _upsert_execucao(fila_exec, idx_exec, execucao)
            registrar_historico_execucao(hist_exec, execucao, "handoff_recebido",
                f"Handoff {handoff['id']} recebido de {handoff.get('agente_origem','?')}")
            registrar_historico_execucao(hist_exec, execucao, "execucao_bloqueada",
                f"Bloqueio: {motivo}")

            atualizar_statuses_relacionados(handoff, fu, opp, pipeline, followups,
                                            status_handoff="pendente",
                                            status_followup="bloqueado",
                                            status_operacional="bloqueado")

            n_bloqueados += 1
            log.info(f"  [bloqueado] {exec_id} | {fu.get('contraparte','?')[:40]} | {motivo}")

        marcar_processado(estado, exec_id)

    # ── ETAPA 3: Persistir arquivos ────────────────────────────────────────
    _salvar_json("fila_execucao_contato.json",      fila_exec)
    _salvar_json("historico_execucao_contato.json", hist_exec)
    _salvar_json("handoffs_agentes.json",           handoffs)
    _salvar_json("fila_followups.json",             followups)
    _salvar_json("pipeline_comercial.json",         pipeline)
    _salvar_json("historico_abordagens.json",       hist_abord)

    # ── ETAPA 4: Salvar estado ─────────────────────────────────────────────
    resumo_str = (
        f"preparados={n_preparados} bloqueados={n_bloqueados} "
        f"skip={n_skip} fila_total={len(fila_exec)}"
    )
    resultado_hash = {
        "posicao": {"saldo_atual_estimado": 0},
        "fila_riscos": [],
        "alertas": [],
        "resumo": {"resumo_curto": resumo_str},
    }
    registrar_execucao(
        estado,
        saldo       = 0.0,
        resumo      = resumo_str,
        n_escalados = n_bloqueados,
        n_autonomos = n_preparados,
        hash_exec   = gerar_hash_execucao(resultado_hash),
    )
    salvar_estado(NOME_AGENTE, estado)

    log.info("=" * 60)
    log.info(f"AGENTE EXECUTOR CONTATO — concluido")
    log.info(f"  handoffs pendentes  : {len(pendentes)}")
    log.info(f"  preparados          : {n_preparados}")
    log.info(f"  bloqueados          : {n_bloqueados}")
    log.info(f"  skip (ja proc.)     : {n_skip}")
    log.info(f"  fila_exec total     : {len(fila_exec)}")
    log.info("=" * 60)

    # Memória do agente (melhor esforço)
    try:
        from core.llm_memoria import atualizar_memoria_agente
        atualizar_memoria_agente(NOME_AGENTE, {
            "resumo_ciclo_anterior": f"{n_preparados} preparados, {n_bloqueados} bloqueados, {n_skip} skip"
        })
    except Exception:
        pass

    return {
        "agente":          NOME_AGENTE,
        "timestamp":       ts,
        "handoffs_lidos":  len(pendentes),
        "preparados":      n_preparados,
        "bloqueados":      n_bloqueados,
        "skip":            n_skip,
        "fila_total":      len(fila_exec),
        "caminho_log":     str(caminho_log),
    }


# ─── Funções operacionais ─────────────────────────────────────────────────────

def carregar_handoffs_pendentes(handoffs: list) -> list:
    """Retorna handoffs pendentes destinados a este agente."""
    return [
        h for h in handoffs
        if h.get("agente_destino") == _DESTINO_AGENTE and h.get("status") == "pendente"
    ]


def localizar_followup_relacionado(handoff: dict, idx_followup: dict):
    """Localiza o follow-up referenciado pelo handoff. Retorna None se não encontrado."""
    fu_id = handoff.get("referencia_id", "")
    return idx_followup.get(fu_id)


def validar_followup_para_execucao(fu, opp, handoff) -> tuple:
    """
    Valida se há dados mínimos para preparar a tentativa de execução.
    Retorna (True, None) se válido, (False, motivo) se bloqueado.
    """
    if fu is None:
        return False, "follow-up nao encontrado"

    if fu.get("status") in ("cancelado", "executado"):
        return False, f"follow-up com status={fu.get('status')} — nao executavel"

    canal = fu.get("canal", "")
    if not canal or canal not in _CANAIS_VALIDOS:
        return False, f"canal invalido ou ausente: '{canal}'"

    descricao = fu.get("descricao", "")
    if not descricao or len(descricao) < 10:
        return False, "descricao ausente ou muito curta"

    contato = _extrair_contato_destino(fu, opp)
    if not contato:
        return False, "contato_destino nao encontrado (sem contato_principal e sem numero na descricao)"

    return True, None


def montar_payload_execucao(fu: dict, opp) -> dict:
    """
    Monta o payload estruturado da tentativa de execução.
    Pronto para futura integração com conector de canal.
    """
    canal   = fu.get("canal", "")
    contato = _extrair_contato_destino(fu, opp)

    contexto = {}
    if opp:
        contexto = {
            "contraparte":    opp.get("contraparte", ""),
            "estagio":        opp.get("estagio", ""),
            "prioridade":     opp.get("prioridade", ""),
            "canal_sugerido": opp.get("canal_sugerido", ""),
            "categoria":      opp.get("categoria", ""),
            "cidade":         opp.get("cidade", ""),
            "observacoes":    opp.get("observacoes", "")[:200] if opp.get("observacoes") else "",
        }

    tentativa_num = _calcular_numero_tentativa(fu)

    return {
        "canal":                  canal,
        "contato_destino":        contato,
        "roteiro_base":           fu.get("descricao", ""),
        "contexto_oportunidade":  contexto,
        "observacoes":            f"Tentativa #{tentativa_num} | tipo_acao={fu.get('tipo_acao','?')}",
        "acao_sugerida": (
            f"Executar {canal} para {contato} seguindo roteiro. "
            f"Registrar resultado em historico_abordagens.json."
        ),
    }


def criar_execucao_contato(
    handoff: dict,
    fu: dict,
    opp,
    payload: dict,
    status: str,
    motivo_bloqueio,
    exec_id: str,
    abordagem: str = "padrao",
) -> dict:
    """Cria item de execucao para fila_execucao_contato.json."""
    agora = datetime.now().isoformat(timespec="seconds")
    pronto = status == "aguardando_integracao_canal"
    return {
        "id":                      exec_id,
        "handoff_id":              handoff["id"],
        "followup_id":             fu.get("id", "") if fu else "",
        "oportunidade_id":         fu.get("oportunidade_id", "") if fu else "",
        "contraparte":             fu.get("contraparte", "") if fu else "",
        "canal":                   fu.get("canal", "") if fu else "",
        "tipo_acao":               fu.get("tipo_acao", "") if fu else "",
        "descricao":               fu.get("descricao", "") if fu else "",
        "abordagem_inicial_tipo":  abordagem,
        "origem_oportunidade":     opp.get("origem_oportunidade", "") if opp else "",
        "linha_servico_sugerida":  opp.get("linha_servico_sugerida", "") if opp else "",
        "roteiro_base":            payload.get("roteiro_base", "") if payload else "",
        "payload_execucao":        payload,
        "status":                  status,
        "motivo_bloqueio":         motivo_bloqueio,
        "tentativa_numero":        _calcular_numero_tentativa(fu) if fu else 1,
        "pronto_para_integracao":  pronto,
        "registrado_em":           agora,
        "atualizado_em":           agora,
    }


def registrar_historico_execucao(
    hist_exec: list,
    execucao: dict,
    evento: str,
    descricao: str,
) -> None:
    """Adiciona evento ao historico_execucao_contato (in-place)."""
    agora = datetime.now().isoformat(timespec="seconds")
    chave = f"{execucao['id']}|{evento}|{agora}"
    hist_exec.append({
        "id":              "hev_" + hashlib.md5(chave.encode()).hexdigest()[:12],
        "execucao_id":     execucao["id"],
        "handoff_id":      execucao["handoff_id"],
        "followup_id":     execucao["followup_id"],
        "oportunidade_id": execucao["oportunidade_id"],
        "evento":          evento,
        "descricao":       descricao,
        "resultado":       execucao["status"],
        "registrado_em":   agora,
    })


def atualizar_statuses_relacionados(
    handoff: dict,
    fu: dict,
    opp,
    pipeline: list,
    followups: list,
    status_handoff: str,
    status_followup: str,
    status_operacional: str,
) -> None:
    """
    Atualiza handoff, follow-up e status_operacional do pipeline (in-place).
    Não avança o estagio do pipeline — apenas status_operacional.
    """
    agora = datetime.now().isoformat(timespec="seconds")

    handoff["status"]      = status_handoff
    handoff["atualizado_em"] = agora

    if fu:
        fu["status"]       = status_followup
        fu["atualizado_em"] = agora

    if opp:
        opp["status_operacional"] = status_operacional
        opp["atualizado_em"]      = agora


# ─── Especialização por abordagem ────────────────────────────────────────────

def detectar_abordagem_execucao(fu: dict, opp) -> str:
    """
    Determina o tipo de abordagem para a execução.
    Ordem: opp.abordagem_inicial_tipo → opp.origem_oportunidade → fu.origem_followup → 'padrao'

    Retorna: 'exploratoria' | 'consultiva_diagnostica' | 'padrao'
    """
    if opp:
        tipo = opp.get("abordagem_inicial_tipo", "")
        if tipo in ("exploratoria", "consultiva_diagnostica"):
            return tipo
        origem = opp.get("origem_oportunidade", "")
        if "marketing" in origem:
            return "consultiva_diagnostica"
        if origem == "prospeccao":
            return "exploratoria"

    if fu:
        orig_fu = fu.get("origem_followup", "")
        if orig_fu == "marketing":
            return "consultiva_diagnostica"
        if orig_fu == "prospeccao_e_marketing":
            return "consultiva_diagnostica"
        if orig_fu == "prospeccao":
            return "exploratoria"

    return "padrao"


def montar_roteiro_base_por_abordagem(abordagem: str, fu: dict, opp) -> str:
    """
    Gera roteiro_base diferenciado conforme a abordagem.
    Não inventa resposta do cliente. Não negocia preço.
    """
    empresa = (fu.get("contraparte", "empresa") if fu else "empresa") or "empresa"

    if abordagem == "consultiva_diagnostica":
        contexto = ""
        if opp:
            contexto = (opp.get("contexto_origem", "") or "")[:200]
        partes = [
            f"Retomar oportunidade detectada no digital — {empresa}",
            "Apresentar diagnóstico resumido quando existir",
            "Validar interesse em resolver gargalo específico",
            "Avançar para proposta quando fizer sentido",
        ]
        if contexto:
            partes.append(f"Contexto: {contexto}")
        return " | ".join(partes)

    if abordagem == "exploratoria":
        desc_fu = (fu.get("descricao", "") if fu else "")[:200]
        return (
            f"Mapear interesse e validar dor — abrir conversa inicial com {empresa} | "
            f"Confirmar contexto básico e qualificar interesse | "
            f"Não assumir problema específico como fato | "
            f"{desc_fu}"
        ).rstrip(" | ")

    # padrao — usa descricao original do follow-up
    return (fu.get("descricao", "") if fu else "")[:300]


def enriquecer_payload_execucao(payload: dict, abordagem: str, fu: dict, opp) -> None:
    """
    Enriquece o payload in-place com campos de abordagem e roteiro especializado.
    Adiciona: roteiro_base, abordagem_inicial_tipo, linha_servico_sugerida,
              origem_oportunidade ao payload e ao contexto_oportunidade.
    """
    roteiro = montar_roteiro_base_por_abordagem(abordagem, fu, opp)
    payload["roteiro_base"]           = roteiro
    payload["abordagem_inicial_tipo"] = abordagem
    payload["linha_servico_sugerida"] = opp.get("linha_servico_sugerida", "") if opp else ""
    payload["origem_oportunidade"]    = opp.get("origem_oportunidade", "") if opp else ""

    ctx = payload.get("contexto_oportunidade", {})
    if isinstance(ctx, dict):
        ctx["abordagem_inicial_tipo"]  = abordagem
        ctx["linha_servico_sugerida"]  = payload["linha_servico_sugerida"]
        ctx["contexto_origem"]         = (opp.get("contexto_origem", "") or "")[:200] if opp else ""


# ─── Internos ─────────────────────────────────────────────────────────────────

def _localizar_oportunidade(fu: dict, idx_pipeline: dict):
    """Localiza oportunidade pelo oportunidade_id do follow-up. Retorna None se ausente."""
    opp_id = fu.get("oportunidade_id", "") if fu else ""
    return idx_pipeline.get(opp_id)


def _extrair_contato_destino(fu: dict, opp) -> str:
    """
    Extrai contato destino estruturado.
    Prioridade: contato_principal do pipeline > telefone extraído da descricao.
    """
    # 1. pipeline tem contato_principal válido
    if opp:
        cp = opp.get("contato_principal", "") or ""
        if cp and cp.strip().lower() not in ("n/a", "", "none"):
            return cp.strip()

    # 2. follow-up tem contato_principal válido
    if fu:
        cp = fu.get("contato_principal", "") or ""
        if cp and cp.strip().lower() not in ("n/a", "", "none"):
            return cp.strip()

    # 3. extrair número de telefone/WhatsApp da descricao
    if fu:
        desc = fu.get("descricao", "") or ""
        match = re.search(r"(\+55\s?[\d\s\-\.]{8,}|\d[\d\s\-\.]{7,})", desc)
        if match:
            numero = re.sub(r"[\s\-\.]", "", match.group(1))
            if len(numero) >= 8:
                return numero

    return ""


def _calcular_numero_tentativa(fu) -> int:
    """Calcula número da tentativa baseado no sufixo do follow-up id."""
    if fu is None:
        return 1
    fu_id = fu.get("id", "")
    parts = fu_id.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return 1


def _upsert_execucao(fila_exec: list, idx_exec: dict, execucao: dict) -> None:
    """Insere ou atualiza execucao na fila (in-place), por id."""
    exec_id = execucao["id"]
    if exec_id in idx_exec:
        execucao["registrado_em"] = fila_exec[idx_exec[exec_id]]["registrado_em"]
        fila_exec[idx_exec[exec_id]] = execucao
    else:
        fila_exec.append(execucao)
        idx_exec[exec_id] = len(fila_exec) - 1


def _registrar_bloqueio_sem_fu(handoff, fila_exec, hist_exec, idx_exec, log) -> None:
    """Cria item bloqueado quando o follow-up não é encontrado."""
    exec_id = f"exec_{handoff['referencia_id']}"
    execucao = criar_execucao_contato(
        handoff, fu=None, opp=None, payload={},
        status="bloqueado",
        motivo_bloqueio="follow-up nao encontrado no arquivo fila_followups.json",
        exec_id=exec_id,
    )
    _upsert_execucao(fila_exec, idx_exec, execucao)
    registrar_historico_execucao(hist_exec, execucao, "handoff_recebido",
        f"Handoff {handoff['id']} recebido mas follow-up ausente")
    registrar_historico_execucao(hist_exec, execucao, "execucao_bloqueada",
        "Follow-up nao encontrado — nao e possivel montar payload")
    log.warning(f"  [bloqueado] {exec_id} — follow-up ausente")


def _registrar_evento_historico_abordagens(hist_abord: list, fu: dict, opp, exec_id: str, abordagem: str = "padrao") -> None:
    """
    Registra evento em historico_abordagens.json com tipo específico por abordagem.
    Nunca afirma que houve contato real.
    """
    agora    = datetime.now().isoformat(timespec="seconds")
    opp_id   = fu.get("oportunidade_id", "?")
    chave    = f"{opp_id}|payload_execucao_gerado|{agora}"
    tipo_ev  = f"payload_execucao_gerado_{abordagem}"

    contexto_origem = ""
    if opp:
        contexto_origem = opp.get("contexto_origem", "")[:120] or ""

    hist_abord.append({
        "id":              "hab_" + hashlib.md5(chave.encode()).hexdigest()[:12],
        "oportunidade_id": opp_id,
        "contraparte":     fu.get("contraparte", "?"),
        "tipo_evento":     tipo_ev,
        "descricao":       (
            f"Payload preparado por agente_executor_contato | "
            f"abordagem={abordagem} | "
            f"execucao_id={exec_id} | canal={fu.get('canal','?')} | "
            + (f"contexto: {contexto_origem}" if contexto_origem else "aguardando integracao com canal real")
        ),
        "origem":          NOME_AGENTE,
        "agente_responsavel": NOME_AGENTE,
        "registrado_em":   agora,
    })


# ─── Classificação LLM de resultados de contato ──────────────────────────────

def _classificar_resultados_contato_llm(router, log) -> int:
    """
    Enriquece resultados_contato.json com classificação LLM para entradas com
    resposta_cliente preenchida e sem classificacao_llm.
    Fallback automático: se LLM falhar ou dry-run retornar fallback, ignora e continua.
    Retorna número de classificações realizadas.
    """
    caminho = config.PASTA_DADOS / "resultados_contato.json"
    if not caminho.exists():
        return 0
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            resultados = json.load(f)
    except Exception as exc:
        log.warning(f"  [llm_classif] erro ao carregar resultados_contato: {exc}")
        return 0

    n_classificados = 0
    modificado = False
    for res in resultados:
        resposta = res.get("resposta_cliente", "") or ""
        if not resposta or res.get("classificacao_llm"):
            continue
        _ctx_classif = {
            "texto":      resposta[:500],
            "categorias": ["interessado", "nao_agora", "recusa", "pedido_info", "spam", "ambiguo"],
            "instrucao":  "Classificar resposta de cliente potencial em uma das categorias.",
        }
        _res_classif = router.classificar(_ctx_classif)
        _usou_llm = _res_classif["sucesso"] and not _res_classif["fallback_usado"]
        if _usou_llm:
            res["classificacao_llm"] = _res_classif["resultado"]
            n_classificados += 1
            modificado = True
        log.info(f"  [llm] classif={'LLM' if _usou_llm else 'regra'} | {resposta[:40]!r}")

    if modificado:
        try:
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(resultados, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            log.warning(f"  [llm_classif] erro ao salvar resultados_contato: {exc}")

    return n_classificados


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
        f"Salvo: {caminho.name} ({len(dados) if isinstance(dados, list) else 1} registros)"
    )
