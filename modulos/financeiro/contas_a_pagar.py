"""
modulos/financeiro/contas_a_pagar.py — Gestão de contas a pagar.

Ciclo de vida:
  aberta → paga (total) | parcial → paga | vencida → paga/cancelada

Campos de rastreabilidade opcionais:
  evento_origem_id    — liga esta conta a um evento que a gerou
  conta_relacionada_id — liga esta conta a outra (ex: conta a receber que originou)
"""

import uuid
import logging
from datetime import datetime, date

import config
from core.persistencia import carregar_json_fixo, salvar_json_fixo

logger = logging.getLogger(__name__)

ARQUIVO_CONTAS = "contas_a_pagar.json"

STATUS_VALIDOS = {"aberta", "paga", "parcial", "vencida", "cancelada"}

CAMPOS_OBRIGATORIOS = [
    "contraparte", "descricao", "valor_total", "data_lancamento", "data_vencimento"
]


# ─── Registro ──────────────────────────────────────────────────────────────

def registrar_conta_a_pagar(conta: dict) -> dict:
    """Valida e registra uma conta a pagar. Retorna conta completa."""
    conta_completa = _construir_conta(conta)
    contas = carregar_contas_a_pagar()
    contas.append(conta_completa)
    salvar_json_fixo(contas, ARQUIVO_CONTAS)
    logger.info(
        f"Conta a pagar: [{conta_completa['id']}] "
        f"{conta_completa['contraparte']} | R$ {conta_completa['valor_total']:.2f}"
    )
    return conta_completa


def registrar_lote_pagar(lista: list) -> list:
    """Registra múltiplas contas a pagar em lote."""
    contas_existentes = carregar_contas_a_pagar()
    registradas = []
    for c in lista:
        try:
            conta_completa = _construir_conta(c)
            contas_existentes.append(conta_completa)
            registradas.append(conta_completa)
            logger.info(
                f"  [{conta_completa['id']}] {conta_completa['contraparte']} "
                f"| R$ {conta_completa['valor_total']:.2f} | {conta_completa['descricao']}"
            )
        except ValueError as e:
            logger.warning(f"Conta inválida ignorada: {e} | {c.get('descricao', '?')}")
    salvar_json_fixo(contas_existentes, ARQUIVO_CONTAS)
    logger.info(f"{len(registradas)} de {len(lista)} contas a pagar registradas.")
    return registradas


# ─── Atualização de status ──────────────────────────────────────────────────

def marcar_paga(conta_id: str, valor_pago: float, data: str = None) -> dict:
    """
    Registra pagamento total ou parcial de uma conta.
    - valor_pago total (>= valor_em_aberto) → status = paga
    - valor_pago parcial → status = parcial
    """
    contas = carregar_contas_a_pagar()
    for conta in contas:
        if conta["id"] == conta_id:
            novo_pago      = round(float(conta.get("valor_pago", 0)) + valor_pago, 2)
            novo_em_aberto = round(max(0.0, float(conta["valor_total"]) - novo_pago), 2)
            conta["valor_pago"]          = novo_pago
            conta["valor_em_aberto"]     = novo_em_aberto
            conta["data_pagamento"]      = data or date.today().isoformat()
            conta["status"]              = "paga" if novo_em_aberto <= 0 else "parcial"
            conta["prioridade_financeira"] = _calcular_prioridade(conta)
            conta["atualizado_em"]       = datetime.now().isoformat()
            salvar_json_fixo(contas, ARQUIVO_CONTAS)
            logger.info(
                f"Conta [{conta_id}] → {conta['status']} | "
                f"pago: R$ {novo_pago:.2f} | em aberto: R$ {novo_em_aberto:.2f}"
            )
            return conta
    raise ValueError(f"Conta a pagar não encontrada: {conta_id}")


# ─── Consultas ─────────────────────────────────────────────────────────────

def carregar_contas_a_pagar() -> list:
    """Carrega todas as contas a pagar (status gravado, sem ajuste de vencimento)."""
    return carregar_json_fixo(ARQUIVO_CONTAS, padrao=[])


def carregar_com_status_efetivo() -> list:
    """
    Carrega contas com status ajustado pelo vencimento (não persiste).
    aberta/parcial + data_vencimento < hoje → tratada como vencida para análise.
    """
    return _aplicar_vencimento(carregar_contas_a_pagar())


