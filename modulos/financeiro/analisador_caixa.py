"""
modulos/financeiro/analisador_caixa.py — Posição de caixa consolidada.

Lê eventos não estruturados + contas a receber + contas a pagar.
Parte de config.FINANCEIRO_SALDO_INICIAL como base do caixa.

Nomenclatura dos campos de saída:
  total_a_receber_aberto    — faturado/comprometido ainda não recebido (≠ "confirmado como recebido")
  total_a_pagar_aberto      — comprometido ainda não pago (≠ "confirmado como pago")
  total_a_receber_previsto  — esperado mas não faturado ou não comprometido
  total_a_pagar_previsto    — planejado mas não comprometido
  total_recebido_confirmado — soma do que efetivamente entrou no caixa
  total_pago_confirmado     — soma do que efetivamente saiu do caixa
"""

import logging
from datetime import date, timedelta

import config

logger = logging.getLogger(__name__)


def analisar_caixa(
    eventos: list,
    contas_a_receber: list = None,
    contas_a_pagar: list = None,
) -> dict:
    """
    Calcula posição de caixa consolidada.
    contas_a_receber e contas_a_pagar devem ter status efetivo já aplicado
    (via carregar_com_status_efetivo() de cada módulo).
    """
    contas_a_receber = contas_a_receber or []
    contas_a_pagar   = contas_a_pagar   or []

    saldo_atual             = float(config.FINANCEIRO_SALDO_INICIAL)
    total_recebido_conf     = 0.0   # o que realmente entrou no caixa
    total_pago_conf         = 0.0   # o que realmente saiu do caixa
    a_receber_aberto        = 0.0   # faturado/comprometido, não recebido ainda
    a_receber_previsto      = 0.0   # esperado mas não comprometido
    a_pagar_aberto          = 0.0   # comprometido, não pago ainda
    a_pagar_previsto        = 0.0   # planejado mas não comprometido
    total_vencido_eventos   = 0.0

    # ── Eventos (transações não estruturadas) ──────────────────────────────
    for ev in eventos:
        if ev.get("status") == "cancelado":
            continue
        tipo   = ev.get("tipo", "")
        status = ev.get("status", "pendente")
        valor  = float(ev.get("valor", 0))

        if tipo == "cobranca_recebida" and status == "confirmado":
            saldo_atual         += valor
            total_recebido_conf += valor
        if tipo in ("despesa_identificada", "pagamento_confirmado") and status == "confirmado":
            saldo_atual       -= valor
            total_pago_conf   += valor
        if tipo == "cobranca_emitida" and status == "confirmado":
            a_receber_aberto  += valor
        if tipo == "cobranca_emitida" and status == "pendente":
            a_receber_previsto += valor
        if tipo == "entrada_prevista" and status == "pendente":
            a_receber_previsto += valor
        if tipo == "conta_a_vencer" and status in ("pendente", "confirmado"):
            a_pagar_aberto    += valor
        if tipo == "saida_prevista" and status == "pendente":
            a_pagar_previsto  += valor
        if tipo == "conta_vencida" and status == "vencido":
            total_vencido_eventos += valor
        if tipo == "cliente_atrasou" and status == "vencido":
            total_vencido_eventos += valor

    # ── Contas a receber (estruturadas) ───────────────────────────────────
    total_aberto_a_receber  = 0.0
    total_vencido_a_receber = 0.0
    recebimentos_recentes   = []
    hoje = date.today()
    limite_recentes = hoje - timedelta(days=30)

    for c in contas_a_receber:
        status          = c.get("status", "aberta")
        valor_recebido  = float(c.get("valor_recebido", 0))
        valor_em_aberto = float(c.get("valor_em_aberto", 0))

        if status == "cancelada":
            continue

        if status == "recebida":
            saldo_atual         += valor_recebido
            total_recebido_conf += valor_recebido
            data_rec = c.get("data_recebimento")
            if data_rec:
                try:
                    if date.fromisoformat(data_rec) >= limite_recentes:
                        recebimentos_recentes.append({
                            "contraparte": c.get("contraparte"),
                            "valor":       round(valor_recebido, 2),
                            "data":        data_rec,
                        })
                except ValueError:
                    pass

        elif status == "parcial":
            saldo_atual            += valor_recebido
            total_recebido_conf    += valor_recebido
            a_receber_aberto       += valor_em_aberto
            total_aberto_a_receber += valor_em_aberto

        elif status == "aberta":
            a_receber_aberto       += valor_em_aberto
            total_aberto_a_receber += valor_em_aberto

        elif status == "vencida":
            total_vencido_a_receber += valor_em_aberto
            total_aberto_a_receber  += valor_em_aberto  # ainda precisa receber

    # ── Contas a pagar (estruturadas) ─────────────────────────────────────
    total_aberto_a_pagar  = 0.0
    total_vencido_a_pagar = 0.0
    pagamentos_recentes   = []

    for c in contas_a_pagar:
        status          = c.get("status", "aberta")
        valor_pago      = float(c.get("valor_pago", 0))
        valor_em_aberto = float(c.get("valor_em_aberto", 0))

        if status == "cancelada":
            continue

        if status == "paga":
            saldo_atual       -= valor_pago
            total_pago_conf   += valor_pago
            data_pag = c.get("data_pagamento")
            if data_pag:
                try:
                    if date.fromisoformat(data_pag) >= limite_recentes:
                        pagamentos_recentes.append({
                            "contraparte": c.get("contraparte"),
                            "valor":       round(valor_pago, 2),
                            "data":        data_pag,
                        })
                except ValueError:
                    pass

        elif status == "parcial":
            saldo_atual         -= valor_pago
            total_pago_conf     += valor_pago
            a_pagar_aberto      += valor_em_aberto
            total_aberto_a_pagar += valor_em_aberto

        elif status == "aberta":
            a_pagar_aberto       += valor_em_aberto
            total_aberto_a_pagar += valor_em_aberto

        elif status == "vencida":
            total_vencido_a_pagar += valor_em_aberto
            total_aberto_a_pagar  += valor_em_aberto  # ainda precisa pagar

    # ── Consolidação ───────────────────────────────────────────────────────
    saldo_previsto = (
        saldo_atual
        + a_receber_aberto
        + a_receber_previsto
        - a_pagar_aberto
        - a_pagar_previsto
    )

    total_vencido_geral = total_vencido_eventos + total_vencido_a_receber + total_vencido_a_pagar
    risco_caixa = saldo_previsto < config.FINANCEIRO_THRESHOLD_RISCO or total_vencido_geral > 0

    recebimentos_recentes.sort(key=lambda x: x["data"], reverse=True)
    pagamentos_recentes.sort(key=lambda x: x["data"], reverse=True)

    return {
        "saldo_inicial":              float(config.FINANCEIRO_SALDO_INICIAL),
        "saldo_atual_estimado":       round(saldo_atual, 2),
        "total_recebido_confirmado":  round(total_recebido_conf, 2),  # efetivamente recebido
        "total_pago_confirmado":      round(total_pago_conf, 2),       # efetivamente pago
        "total_a_receber_aberto":     round(a_receber_aberto, 2),      # faturado, aguardando
        "total_a_receber_previsto":   round(a_receber_previsto, 2),    # esperado, não faturado
        "total_a_pagar_aberto":       round(a_pagar_aberto, 2),        # comprometido, a pagar
        "total_a_pagar_previsto":     round(a_pagar_previsto, 2),      # planejado, não comprometido
        "total_aberto_a_receber":     round(total_aberto_a_receber, 2),
        "total_aberto_a_pagar":       round(total_aberto_a_pagar, 2),
        "total_vencido":              round(total_vencido_eventos, 2),
        "total_vencido_a_receber":    round(total_vencido_a_receber, 2),
        "total_vencido_a_pagar":      round(total_vencido_a_pagar, 2),
        "saldo_previsto":             round(saldo_previsto, 2),
        "risco_caixa":                risco_caixa,
        "recebimentos_recentes":      recebimentos_recentes[:10],
        "pagamentos_recentes":        pagamentos_recentes[:10],
        "resumo_curto":               _resumo(
            saldo_atual, a_receber_aberto, a_receber_previsto,
            a_pagar_aberto, a_pagar_previsto,
            total_vencido_a_receber, total_vencido_a_pagar,
            total_vencido_eventos, risco_caixa
        ),
        "calculado_em": hoje.isoformat(),
    }


