"""
agentes/customer_success/agente_customer_success.py

Agente dedicado à retenção e saúde das contas ativas da Vetor.

Responsabilidade:
  Monitorar contas em cliente_ativo / cliente_em_implantacao,
  detectar risco de churn, sugerir ações de retenção e
  identificar oportunidades de expansão.

Autonomia:
  Pode sozinho: calcular saúde, gerar ações de retenção,
  sugerir expansões, atualizar memória.
  Não pode: cancelar contratos, descontar sem aprovação humana,
  enviar comunicação diretamente.

Arquivos produzidos:
  dados/acoes_customer_success.json      — ações geradas por conta
  dados/relatorio_customer_success.json  — relatório do ciclo
  dados/estado_agente_customer_success.json (via controle_agente)
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import config
from core.llm_router import LLMRouter
from core.politicas_empresa import carregar_politicas
from core.controle_agente import (
    carregar_estado,
    configurar_log_agente,
    salvar_estado,
)
from core.acompanhamento_contas import (
    calcular_saude_conta,
    atualizar_saude_conta,
    sugerir_expansao_para_conta,
    criar_oportunidade_expansao,
)

NOME_AGENTE = "agente_customer_success"

_ARQ_CONTAS    = config.PASTA_DADOS / "contas_clientes.json"
_ARQ_ENTREGA   = config.PASTA_DADOS / "pipeline_entrega.json"
_ARQ_ACOES     = config.PASTA_DADOS / "acoes_customer_success.json"
_ARQ_RELATORIO = config.PASTA_DADOS / "relatorio_customer_success.json"

_STATUS_ATIVOS = {"cliente_ativo", "cliente_em_implantacao"}

# Status que requerem diagnóstico LLM (não excelente)
_STATUS_DIAGNOSTICO = {"boa", "atencao", "critica"}
# Status que acionam playbook de risco
_STATUS_RISCO = {"atencao", "critica"}

# Playbooks por status de saúde
_PLAYBOOKS = {
    "critica": [
        {"acao": "contato_urgente",     "descricao": "Contato imediato — conta em estado critico, risco alto de churn"},
        {"acao": "reuniao_recuperacao", "descricao": "Agendar reuniao de recuperacao com o decisor da conta"},
    ],
    "atencao": [
        {"acao": "checkin_proativo",    "descricao": "Check-in proativo para entender necessidades e resolver bloqueios"},
    ],
    "boa": [
        {"acao": "acompanhamento_regular", "descricao": "Manter acompanhamento periodico — conta estavel"},
    ],
}


# ─── I/O helpers ──────────────────────────────────────────────────────────────

def _ler(arq: Path, padrao):
    try:
        if arq.exists():
            return json.loads(arq.read_text(encoding="utf-8")) or padrao
    except Exception:
        pass
    return padrao


def _salvar(arq: Path, dados) -> None:
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _hoje() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ─── Ponto de entrada público ─────────────────────────────────────────────────

def executar() -> dict:
    """
    Executa o ciclo do agente de customer success.
    Retorna resumo da execução.
    """
    log, _ = configurar_log_agente(NOME_AGENTE)
    log.info("=" * 60)
    log.info(f"AGENTE CUSTOMER SUCCESS — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    politicas    = carregar_politicas()
    modo_empresa = politicas.get("modo_empresa", "normal")
    log.info(f"Politicas carregadas: modo={modo_empresa}")

    estado = carregar_estado(NOME_AGENTE)
    router = LLMRouter()

    # ── ETAPA 1: Carregar contas ativas ────────────────────────────────────────
    log.info("  [ETAPA 1] Carregando contas ativas...")
    contas_todas     = _ler(_ARQ_CONTAS, [])
    pipeline_entrega = _ler(_ARQ_ENTREGA, [])

    contas_ativas = [
        c for c in contas_todas
        if c.get("status_relacionamento") in _STATUS_ATIVOS
    ]
    log.info(f"  contas ativas encontradas: {len(contas_ativas)}")

    if not contas_ativas:
        log.info("  sem contas ativas — ciclo encerrado sem acoes")
        resultado = {
            "contas_avaliadas":    0,
            "saude_media":         0,
            "contas_risco":        0,
            "acoes_geradas":       0,
            "expansoes_sugeridas": 0,
            "narrativa_llm":       None,
        }
        salvar_estado(NOME_AGENTE, {**estado, "ultimo_resumo": resultado})
        return resultado

    # ── ETAPA 2: Avaliar saúde de cada conta ───────────────────────────────────
    log.info("  [ETAPA 2] Calculando saude de cada conta...")
    saudes: dict = {}  # conta_id → saude dict
    for conta in contas_ativas:
        conta_id = conta["id"]
        saude    = calcular_saude_conta(conta_id, pipeline_entrega)
        atualizar_saude_conta(conta_id, saude)
        saudes[conta_id] = saude
        log.info(
            f"  conta={conta.get('nome_empresa', '?')[:30]!r} "
            f"score={saude['score_saude']} status={saude['status_saude']}"
        )

    scores      = [s["score_saude"] for s in saudes.values()]
    saude_media = round(sum(scores) / len(scores), 1) if scores else 0
    log.info(f"  saude media do portfolio: {saude_media}")

    # ── ETAPA 3: LLM — diagnóstico para contas não-excelentes ─────────────────
    log.info("  [ETAPA 3] Diagnostico LLM para contas em atencao/risco...")
    for conta in contas_ativas:
        conta_id = conta["id"]
        saude    = saudes[conta_id]
        if saude["status_saude"] not in _STATUS_DIAGNOSTICO:
            continue  # excelente — sem diagnóstico necessário

        try:
            res = router.analisar({
                "agente": NOME_AGENTE,
                "tarefa": "diagnostico_saude_conta",
                "dados": {
                    "conta":               conta.get("nome_empresa", ""),
                    "categoria":           conta.get("categoria", ""),
                    "score_saude":         saude["score_saude"],
                    "status_saude":        saude["status_saude"],
                    "motivos":             saude.get("motivos", []),
                    "entregas_concluidas": saude.get("entregas_concluidas", 0),
                    "entregas_bloqueadas": saude.get("entregas_bloqueadas", 0),
                    "risco_churn":         saude.get("risco_churn", False),
                },
                "empresa_id": conta_id,
            })
            if res["sucesso"] and not res["fallback_usado"]:
                saudes[conta_id]["diagnostico_llm"] = res["resultado"]
                log.info(f"  [llm] diagnostico gerado para conta={conta_id}")
        except Exception as exc:
            log.warning(f"  [llm] falha no diagnostico para {conta_id}: {exc}")

    # ── ETAPA 4: Aplicar playbooks de risco ────────────────────────────────────
    log.info("  [ETAPA 4] Aplicando playbooks de risco...")
    acoes_geradas = _aplicar_playbooks_risco(contas_ativas, saudes, log)
    log.info(f"  acoes de risco geradas: {acoes_geradas}")

    # ── ETAPA 5: Detectar oportunidades de expansão ────────────────────────────
    log.info("  [ETAPA 5] Detectando oportunidades de expansao...")
    expansoes_criadas = _detectar_expansoes(contas_ativas, saudes, pipeline_entrega, router, log)
    log.info(f"  expansoes sugeridas: {expansoes_criadas}")

    # ── ETAPA 6: Gerar relatório de CS ─────────────────────────────────────────
    log.info("  [ETAPA 6] Gerando relatorio de CS...")
    contas_risco  = sum(1 for s in saudes.values() if s["status_saude"] in _STATUS_RISCO)
    narrativa_llm = None
    try:
        res = router.resumir({
            "agente":              NOME_AGENTE,
            "tarefa":              "relatorio_customer_success",
            "contas_ativas":       len(contas_ativas),
            "saude_media":         saude_media,
            "contas_risco":        contas_risco,
            "acoes_geradas":       acoes_geradas,
            "expansoes_sugeridas": expansoes_criadas,
            "modo_empresa":        modo_empresa,
        })
        if res["sucesso"] and not res["fallback_usado"]:
            narrativa_llm = res["resultado"]
            log.info("  [llm] narrativa CS gerada")
    except Exception as exc:
        log.warning(f"  [llm] falha na narrativa CS: {exc}")

    relatorio = {
        "data":                _hoje(),
        "timestamp":           _agora(),
        "contas_ativas":       len(contas_ativas),
        "saude_media":         saude_media,
        "contas_risco":        contas_risco,
        "acoes_geradas":       acoes_geradas,
        "expansoes_sugeridas": expansoes_criadas,
        "narrativa_llm":       narrativa_llm,
        "agente":              NOME_AGENTE,
    }
    _salvar(_ARQ_RELATORIO, relatorio)
    log.info(f"  relatorio salvo: {_ARQ_RELATORIO.name}")

    # ── ETAPA 7: Atualizar memória ─────────────────────────────────────────────
    try:
        from core.llm_memoria import atualizar_memoria_agente, atualizar_memoria_conta
        atualizar_memoria_agente(NOME_AGENTE, {
            "contas_ativas":       len(contas_ativas),
            "saude_media":         saude_media,
            "contas_risco":        contas_risco,
            "acoes_geradas":       acoes_geradas,
            "expansoes_sugeridas": expansoes_criadas,
        })
        for conta in contas_ativas:
            conta_id = conta["id"]
            saude    = saudes.get(conta_id, {})
            atualizar_memoria_conta(conta_id, {
                "resumo":      f"CS: score={saude.get('score_saude','?')} status={saude.get('status_saude','?')}",
                "saude_cs":    saude.get("status_saude"),
                "score_cs":    saude.get("score_saude"),
                "risco_churn": saude.get("risco_churn", False),
            })
    except Exception as exc:
        log.warning(f"  memoria nao atualizada: {exc}")

    resultado = {
        "contas_avaliadas":    len(contas_ativas),
        "saude_media":         saude_media,
        "contas_risco":        contas_risco,
        "acoes_geradas":       acoes_geradas,
        "expansoes_sugeridas": expansoes_criadas,
        "narrativa_llm":       narrativa_llm,
    }

    salvar_estado(NOME_AGENTE, {**estado, "ultimo_resumo": resultado})

    log.info("=" * 60)
    log.info(
        f"CS CONCLUIDO — contas={len(contas_ativas)} "
        f"saude_media={saude_media} risco={contas_risco} "
        f"acoes={acoes_geradas} expansoes={expansoes_criadas}"
    )
    log.info("=" * 60)

    return resultado


# ─── ETAPA 4: Aplicar playbooks de risco ──────────────────────────────────────

def _aplicar_playbooks_risco(contas: list, saudes: dict, log) -> int:
    """
    Para contas em risco/critica (e boa como acompanhamento), gera ação concreta.
    Nunca duplica ação para a mesma conta no mesmo dia.
    Retorna quantidade de ações geradas.
    """
    acoes   = _ler(_ARQ_ACOES, [])
    hoje    = _hoje()
    n_novas = 0

    for conta in contas:
        conta_id = conta["id"]
        saude    = saudes.get(conta_id, {})
        status   = saude.get("status_saude", "boa")

        # Excelente — sem playbook necessário
        if status == "excelente":
            continue

        # Dedup: não duplicar ação para mesma conta no mesmo dia
        ja_tem_hoje = any(
            a.get("conta_id") == conta_id and a.get("data") == hoje
            for a in acoes
        )
        if ja_tem_hoje:
            log.info(f"  dedup: {conta_id} ja tem acao hoje — pulando")
            continue

        playbook_status = status if status in _PLAYBOOKS else "boa"
        for pb in _PLAYBOOKS[playbook_status]:
            acao = {
                "id":             f"cs_{uuid.uuid4().hex[:8]}",
                "conta_id":       conta_id,
                "conta_nome":     conta.get("nome_empresa", ""),
                "data":           hoje,
                "timestamp":      _agora(),
                "status_saude":   status,
                "score_saude":    saude.get("score_saude", 0),
                "acao":           pb["acao"],
                "descricao":      pb["descricao"],
                "diagnostico_llm": saude.get("diagnostico_llm", ""),
                "status_acao":    "pendente",
                "origem":         NOME_AGENTE,
            }
            acoes.append(acao)
            n_novas += 1
            log.info(
                f"  acao gerada: {pb['acao']} | "
                f"conta={conta.get('nome_empresa', '?')[:25]!r} | status={status}"
            )

    _salvar(_ARQ_ACOES, acoes)
    return n_novas


# ─── ETAPA 5: Detectar expansões ──────────────────────────────────────────────

def _detectar_expansoes(contas: list, saudes: dict, pipeline_entrega: list,
                         router: LLMRouter, log) -> int:
    """
    Para contas excelentes com potencial de expansão, avalia momento via LLM.
    Cria oportunidade de expansão quando decisão é 'expandir_agora'.
    Fallback: conta excelente com acompanhamento há >30 dias → expandir_agora.
    Retorna quantidade de expansões criadas.
    """
    n_expansoes = 0

    for conta in contas:
        conta_id = conta["id"]
        saude    = saudes.get(conta_id, {})

        if saude.get("status_saude") != "excelente":
            continue
        if not saude.get("potencial_expansao", False):
            continue

        sugestoes = sugerir_expansao_para_conta(conta_id, pipeline_entrega)
        if not sugestoes:
            continue

        for sug in sugestoes:
            decisao_llm = "esperar"  # fallback conservador
            try:
                res = router.decidir({
                    "agente": NOME_AGENTE,
                    "tarefa": "avaliar_momento_expansao",
                    "dados": {
                        "conta":         conta.get("nome_empresa", ""),
                        "score_saude":   saude["score_saude"],
                        "tipo_expansao": sug.get("tipo_oportunidade", ""),
                        "oferta":        sug.get("oferta_sugerida", ""),
                        "motivo":        sug.get("motivo", ""),
                        "opcoes":        ["expandir_agora", "esperar", "nao_aplicavel"],
                    },
                    "empresa_id": conta_id,
                })
                if res["sucesso"] and not res["fallback_usado"]:
                    resultado_llm = res.get("resultado", "esperar")
                    if isinstance(resultado_llm, str) and resultado_llm in (
                        "expandir_agora", "esperar", "nao_aplicavel"
                    ):
                        decisao_llm = resultado_llm
                    log.info(f"  [llm] expansao decisao={decisao_llm} conta={conta_id}")
            except Exception as exc:
                log.warning(f"  [llm] falha na decisao de expansao {conta_id}: {exc}")
                # Fallback: conta excelente com acompanhamento há >30 dias
                ultima = conta.get("ultimo_acompanhamento_em", "")
                if ultima:
                    try:
                        dias = (datetime.now() - datetime.fromisoformat(ultima)).days
                        if dias > 30:
                            decisao_llm = "expandir_agora"
                            log.info(f"  [fallback] expansao por regra ({dias} dias sem acompanhamento)")
                    except Exception:
                        pass

            if decisao_llm == "expandir_agora":
                # Pegar referência da primeira entrega concluída
                entrega_id = next(
                    (e.get("id", "") for e in pipeline_entrega
                     if e.get("conta_id") == conta_id
                     and e.get("status_entrega") in ("concluida", "entregue", "finalizada")),
                    "",
                )
                criar_oportunidade_expansao(conta_id, entrega_id, sug, NOME_AGENTE)
                n_expansoes += 1
                log.info(
                    f"  expansao criada: {sug.get('tipo_oportunidade')} | "
                    f"conta={conta.get('nome_empresa', '?')[:25]!r}"
                )

    return n_expansoes
