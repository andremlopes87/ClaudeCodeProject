"""
core/playbooks_cs.py

Playbooks estruturados de customer success — receitas de retenção baseadas em
padrões de risco detectados nas contas ativas.

Responsabilidade:
  Carregar playbooks do JSON configurável, avaliar gatilhos por conta,
  gerar ações concretas e registrar execuções para controle de progresso.

Sem envio real — ações ficam em fila para executor_contato ou conselho.

Arquivos gerenciados:
  dados/playbooks_customer_success.json — definição dos playbooks (editável)
  dados/historico_playbooks_cs.json     — histórico de execuções por conta
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_PLAYBOOKS = config.PASTA_DADOS / "playbooks_customer_success.json"
_ARQ_HISTORICO = config.PASTA_DADOS / "historico_playbooks_cs.json"

# Ordem de severidade para priorização por fallback
_PESO_SEVERIDADE = {"critico": 0, "risco": 1, "atencao": 2}


# ─── I/O helpers ──────────────────────────────────────────────────────────────

def _ler(arq: Path, padrao):
    try:
        if arq.exists():
            return json.loads(arq.read_text(encoding="utf-8")) or padrao
    except Exception as _err:
        log.warning("erro ignorado: %s", _err)
    return padrao


def _salvar(arq: Path, dados) -> None:
    import os
    arq.parent.mkdir(parents=True, exist_ok=True)
    conteudo = json.dumps(dados, ensure_ascii=False, indent=2)
    tmp = arq.with_suffix(arq.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, arq)


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _hoje() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ─── API pública ──────────────────────────────────────────────────────────────

def carregar_playbooks() -> list:
    """
    Lê dados/playbooks_customer_success.json.
    Retorna lista de playbooks. Nunca lança exceção.
    """
    dados = _ler(_ARQ_PLAYBOOKS, {"playbooks": []})
    return dados.get("playbooks", [])


def avaliar_playbooks(conta: dict, contexto: dict) -> list:
    """
    Avalia todos os playbooks contra o contexto da conta.

    contexto esperado:
      dias_sem_interacao          int  — dias desde último contato/acompanhamento
      parcela_atrasada_dias       int  — dias de atraso no pagamento (0 se em dia)
      dias_sem_progresso_entrega  int  — dias sem atualização em entrega ativa
      score_saude                 int  — score de saúde (0-100)
      nps_score                   int  — NPS mais recente (None se não disponível)
      feedback_sentimento         str  — "positivo" | "negativo" | "neutro" | None

    Retorna lista de playbooks ativados, ordenados por severidade (critico primeiro).
    """
    playbooks   = carregar_playbooks()
    ativados    = []

    for pb in playbooks:
        gatilho = pb.get("gatilho", {})
        if _avaliar_gatilho(gatilho, contexto):
            ativados.append(pb)
            log.debug(
                f"  [playbook] ativado: {pb['id']} | conta={conta.get('id','?')} "
                f"| gatilho={gatilho.get('tipo')}"
            )

    # Ordenar por severidade
    ativados.sort(key=lambda p: _PESO_SEVERIDADE.get(p.get("severidade", "atencao"), 99))
    return ativados


def gerar_acoes_playbook(conta_id: str, playbook: dict,
                          etapa_atual: int = 1) -> "dict | None":
    """
    Retorna a ação da etapa_atual do playbook para a conta.

    - Dedup: se a mesma ação já foi gerada hoje (mesmo conta+playbook+ordem), retorna None.
    - Se etapa_atual exceder o número de ações, retorna None (playbook concluído).

    Retorna dict com todos os campos da ação, mais metadados de rastreabilidade.
    """
    acoes_def = playbook.get("acoes", [])
    acao_def  = next((a for a in acoes_def if a.get("ordem") == etapa_atual), None)
    if not acao_def:
        return None  # etapa não existe ou playbook esgotado

    # Dedup: não gerar a mesma ação duas vezes no mesmo dia
    historico = _ler(_ARQ_HISTORICO, [])
    hoje      = _hoje()
    ja_feita  = any(
        h.get("conta_id") == conta_id
        and h.get("playbook_id") == playbook["id"]
        and h.get("acao_ordem") == etapa_atual
        and h.get("data") == hoje
        for h in historico
    )
    if ja_feita:
        log.debug(
            f"  [playbook] dedup — {playbook['id']} etapa={etapa_atual} "
            f"conta={conta_id} ja gerada hoje"
        )
        return None

    return {
        **acao_def,
        "playbook_id":   playbook["id"],
        "playbook_nome": playbook.get("nome", ""),
        "severidade":    playbook.get("severidade", "atencao"),
        "conta_id":      conta_id,
        "etapa_atual":   etapa_atual,
        "total_etapas":  len(acoes_def),
        "gerada_em":     _agora(),
    }


def registrar_execucao_acao(conta_id: str, playbook_id: str,
                              acao: dict, resultado: str) -> None:
    """
    Registra execução de uma ação em historico_playbooks_cs.json.

    resultado: "executada" | "sem_resposta" | "resolvida" | "escalada"
    """
    historico = _ler(_ARQ_HISTORICO, [])
    historico.append({
        "id":            f"hcs_{uuid.uuid4().hex[:8]}",
        "conta_id":      conta_id,
        "playbook_id":   playbook_id,
        "acao_ordem":    acao.get("ordem", acao.get("etapa_atual", 1)),
        "acao_tipo":     acao.get("tipo", ""),
        "resultado":     resultado,
        "data":          _hoje(),
        "registrado_em": _agora(),
    })
    _salvar(_ARQ_HISTORICO, historico)
    log.info(
        f"[playbook_cs] execucao registrada | conta={conta_id} "
        f"playbook={playbook_id} acao={acao.get('ordem')} resultado={resultado}"
    )


def obter_status_playbooks_conta(conta_id: str) -> list:
    """
    Retorna status atual de cada playbook para a conta:
    etapa_atual calculada a partir do histórico de execuções.

    Regras:
    - Se última execução tem resultado "resolvida" → playbook encerrado (não retorna)
    - Caso contrário: etapa_atual = max(ordem_executada) + 1
    - Se nunca executado: etapa_atual = 1
    """
    historico = _ler(_ARQ_HISTORICO, [])
    entradas  = [h for h in historico if h.get("conta_id") == conta_id]

    por_playbook: dict = {}
    for h in entradas:
        pb_id  = h.get("playbook_id", "")
        ordem  = h.get("acao_ordem", 0)
        result = h.get("resultado", "")

        if pb_id not in por_playbook:
            por_playbook[pb_id] = {"max_ordem": 0, "resolvido": False}

        if result == "resolvida":
            por_playbook[pb_id]["resolvido"] = True
        if ordem > por_playbook[pb_id]["max_ordem"]:
            por_playbook[pb_id]["max_ordem"] = ordem

    status = []
    for pb_id, info in por_playbook.items():
        if info["resolvido"]:
            continue  # playbook encerrado — não listar
        status.append({
            "playbook_id": pb_id,
            "etapa_atual": info["max_ordem"] + 1,
        })

    return status


# ─── Avaliação de gatilhos ─────────────────────────────────────────────────────

def _avaliar_gatilho(gatilho: dict, contexto: dict) -> bool:
    """
    Avalia o gatilho do playbook contra o contexto da conta.
    Usa o campo 'tipo' para despachar para a lógica correta.
    O campo 'condicao' no JSON serve como documentação.
    """
    tipo = gatilho.get("tipo")

    if tipo == "inatividade":
        return contexto.get("dias_sem_interacao", 0) >= 14

    if tipo == "financeiro":
        return contexto.get("parcela_atrasada_dias", 0) >= 7

    if tipo == "operacional":
        return contexto.get("dias_sem_progresso_entrega", 0) >= 7

    if tipo == "saude":
        return contexto.get("score_saude", 100) < 40

    if tipo == "feedback":
        nps    = contexto.get("nps_score")
        sentim = contexto.get("feedback_sentimento")
        nps_negativo = (nps is not None and nps <= 6)
        return nps_negativo or sentim == "negativo"

    log.warning(f"[playbook_cs] gatilho tipo desconhecido: '{tipo}' — ignorado")
    return False
