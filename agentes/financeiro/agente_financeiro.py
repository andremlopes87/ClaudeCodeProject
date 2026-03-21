"""
agentes/financeiro/agente_financeiro.py — Agente financeiro operacional.

Lê a posição financeira atual, executa o pipeline de análise,
classifica o que pode tratar sozinho e escala o que exige decisão humana.

Não movimenta dinheiro. Não cobra. Não paga. Não renegocia.
Classifica, alerta, recomenda e escala.

Integra com core/controle_agente.py para:
  - estado persistente entre execuções
  - deduplicação de itens
  - fila de decisões consolidada
  - agenda do dia (atualização idempotente)
  - aprovações humanas
"""

import logging
from datetime import datetime

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
from modulos.financeiro.pipeline import executar_analise_financeira
from modulos.financeiro.registrador_eventos import carregar_eventos
from modulos.financeiro.contas_a_receber import carregar_com_status_efetivo as receber_efetivo
from modulos.financeiro.contas_a_pagar import carregar_com_status_efetivo as pagar_efetivo

NOME_AGENTE = "agente_financeiro"

# Urgências que exigem escalamento ao usuário
_URGENCIAS_ESCALAMENTO = {"imediata", "alta"}


def executar() -> dict:
    """
    Executa o agente financeiro completo.
    Retorna dict com resumo da execução.
    """
    log, caminho_log = configurar_log_agente(NOME_AGENTE)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")

    log.info("=" * 60)
    log.info(f"AGENTE FINANCEIRO — inicio {ts}")
    log.info("=" * 60)

    # ── ETAPA 1: Carregar estado anterior ─────────────────────────────────
    estado = carregar_estado(NOME_AGENTE)
    log.info(
        f"Estado carregado: ultima_execucao={estado['ultima_execucao']} | "
        f"processados={len(estado['itens_processados'])} | "
        f"pendentes={len(estado['itens_pendentes_escalados'])}"
    )

    # ── ETAPA 2: Verificar aprovações recebidas ────────────────────────────
    aprovacoes = carregar_aprovacoes()
    aprovados_agora = _processar_aprovacoes(aprovacoes, estado, log)

    # ── ETAPA 3: Carregar dados financeiros ────────────────────────────────
    log.info("Carregando dados financeiros com status efetivo...")
    eventos         = carregar_eventos()
    contas_receber  = receber_efetivo()
    contas_pagar    = pagar_efetivo()
    log.info(
        f"Dados carregados: {len(eventos)} eventos | "
        f"{len(contas_receber)} contas a receber | "
        f"{len(contas_pagar)} contas a pagar"
    )

    # ── ETAPA 4: Executar pipeline financeiro ─────────────────────────────
    log.info("Executando pipeline financeiro...")
    resultado = executar_analise_financeira(
        eventos=eventos,
        contas_a_receber=contas_receber,
        contas_a_pagar=contas_pagar,
        salvar=True,
        ts=ts,
    )
    posicao    = resultado["posicao"]
    alertas    = resultado["alertas"]
    fila_riscos = resultado["fila_riscos"]
    previsao   = resultado["previsao"]
    log.info(
        f"Pipeline concluido: saldo={posicao['saldo_atual_estimado']:.2f} | "
        f"alertas={len(alertas)} | riscos={len(fila_riscos)}"
    )

    # ── ETAPA 5: Processar riscos — autônomo vs escalamento ───────────────
    log.info("Classificando riscos e alertas...")
    itens_escalados  = []
    itens_autonomos  = []

    # Processar fila de riscos
    for risco in fila_riscos:
        item_id = risco.get("id")
        if not item_id:
            continue

        if ja_processado(estado, item_id):
            log.info(f"  [skip] {item_id} — ja processado")
            continue

        if esta_pendente(estado, item_id):
            log.info(f"  [aguardando] {item_id} — escalado, sem resposta ainda")
            continue

        if _deve_escalar_risco(risco, posicao, previsao):
            item_consolidado = _formatar_item_consolidado(risco, NOME_AGENTE)
            itens_escalados.append(item_consolidado)
            marcar_pendente(estado, item_id)
            log.info(f"  [ESCALAR] {item_id} — urgencia={risco['urgencia']} tipo={risco['tipo']}")
        else:
            itens_autonomos.append(risco)
            marcar_processado(estado, item_id)
            log.info(f"  [autonomo] {item_id} — urgencia={risco['urgencia']} tipo={risco['tipo']}")

    # Processar alertas de urgência imediata não mapeados pelos riscos
    # Dedup: se a mesma contraparte já foi coberta por um risco vencido escalado, pular o alerta
    contrapartes_cobertas = _extrair_contrapartes_cobertas(itens_escalados)

    for alerta in alertas:
        item_id = alerta.get("id")
        if not item_id:
            continue
        if ja_processado(estado, item_id) or esta_pendente(estado, item_id):
            continue

        contraparte = alerta.get("contraparte", "")
        if contraparte and contraparte in contrapartes_cobertas:
            log.info(f"  [coberto por risco] alerta {item_id} — {contraparte} ja escalado via risco vencido")
            continue

        if alerta.get("urgencia") == "imediata":
            item_consolidado = _formatar_item_consolidado_alerta(alerta, NOME_AGENTE)
            itens_escalados.append(item_consolidado)
            marcar_pendente(estado, item_id)
            log.info(f"  [ESCALAR alerta] {item_id} — {alerta.get('descricao', '')[:60]}")

    # ── ETAPA 6: Atualizar fila consolidada ────────────────────────────────
    if itens_escalados:
        registrar_na_fila_consolidada(itens_escalados)
        log.info(f"Fila consolidada atualizada: {len(itens_escalados)} itens escalados")

    # ── ETAPA 7: Atualizar agenda do dia ──────────────────────────────────
    itens_agenda = [i for i in itens_escalados if i.get("urgencia") in _URGENCIAS_ESCALAMENTO]
    if itens_agenda:
        atualizar_agenda(itens_agenda)
        log.info(f"Agenda do dia atualizada: {len(itens_agenda)} itens urgentes")

    # ── ETAPA 8: Salvar estado ────────────────────────────────────────────
    hash_exec = gerar_hash_execucao(resultado)
    registrar_execucao(
        estado,
        saldo   = posicao["saldo_atual_estimado"],
        resumo  = posicao.get("resumo_curto", ""),
        n_escalados = len(itens_escalados),
        n_autonomos = len(itens_autonomos),
        hash_exec   = hash_exec,
    )
    salvar_estado(NOME_AGENTE, estado)

    # ── ETAPA 9: Resumo final ─────────────────────────────────────────────
    resumo_execucao = {
        "agente":             NOME_AGENTE,
        "timestamp":          ts,
        "saldo_atual":        posicao["saldo_atual_estimado"],
        "saldo_previsto":     posicao["saldo_previsto"],
        "risco_caixa":        posicao["risco_caixa"],
        "total_riscos":       len(fila_riscos),
        "total_alertas":      len(alertas),
        "autonomos":          len(itens_autonomos),
        "escalados":          len(itens_escalados),
        "aprovados_nesta_exec": aprovados_agora,
        "caminho_log":        str(caminho_log),
    }

    log.info("=" * 60)
    log.info(f"AGENTE FINANCEIRO — concluido")
    log.info(f"  saldo atual    : R$ {posicao['saldo_atual_estimado']:,.2f}")
    log.info(f"  saldo previsto : R$ {posicao['saldo_previsto']:,.2f}")
    log.info(f"  risco de caixa : {'SIM' if posicao['risco_caixa'] else 'nao'}")
    log.info(f"  riscos         : {len(fila_riscos)}")
    log.info(f"  alertas        : {len(alertas)}")
    log.info(f"  autonomos      : {len(itens_autonomos)}")
    log.info(f"  escalados      : {len(itens_escalados)}")
    log.info("=" * 60)

    return resumo_execucao


