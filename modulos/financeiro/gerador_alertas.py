"""
modulos/financeiro/gerador_alertas.py — Gera filas de alertas e decisões humanas.

Alertas   : eventos urgentes que exigem atenção operacional (curto_prazo ou imediata).
Decisões  : eventos que precisam de julgamento ou aprovação humana (requer_decisao=True).

A fila de decisões é enxuta — só eventos com impacto real ou ambiguidade real.
"""

import logging
from datetime import date

import config

logger = logging.getLogger(__name__)

_ORDEM_URGENCIA = {"imediata": 0, "curto_prazo": 1, "medio_prazo": 2}


def gerar_alertas(eventos: list, posicao_caixa: dict) -> tuple:
    """
    Gera fila de alertas e fila de decisões.
    Retorna: (fila_alertas, fila_decisoes)
    """
    hoje = date.today()
    alertas  = []
    decisoes = []

    for ev in eventos:
        if ev.get("status") == "cancelado":
            continue

        urgencia       = ev.get("urgencia", "medio_prazo")
        requer_decisao = ev.get("requer_decisao", False)

        if urgencia in ("imediata", "curto_prazo"):
            alertas.append(_resumir(ev, motivo_alerta=_motivo_alerta(ev, hoje)))

        if requer_decisao:
            decisoes.append(_resumir(ev, motivo_decisao=ev.get("motivo_decisao")))

    # Alerta extra: saldo previsto negativo (calculado pelo analisador_caixa)
    if posicao_caixa.get("risco_caixa") and posicao_caixa.get("saldo_previsto", 0) < 0:
        saldo = posicao_caixa["saldo_previsto"]
        evento_risco = {
            "id":             "caixa_previsto",
            "tipo":           "risco_de_caixa",
            "status":         "pendente",
            "descricao":      "Saldo previsto negativo",
            "valor":          abs(saldo),
            "data_vencimento": None,
            "contraparte":    None,
            "urgencia":       "imediata",
            "motivo_alerta":  f"Saldo previsto: R$ {saldo:,.2f} — caixa insuficiente",
            "motivo_decisao": (
                f"Caixa previsto negativo (R$ {saldo:,.2f}) — "
                "revisar pagamentos ou antecipar recebíveis"
            ),
        }
        alertas.append(evento_risco)
        decisoes.append(evento_risco)

    alertas  = _dedup_e_ordenar(alertas)
    decisoes = _dedup_e_ordenar(decisoes)

    logger.info(f"Alertas gerados: {len(alertas)} | Decisões: {len(decisoes)}")
    return alertas, decisoes


# ─── Internos ──────────────────────────────────────────────────────────────

def _resumir(evento: dict, motivo_alerta: str = None, motivo_decisao: str = None) -> dict:
    return {
        "id":             evento.get("id"),
        "tipo":           evento.get("tipo"),
        "status":         evento.get("status"),
        "descricao":      evento.get("descricao"),
        "valor":          evento.get("valor"),
        "data_vencimento": evento.get("data_vencimento"),
        "contraparte":    evento.get("contraparte"),
        "urgencia":       evento.get("urgencia"),
        "motivo_alerta":  motivo_alerta,
        "motivo_decisao": motivo_decisao,
    }


def _motivo_alerta(evento: dict, hoje: date) -> str:
    tipo   = evento.get("tipo", "")
    status = evento.get("status", "")
    valor  = float(evento.get("valor", 0))
    venc   = evento.get("data_vencimento")

    if tipo == "conta_vencida" or (status == "vencido" and tipo != "cliente_atrasou"):
        return f"conta vencida de R$ {valor:,.2f} — pagar ou negociar"
    if tipo == "cliente_atrasou":
        return f"cliente em atraso de R$ {valor:,.2f} — acionar cobrança"
    if tipo == "risco_de_caixa":
        return "risco de caixa identificado manualmente"
    if venc:
        try:
            diff = (date.fromisoformat(venc) - hoje).days
            if diff < 0:
                return f"venceu há {abs(diff)} dia(s)"
            if diff == 0:
                return "vence hoje"
            return f"vence em {diff} dia(s)"
        except ValueError:
            pass
    return "evento urgente"


def _dedup_e_ordenar(lista: list) -> list:
    vistos = set()
    resultado = []
    for item in lista:
        chave = item.get("id", id(item))
        if chave not in vistos:
            vistos.add(chave)
            resultado.append(item)
    resultado.sort(key=lambda e: _ORDEM_URGENCIA.get(e.get("urgencia", "medio_prazo"), 2))
    return resultado
