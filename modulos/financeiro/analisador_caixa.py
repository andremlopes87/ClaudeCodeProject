"""
modulos/financeiro/analisador_caixa.py — Posição de caixa a partir dos eventos registrados.

Só lê eventos — não registra, não altera nada.

Campos gerados:
  saldo_atual_estimado        — entradas confirmadas menos saídas confirmadas
  total_a_receber_confirmado  — faturado e confirmado pelo cliente, ainda não recebido
  total_a_receber_previsto    — esperado mas não faturado ou não confirmado
  total_a_pagar_confirmado    — compromisso de pagamento futuro (conta a vencer)
  total_a_pagar_previsto      — planejado mas ainda não comprometido
  total_vencido               — soma de valores overdue (a pagar ou a receber)
  saldo_previsto              — projeção: saldo + receber - pagar
  risco_caixa                 — bool: saldo previsto negativo ou há valores vencidos
  resumo_curto                — texto legível com os principais números
"""

import logging
from datetime import date

import config

logger = logging.getLogger(__name__)


def analisar_caixa(eventos: list) -> dict:
    """Calcula posição de caixa a partir dos eventos. Retorna dict pronto para serializar."""
    saldo_atual              = 0.0
    a_receber_confirmado     = 0.0
    a_receber_previsto       = 0.0
    a_pagar_confirmado       = 0.0
    a_pagar_previsto         = 0.0
    total_vencido            = 0.0

    for ev in eventos:
        if ev.get("status") == "cancelado":
            continue

        tipo   = ev.get("tipo", "")
        status = ev.get("status", "pendente")
        valor  = float(ev.get("valor", 0))

        # ── Entradas reais (dinheiro já no caixa) ──────────────────────
        if tipo == "cobranca_recebida" and status == "confirmado":
            saldo_atual += valor

        # ── Saídas reais (dinheiro já saiu do caixa) ───────────────────
        if tipo in ("despesa_identificada", "pagamento_confirmado") and status == "confirmado":
            saldo_atual -= valor

        # ── A receber confirmado (faturado + cliente confirmou) ─────────
        if tipo == "cobranca_emitida" and status == "confirmado":
            a_receber_confirmado += valor

        # ── A receber previsto (esperado, não confirmado ainda) ─────────
        if tipo == "cobranca_emitida" and status == "pendente":
            a_receber_previsto += valor
        if tipo == "entrada_prevista" and status == "pendente":
            a_receber_previsto += valor

        # ── A pagar confirmado (compromisso futuro certo) ───────────────
        if tipo == "conta_a_vencer" and status in ("pendente", "confirmado"):
            a_pagar_confirmado += valor

        # ── A pagar previsto (planejado, ainda sem data firme) ──────────
        if tipo == "saida_prevista" and status == "pendente":
            a_pagar_previsto += valor

        # ── Vencido (risco: a pagar atrasado OU a receber atrasado) ────
        if tipo == "conta_vencida" and status == "vencido":
            total_vencido += valor
        if tipo == "cliente_atrasou" and status == "vencido":
            total_vencido += valor

    saldo_previsto = (
        saldo_atual
        + a_receber_confirmado
        + a_receber_previsto
        - a_pagar_confirmado
        - a_pagar_previsto
    )

    risco_caixa = saldo_previsto < config.FINANCEIRO_THRESHOLD_RISCO or total_vencido > 0

    return {
        "saldo_atual_estimado":       round(saldo_atual, 2),
        "total_a_receber_confirmado": round(a_receber_confirmado, 2),
        "total_a_receber_previsto":   round(a_receber_previsto, 2),
        "total_a_pagar_confirmado":   round(a_pagar_confirmado, 2),
        "total_a_pagar_previsto":     round(a_pagar_previsto, 2),
        "total_vencido":              round(total_vencido, 2),
        "saldo_previsto":             round(saldo_previsto, 2),
        "risco_caixa":                risco_caixa,
        "resumo_curto":               _resumo(
            saldo_atual, a_receber_confirmado, a_receber_previsto,
            a_pagar_confirmado, a_pagar_previsto, total_vencido, risco_caixa
        ),
        "calculado_em": date.today().isoformat(),
    }


def _resumo(saldo, a_rec_conf, a_rec_prev, a_pag_conf, a_pag_prev, vencido, risco) -> str:
    partes = []
    if saldo >= 0:
        partes.append(f"Saldo atual: R$ {saldo:,.2f}")
    else:
        partes.append(f"Saldo NEGATIVO: R$ {saldo:,.2f}")
    if a_rec_conf > 0:
        partes.append(f"a receber confirmado: R$ {a_rec_conf:,.2f}")
    if a_rec_prev > 0:
        partes.append(f"a receber previsto: R$ {a_rec_prev:,.2f}")
    if a_pag_conf > 0:
        partes.append(f"a pagar: R$ {a_pag_conf:,.2f}")
    if a_pag_prev > 0:
        partes.append(f"previsto pagar: R$ {a_pag_prev:,.2f}")
    if vencido > 0:
        partes.append(f"VENCIDO: R$ {vencido:,.2f}")
    if risco:
        partes.append("RISCO DE CAIXA")
    return " | ".join(partes) if partes else "Sem movimentação registrada"