# ─── Regras de escalamento ───────────────────────────────────────────────────

def _deve_escalar_risco(risco: dict, posicao: dict, previsao: dict) -> bool:
    """
    Retorna True se o risco deve ser escalado para o usuário.

    Critérios de escalamento:
    - Urgência alta
    - Buraco de caixa em 7 dias
    - Risco operacional imediato (sinais heurísticos)
    - Risco de caixa na posição atual
    """
    if risco.get("urgencia") == "alta":
        return True

    tipo = risco.get("tipo", "")

    if tipo == "caixa_insuficiente_na_janela":
        janela_7 = previsao.get("janelas", {}).get("7_dias", {})
        if janela_7.get("houve_buraco_de_caixa"):
            return True

    if tipo in ("vencido_sem_resolucao", "vencido_sem_pagamento"):
        return True

    if posicao.get("risco_caixa") and tipo == "crescimento_bloqueado":
        return True

    return False


# ─── Aprovações ──────────────────────────────────────────────────────────────

def _processar_aprovacoes(aprovacoes: list, estado: dict, log) -> int:
    """
    Verifica aprovações recebidas para itens pendentes deste agente.
    Resolve pendentes que foram aprovados/rejeitados.
    Retorna número de itens resolvidos nesta execução.
    """
    pendentes = set(estado.get("itens_pendentes_escalados", []))
    resolvidos = 0
    for ap in aprovacoes:
        if ap.get("item_id") in pendentes and ap.get("decisao") in ("aprovado", "rejeitado"):
            resolver_pendente(estado, ap["item_id"])
            resolvidos += 1
            log.info(
                f"  [resolvido] {ap['item_id']} — decisao={ap['decisao']} "
                f"em {ap.get('data_decisao', '?')}"
            )
    if resolvidos:
        log.info(f"Aprovacoes processadas: {resolvidos} itens resolvidos")
    return resolvidos


