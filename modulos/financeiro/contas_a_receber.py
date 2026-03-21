"""
modulos/financeiro/contas_a_receber.py — Gestão de contas a receber.

Ciclo de vida:
  aberta → recebida (total) | parcial → recebida | vencida → recebida/cancelada

Diferença em relação a eventos:
  Contas têm lifecycle, vencimento, confirmação parcial e valor_em_aberto explícito.
  Eventos são para transações pontuais sem lifecycle (despesas não planejadas, alertas).

Campos de rastreabilidade opcionais:
  evento_origem_id    — liga esta conta a um evento que a gerou
  conta_relacionada_id — liga esta conta a outra (ex: conta a pagar relacionada)
"""

import uuid
import logging
from datetime import datetime, date

import config
from core.persistencia import carregar_json_fixo, salvar_json_fixo

logger = logging.getLogger(__name__)

ARQUIVO_CONTAS = "contas_a_receber.json"

STATUS_VALIDOS = {"aberta", "recebida", "parcial", "vencida", "cancelada"}

CAMPOS_OBRIGATORIOS = [
    "contraparte", "descricao", "valor_total", "data_emissao", "data_vencimento"
]


# ─── Registro ──────────────────────────────────────────────────────────────

def registrar_conta_a_receber(conta: dict) -> dict:
    """Valida e registra uma conta a receber. Retorna conta completa."""
    conta_completa = _construir_conta(conta)
    contas = carregar_contas_a_receber()
    contas.append(conta_completa)
    salvar_json_fixo(contas, ARQUIVO_CONTAS)
    logger.info(
        f"Conta a receber: [{conta_completa['id']}] "
        f"{conta_completa['contraparte']} | R$ {conta_completa['valor_total']:.2f}"
    )
    return conta_completa


def registrar_lote_receber(lista: list) -> list:
    """Registra múltiplas contas a receber em lote."""
    contas_existentes = carregar_contas_a_receber()
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
    logger.info(f"{len(registradas)} de {len(lista)} contas a receber registradas.")
    return registradas


# ─── Atualização de status ──────────────────────────────────────────────────

def marcar_recebida(conta_id: str, valor_recebido: float, data: str = None) -> dict:
    """
    Registra recebimento total ou parcial de uma conta.
    - valor_recebido total (>= valor_em_aberto) → status = recebida
    - valor_recebido parcial → status = parcial
    """
    contas = carregar_contas_a_receber()
    for conta in contas:
        if conta["id"] == conta_id:
            novo_recebido  = round(float(conta.get("valor_recebido", 0)) + valor_recebido, 2)
            novo_em_aberto = round(max(0.0, float(conta["valor_total"]) - novo_recebido), 2)
            conta["valor_recebido"]      = novo_recebido
            conta["valor_em_aberto"]     = novo_em_aberto
            conta["data_recebimento"]    = data or date.today().isoformat()
            conta["status"]              = "recebida" if novo_em_aberto <= 0 else "parcial"
            conta["prioridade_financeira"] = _calcular_prioridade(conta)
            conta["atualizado_em"]       = datetime.now().isoformat()
            salvar_json_fixo(contas, ARQUIVO_CONTAS)
            logger.info(
                f"Conta [{conta_id}] → {conta['status']} | "
                f"recebido: R$ {novo_recebido:.2f} | em aberto: R$ {novo_em_aberto:.2f}"
            )
            return conta
    raise ValueError(f"Conta a receber não encontrada: {conta_id}")


# ─── Consultas ─────────────────────────────────────────────────────────────

def carregar_contas_a_receber() -> list:
    """Carrega todas as contas a receber (status gravado, sem ajuste de vencimento)."""
    return carregar_json_fixo(ARQUIVO_CONTAS, padrao=[])


def carregar_com_status_efetivo() -> list:
    """
    Carrega contas com status ajustado pelo vencimento (não persiste).
    aberta/parcial + data_vencimento < hoje → tratada como vencida para análise.
    """
    return _aplicar_vencimento(carregar_contas_a_receber())


def listar_abertas() -> list:
    """Contas com status aberta ou parcial (após ajuste de vencimento)."""
    return [c for c in carregar_com_status_efetivo() if c["status"] in ("aberta", "parcial")]


def listar_vencidas() -> list:
    """Contas com vencimento expirado sem recebimento total."""
    return [c for c in carregar_com_status_efetivo() if c["status"] == "vencida"]


def listar_recentes(dias: int = 30) -> list:
    """Contas recebidas nos últimos N dias."""
    hoje = date.today()
    resultado = []
    for c in carregar_contas_a_receber():
        if c.get("status") == "recebida" and c.get("data_recebimento"):
            try:
                if (hoje - date.fromisoformat(c["data_recebimento"])).days <= dias:
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
    valor_recebido  = round(float(conta.get("valor_recebido", 0.0)), 2)
    valor_em_aberto = round(max(0.0, valor_total - valor_recebido), 2)

    conta_completa = {
        "id":                   conta.get("id") or str(uuid.uuid4())[:8],
        "contraparte":          conta["contraparte"],
        "descricao":            conta["descricao"],
        "valor_total":          valor_total,
        "valor_recebido":       valor_recebido,
        "valor_em_aberto":      valor_em_aberto,
        "data_emissao":         conta["data_emissao"],
        "data_vencimento":      conta["data_vencimento"],
        "data_recebimento":     conta.get("data_recebimento"),
        "status":               status,
        "categoria":            conta.get("categoria", "receita"),
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
    if status in ("recebida", "cancelada"):
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