def listar_abertas() -> list:
    """Contas com status aberta ou parcial (após ajuste de vencimento)."""
    return [c for c in carregar_com_status_efetivo() if c["status"] in ("aberta", "parcial")]


def listar_vencidas() -> list:
    """Contas com vencimento expirado sem pagamento total."""
    return [c for c in carregar_com_status_efetivo() if c["status"] == "vencida"]


def listar_recentes(dias: int = 30) -> list:
    """Contas pagas nos últimos N dias."""
    hoje = date.today()
    resultado = []
    for c in carregar_contas_a_pagar():
        if c.get("status") == "paga" and c.get("data_pagamento"):
            try:
                if (hoje - date.fromisoformat(c["data_pagamento"])).days <= dias:
                    resultado.append(c)
            except ValueError:
                pass
    return resultado


# ─── Internos ──────────────────────────────────────────────────────────────

def _construir_conta(conta: dict) -> dict:
    for campo in CAMPOS_OBRIGATORIOS:
        if conta.get(campo) is None:
            raise ValueError(f"Campo obrigatório ausente: {campo}")

    status = conta.get("status", "aberta")
    if status not in STATUS_VALIDOS:
        raise ValueError(f"Status inválido: '{status}'. Válidos: {sorted(STATUS_VALIDOS)}")

    valor_total     = round(float(conta["valor_total"]), 2)
    valor_pago      = round(float(conta.get("valor_pago", 0.0)), 2)
    valor_em_aberto = round(max(0.0, valor_total - valor_pago), 2)

    conta_completa = {
        "id":                   conta.get("id") or str(uuid.uuid4())[:8],
        "contraparte":          conta["contraparte"],
        "descricao":            conta["descricao"],
        "valor_total":          valor_total,
        "valor_pago":           valor_pago,
        "valor_em_aberto":      valor_em_aberto,
        "data_lancamento":      conta["data_lancamento"],
        "data_vencimento":      conta["data_vencimento"],
        "data_pagamento":       conta.get("data_pagamento"),
        "status":               status,
        "categoria":            conta.get("categoria", "despesa_operacional"),
        "evento_origem_id":     conta.get("evento_origem_id"),       # rastreabilidade opcional
        "conta_relacionada_id": conta.get("conta_relacionada_id"),   # rastreabilidade opcional
        "observacoes":          conta.get("observacoes"),
        "registrado_em":        datetime.now().isoformat(),
        "atualizado_em":        datetime.now().isoformat(),
    }
    conta_completa["prioridade_financeira"] = _calcular_prioridade(conta_completa)
    return conta_completa


def _calcular_prioridade(conta: dict) -> str:
    status = conta.get("status", "aberta")
    if status in ("paga", "cancelada"):
        return "baixa"
    if status == "vencida":
        return "alta"

    valor_em_aberto = float(conta.get("valor_em_aberto", 0))
    limiar = config.FINANCEIRO_VALOR_RELEVANTE
    hoje = date.today()
    dias = None
    venc = conta.get("data_vencimento")
    if venc:
        try:
            dias = (date.fromisoformat(venc) - hoje).days
        except ValueError:
            pass

    if dias is not None and dias <= config.FINANCEIRO_DIAS_ALERTA_IMEDIATO:
        return "alta"
    if dias is not None and dias <= config.FINANCEIRO_DIAS_ALERTA_CURTO_PRAZO and valor_em_aberto >= limiar:
        return "alta"
    if dias is not None and dias <= config.FINANCEIRO_DIAS_ALERTA_CURTO_PRAZO:
        return "media"
    if valor_em_aberto >= limiar * 2:
        return "media"
    return "baixa"


def _aplicar_vencimento(contas: list) -> list:
    """Ajusta status para 'vencida' em memória se prazo expirou. Não persiste."""
    hoje = date.today()
    for c in contas:
        if c["status"] in ("aberta", "parcial") and c.get("data_vencimento"):
            try:
                if date.fromisoformat(c["data_vencimento"]) < hoje:
                    c["status"] = "vencida"
                    c["prioridade_financeira"] = "alta"
            except ValueError:
                pass
    return contas