# ─── Formatação de itens para filas ─────────────────────────────────────────

def _extrair_contrapartes_cobertas(itens_escalados: list) -> set:
    """
    Extrai contrapartes já cobertas por riscos vencidos escalados.
    Evita duplicar o mesmo problema (vencido_sem_resolucao + alerta imediato).
    Formato da descricao: 'Contraparte — descricao — vencido em data'
    """
    tipos_vencidos = {"vencido_sem_resolucao", "vencido_sem_pagamento"}
    cobertas = set()
    for item in itens_escalados:
        if item.get("tipo") in tipos_vencidos:
            desc  = item.get("descricao", "")
            parte = desc.split("—")[0].strip()
            if parte:
                cobertas.add(parte)
    return cobertas


def _formatar_item_consolidado(risco: dict, agente_origem: str) -> dict:
    """Formata risco no esquema da fila consolidada."""
    return {
        "item_id":        risco["id"],
        "agente_origem":  agente_origem,
        "tipo":           risco.get("tipo", ""),
        "descricao":      risco.get("descricao", ""),
        "urgencia":       risco.get("urgencia", "media"),
        "acao_sugerida":  risco.get("acao_sugerida", ""),
        "prazo_sugerido": risco.get("prazo_sugerido"),
        "status_aprovacao": "pendente",
    }


def _formatar_item_consolidado_alerta(alerta: dict, agente_origem: str) -> dict:
    """Formata alerta no esquema da fila consolidada."""
    return {
        "item_id":        alerta.get("id", ""),
        "agente_origem":  agente_origem,
        "tipo":           alerta.get("tipo", "alerta"),
        "descricao":      alerta.get("descricao", ""),
        "urgencia":       alerta.get("urgencia", "imediata"),
        "acao_sugerida":  alerta.get("motivo_alerta", "revisar item urgente"),
        "prazo_sugerido": alerta.get("data_vencimento"),
        "status_aprovacao": "pendente",
    }
