"""
modulos/financeiro/classificador_eventos.py — Classifica impacto e urgência dos eventos.

Separação de responsabilidades:
  tipo   = o que aconteceu (imutável após registro)
  status = estado atual (pode mudar)
  impacto_caixa / urgencia / requer_decisao = derivados aqui, recalculados a cada execução

Usa config.FINANCEIRO_* para thresholds ajustáveis.
"""

import logging
from datetime import date

import config

logger = logging.getLogger(__name__)

# Tipos cujo impacto no caixa é positivo (entrada real)
_TIPOS_ENTRADA_REAL = {"cobranca_recebida"}

# Tipos cujo impacto é saída real confirmada
_TIPOS_SAIDA_REAL = {"despesa_identificada", "pagamento_confirmado", "conta_vencida"}

# Tipos cujo impacto é previsto positivo
_TIPOS_ENTRADA_PREVISTA = {"cobranca_emitida", "entrada_prevista"}

# Tipos cujo impacto é previsto negativo
_TIPOS_SAIDA_PREVISTA = {"conta_a_vencer", "saida_prevista"}


def classificar_eventos(eventos: list) -> list:
    """
    Aplica impacto_caixa, urgencia e requer_decisao a cada evento.
    Modifica a lista em lugar — retorna a mesma lista.
    """
    hoje = date.today()
    for evento in eventos:
        evento["impacto_caixa"] = _impacto(evento)
        evento["urgencia"] = _urgencia(evento, hoje)
        requer, motivo = _decisao(evento, hoje)
        evento["requer_decisao"] = requer
        evento["motivo_decisao"] = motivo
    return eventos


# ─── Internos ──────────────────────────────────────────────────────────────

def _impacto(evento: dict) -> str:
    tipo = evento.get("tipo", "")
    status = evento.get("status", "pendente")

    if tipo in _TIPOS_ENTRADA_REAL and status == "confirmado":
        return "positivo"
    if tipo in _TIPOS_ENTRADA_PREVISTA and status == "confirmado":
        return "positivo"  # faturado e confirmado pelo cliente
    if tipo in _TIPOS_ENTRADA_PREVISTA and status == "pendente":
        return "previsto_positivo"
    if tipo in _TIPOS_SAIDA_REAL and status == "confirmado":
        return "negativo"
    if tipo in _TIPOS_SAIDA_PREVISTA:
        return "previsto_negativo"
    if tipo == "cliente_atrasou":
        return "risco_positivo"   # devemos receber, mas está em risco
    if tipo == "risco_de_caixa":
        return "alerta"
    if status == "vencido":
        return "negativo" if tipo in _TIPOS_SAIDA_REAL else "risco_positivo"
    return "neutro"


def _urgencia(evento: dict, hoje: date) -> str:
    tipo = evento.get("tipo", "")
    status = evento.get("status", "pendente")

    # Já vencido → imediato
    if status == "vencido" or tipo in ("conta_vencida", "risco_de_caixa"):
        return "imediata"
    if tipo == "cliente_atrasou":
        return "imediata"

    # Vence em breve → avalia pelo data_vencimento
    venc = evento.get("data_vencimento")
    if venc:
        try:
            diff = (date.fromisoformat(venc) - hoje).days
            if diff <= config.FINANCEIRO_DIAS_ALERTA_IMEDIATO:
                return "imediata"
            if diff <= config.FINANCEIRO_DIAS_ALERTA_CURTO_PRAZO:
                return "curto_prazo"
        except ValueError:
            pass

    return "medio_prazo"


def _decisao(evento: dict, hoje: date) -> tuple:
    """Retorna (requer_decisao: bool, motivo: str | None)."""
    tipo = evento.get("tipo", "")
    valor = float(evento.get("valor", 0))
    status = evento.get("status", "pendente")
    limiar = config.FINANCEIRO_VALOR_RELEVANTE

    # Risco de caixa → sempre escala
    if tipo == "risco_de_caixa":
        return True, "caixa em risco — requer análise e decisão"

    # Cliente atrasado com valor relevante (verificar antes de conta_vencida)
    if tipo == "cliente_atrasou" and valor >= limiar:
        return True, f"cliente atrasado em R$ {valor:,.2f} — acionar cobrança"

    # Conta vencida com valor relevante
    if (tipo == "conta_vencida" or status == "vencido") and valor >= limiar:
        return True, f"conta vencida de R$ {valor:,.2f} — pagar ou renegociar"

    # Despesa elevada (acima de 3× o limiar)
    if tipo == "despesa_identificada" and valor >= limiar * 3:
        return True, f"despesa elevada de R$ {valor:,.2f} — confirmar autorização"

    # Evento ambíguo
    if status == "em_analise":
        return True, "evento marcado como em_analise — aguardando classificação"

    return False, None
