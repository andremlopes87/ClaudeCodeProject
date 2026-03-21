"""
modulos/financeiro/registrador_eventos.py — Captura e validação de eventos financeiros.

Regra de modelagem:
  tipo   = o que aconteceu (definido no registro, não muda)
  status = estado atual do evento (pode mudar ao longo do tempo)
"""

import uuid
import logging
from datetime import datetime

from core.persistencia import carregar_json_fixo, salvar_json_fixo

logger = logging.getLogger(__name__)

ARQUIVO_EVENTOS = "eventos_financeiros.json"

TIPOS_VALIDOS = {
    "cobranca_emitida",        # cobrança enviada ao cliente — receita esperada
    "cobranca_recebida",       # pagamento de cliente confirmado — receita realizada
    "cliente_atrasou",         # cliente não pagou no vencimento
    "despesa_identificada",    # despesa registrada — saída de caixa
    "conta_a_vencer",          # conta que vence nos próximos dias
    "conta_vencida",           # conta que passou do vencimento sem pagamento
    "pagamento_confirmado",    # pagamento de despesa confirmado
    "entrada_prevista",        # receita esperada ainda não faturada
    "saida_prevista",          # despesa planejada ainda não executada
    "risco_de_caixa",          # alerta manual de risco de caixa
}

STATUS_VALIDOS = {
    "pendente",    # evento registrado, aguardando confirmação ou vencimento
    "confirmado",  # confirmado — entrada ou saída realizada
    "vencido",     # passou do vencimento sem resolução
    "cancelado",   # cancelado — ignorado nas análises
    "em_analise",  # ambíguo ou incompleto — precisa de revisão humana
}

CATEGORIAS_VALIDAS = {
    "receita",
    "despesa_operacional",
    "despesa_fixa",
    "investimento",
    "imposto",
    "transferencia",
}

CAMPOS_OBRIGATORIOS = ["tipo", "descricao", "valor", "data_evento"]

_TIPOS_RECEITA = {"cobranca_emitida", "cobranca_recebida", "entrada_prevista", "cliente_atrasou"}


def registrar_evento(evento: dict) -> dict:
    """
    Valida e registra um evento financeiro.
    Retorna o evento completo com id e campos padrão preenchidos.
    """
    evento_completo = _construir_evento(evento)
    eventos = carregar_json_fixo(ARQUIVO_EVENTOS, padrao=[])
    eventos.append(evento_completo)
    salvar_json_fixo(eventos, ARQUIVO_EVENTOS)
    logger.info(
        f"Evento registrado: [{evento_completo['id']}] "
        f"{evento_completo['tipo']} | R$ {evento_completo['valor']:.2f}"
    )
    return evento_completo


def registrar_lote(lista_eventos: list) -> list:
    """
    Registra múltiplos eventos em lote.
    Carrega o arquivo uma vez, adiciona todos, salva uma vez.
    """
    eventos_existentes = carregar_json_fixo(ARQUIVO_EVENTOS, padrao=[])
    registrados = []
    for ev in lista_eventos:
        try:
            evento_completo = _construir_evento(ev)
            eventos_existentes.append(evento_completo)
            registrados.append(evento_completo)
            logger.info(
                f"  [{evento_completo['id']}] {evento_completo['tipo']} "
                f"| R$ {evento_completo['valor']:.2f} | {evento_completo['descricao']}"
            )
        except ValueError as e:
            logger.warning(f"Evento inválido ignorado: {e} | {ev.get('descricao', '?')}")

    salvar_json_fixo(eventos_existentes, ARQUIVO_EVENTOS)
    logger.info(f"{len(registrados)} de {len(lista_eventos)} eventos registrados em lote.")
    return registrados


def carregar_eventos() -> list:
    """Carrega todos os eventos registrados."""
    return carregar_json_fixo(ARQUIVO_EVENTOS, padrao=[])


# ─── Interno ───────────────────────────────────────────────────────────────

def _construir_evento(evento: dict) -> dict:
    """Valida campos e retorna evento completo com defaults preenchidos."""
    for campo in CAMPOS_OBRIGATORIOS:
        if evento.get(campo) is None:
            raise ValueError(f"Campo obrigatório ausente: {campo}")

    tipo = evento["tipo"]
    if tipo not in TIPOS_VALIDOS:
        raise ValueError(f"Tipo inválido: '{tipo}'. Válidos: {sorted(TIPOS_VALIDOS)}")

    status = evento.get("status", "pendente")
    if status not in STATUS_VALIDOS:
        raise ValueError(f"Status inválido: '{status}'. Válidos: {sorted(STATUS_VALIDOS)}")

    categoria_padrao = "receita" if tipo in _TIPOS_RECEITA else "despesa_operacional"

    return {
        "id":              evento.get("id") or str(uuid.uuid4())[:8],
        "tipo":            tipo,
        "status":          status,
        "descricao":       evento["descricao"],
        "valor":           float(evento["valor"]),
        "data_evento":     evento["data_evento"],
        "data_vencimento": evento.get("data_vencimento"),
        "categoria":       evento.get("categoria", categoria_padrao),
        "contraparte":     evento.get("contraparte"),    # quem pagou, quem cobrou, quem emitiu
        "canal_origem":    evento.get("canal_origem", "manual"),  # manual | sistema | banco | email
        "referencia":      evento.get("referencia"),    # número de nota, contrato, fatura, NF
        "impacto_caixa":   None,      # preenchido pelo classificador
        "urgencia":        None,      # preenchido pelo classificador
        "requer_decisao":  False,     # preenchido pelo classificador
        "motivo_decisao":  None,      # preenchido pelo classificador
        "observacoes":     evento.get("observacoes"),
        "registrado_em":   datetime.now().isoformat(),
    }