def _resumo(
    saldo, a_rec_aberto, a_rec_prev, a_pag_aberto, a_pag_prev,
    venc_receber, venc_pagar, venc_eventos, risco
) -> str:
    partes = []
    if saldo >= 0:
        partes.append(f"Saldo atual: R$ {saldo:,.2f}")
    else:
        partes.append(f"Saldo NEGATIVO: R$ {saldo:,.2f}")
    if a_rec_aberto > 0:
        partes.append(f"a receber aberto: R$ {a_rec_aberto:,.2f}")
    if a_rec_prev > 0:
        partes.append(f"a receber previsto: R$ {a_rec_prev:,.2f}")
    if a_pag_aberto > 0:
        partes.append(f"a pagar aberto: R$ {a_pag_aberto:,.2f}")
    if a_pag_prev > 0:
        partes.append(f"previsto pagar: R$ {a_pag_prev:,.2f}")
    if venc_receber > 0:
        partes.append(f"VENCIDO a receber: R$ {venc_receber:,.2f}")
    if venc_pagar > 0:
        partes.append(f"VENCIDO a pagar: R$ {venc_pagar:,.2f}")
    if venc_eventos > 0:
        partes.append(f"vencido (eventos): R$ {venc_eventos:,.2f}")
    if risco:
        partes.append("RISCO DE CAIXA")
    return " | ".join(partes) if partes else "Sem movimentacao registrada"
