"""
modulos/financeiro/resumo_financeiro.py — Resumo financeiro operacional consolidado.

Agrega contas a receber, contas a pagar, posição de caixa, alertas e decisões
em um único documento legível por humanos e agentes.

Saída: resumo_financeiro_operacional.json
"""

import logging
from datetime import date

logger = logging.getLogger(__name__)


def gerar_resumo(
    posicao_caixa: dict,
    contas_a_receber: list,
    contas_a_pagar: list,
    alertas: list,
    decisoes: list,
) -> dict:
    """Gera resumo financeiro operacional consolidado. Retorna dict pronto para serializar."""

    # ── Contas a receber ───────────────────────────────────────────────────
    receber_abertas  = [c for c in contas_a_receber if c.get("status") in ("aberta", "parcial")]
    receber_vencidas = [c for c in contas_a_receber if c.get("status") == "vencida"]

    total_em_aberto_receber = sum(float(c.get("valor_em_aberto", 0)) for c in receber_abertas)
    total_vencido_receber   = sum(float(c.get("valor_em_aberto", 0)) for c in receber_vencidas)

    # ── Contas a pagar ─────────────────────────────────────────────────────
    pagar_abertas  = [c for c in contas_a_pagar if c.get("status") in ("aberta", "parcial")]
    pagar_vencidas = [c for c in contas_a_pagar if c.get("status") == "vencida"]

    total_em_aberto_pagar = sum(float(c.get("valor_em_aberto", 0)) for c in pagar_abertas)
    total_vencido_pagar   = sum(float(c.get("valor_em_aberto", 0)) for c in pagar_vencidas)

    risco = posicao_caixa.get("risco_caixa", False)

    resumo_curto = _resumo(
        total_em_aberto_receber, total_em_aberto_pagar,
        total_vencido_receber,   total_vencido_pagar,
        len(receber_vencidas),   len(pagar_vencidas),
        len(alertas),            len(decisoes),
        risco,
    )

    return {
        "total_contas_a_receber_abertas":  len(receber_abertas),
        "total_contas_a_receber_vencidas": len(receber_vencidas),
        "total_contas_a_pagar_abertas":    len(pagar_abertas),
        "total_contas_a_pagar_vencidas":   len(pagar_vencidas),
        "total_em_aberto_a_receber":       round(total_em_aberto_receber, 2),
        "total_em_aberto_a_pagar":         round(total_em_aberto_pagar, 2),
        "total_vencido_a_receber":         round(total_vencido_receber, 2),
        "total_vencido_a_pagar":           round(total_vencido_pagar, 2),
        "risco_caixa":                     risco,
        "quantidade_alertas":              len(alertas),
        "quantidade_decisoes":             len(decisoes),
        "resumo_curto":                    resumo_curto,
        "gerado_em":                       date.today().isoformat(),
    }


def _resumo(
    rec_aberto, pag_aberto, rec_vencido, pag_vencido,
    n_rec_vencidas, n_pag_vencidas, n_alertas, n_decisoes, risco
) -> str:
    partes = []
    if rec_aberto > 0:
        partes.append(f"a receber: R$ {rec_aberto:,.2f}")
    if pag_aberto > 0:
        partes.append(f"a pagar: R$ {pag_aberto:,.2f}")
    if rec_vencido > 0:
        partes.append(f"vencido a receber: R$ {rec_vencido:,.2f} ({n_rec_vencidas} conta(s))")
    if pag_vencido > 0:
        partes.append(f"vencido a pagar: R$ {pag_vencido:,.2f} ({n_pag_vencidas} conta(s))")
    if n_alertas > 0:
        partes.append(f"{n_alertas} alerta(s)")
    if n_decisoes > 0:
        partes.append(f"{n_decisoes} decisao(oes) pendente(s)")
    if risco:
        partes.append("RISCO DE CAIXA")
    return " | ".join(partes) if partes else "Sem pendencias financeiras"
