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

_ARQ_CONTAS       = config.PASTA_DADOS / "contas_clientes.json"
_ARQ_ENTREGA      = config.PASTA_DADOS / "pipeline_entrega.json"
_ARQ_ACOES        = config.PASTA_DADOS / "acoes_customer_success.json"
_ARQ_RELATORIO    = config.PASTA_DADOS / "relatorio_customer_success.json"
_ARQ_RECEBIVEIS   = config.PASTA_DADOS / "recebiveis.json"
_ARQ_ACOMPS       = config.PASTA_DADOS / "acompanhamentos_contas.json"

_STATUS_ATIVOS      = {"cliente_ativo", "cliente_em_implantacao"}
_STATUS_DIAGNOSTICO = {"boa", "atencao", "critica"}
_STATUS_RISCO       = {"atencao", "critica"}

# Peso de severidade para priorização por fallback
_PESO_SEV = {"critico": 0, "risco": 1, "atencao": 2}


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

    # ── ETAPA 2b: NPS — programar pesquisas para contas elegíveis ─────────────
    log.info("  [ETAPA 2b] Verificando NPS devidos...")
    nps_programados = _programar_nps_ciclo(contas_ativas, saudes, log)
    log.info(f"  NPS programados: {nps_programados}")

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
    acoes_geradas = _aplicar_playbooks_risco(contas_ativas, saudes, pipeline_entrega, router, log)
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
        "nps_programados":     nps_programados,
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
        "nps_programados":     nps_programados,
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

def _aplicar_playbooks_risco(contas: list, saudes: dict, pipeline_entrega: list,
                              router: LLMRouter, log) -> int:
    """
    Avalia playbooks configuráveis para cada conta ativa.
    Usa LLM para priorizar quando múltiplos playbooks ativam na mesma conta.
    Fallback: ordena por severidade (critico > risco > atencao).
    Nunca duplica ação para mesma conta + playbook no mesmo dia.
    Retorna quantidade de ações geradas.
    """
    from core.playbooks_cs import (
        avaliar_playbooks,
        gerar_acoes_playbook,
        obter_status_playbooks_conta,
    )

    acoes_cs = _ler(_ARQ_ACOES, [])
    hoje     = _hoje()
    n_novas  = 0

    for conta in contas:
        conta_id = conta["id"]
        saude    = saudes.get(conta_id, {})

        # Montar contexto para avaliação de gatilhos
        contexto = _montar_contexto_cs(conta, saude, pipeline_entrega)

        # Avaliar quais playbooks disparam para esta conta
        playbooks_ativados = avaliar_playbooks(conta, contexto)
        if not playbooks_ativados:
            continue

        log.info(
            f"  conta={conta.get('nome_empresa','?')[:25]!r} — "
            f"{len(playbooks_ativados)} playbook(s) ativado(s): "
            f"{[p['id'] for p in playbooks_ativados]}"
        )

        # LLM: priorizar quando múltiplos playbooks ativam
        if len(playbooks_ativados) > 1:
            try:
                res = router.decidir({
                    "agente": NOME_AGENTE,
                    "tarefa": "priorizar_playbooks",
                    "dados": {
                        "conta":     conta.get("nome_empresa", ""),
                        "playbooks": [
                            {"id": p["id"], "nome": p["nome"], "severidade": p["severidade"]}
                            for p in playbooks_ativados
                        ],
                        "contexto":  contexto,
                    },
                    "empresa_id": conta_id,
                })
                if res["sucesso"] and not res["fallback_usado"]:
                    log.info(f"  [llm] priorizacao de playbooks para conta={conta_id}")
                # Playbooks já vêm ordenados por severidade de avaliar_playbooks — LLM pode refinar
                # mas sem reordenação automática aqui (dry-run não retorna ordem útil)
            except Exception as exc:
                log.warning(f"  [llm] falha na priorizacao de playbooks {conta_id}: {exc}")
            # Fallback: já estão ordenados por severidade (critico primeiro)

        # Obter etapa atual de cada playbook para esta conta
        status_playbooks = obter_status_playbooks_conta(conta_id)
        etapas_map = {s["playbook_id"]: s["etapa_atual"] for s in status_playbooks}

        for pb in playbooks_ativados:
            etapa_atual = etapas_map.get(pb["id"], 1)
            acao        = gerar_acoes_playbook(conta_id, pb, etapa_atual)
            if not acao:
                log.info(f"  dedup ou esgotado: {pb['id']} etapa={etapa_atual} conta={conta_id}")
                continue

            entrada = {
                "id":             f"cs_{uuid.uuid4().hex[:8]}",
                "conta_id":       conta_id,
                "conta_nome":     conta.get("nome_empresa", ""),
                "data":           hoje,
                "timestamp":      _agora(),
                "status_saude":   saude.get("status_saude", ""),
                "score_saude":    saude.get("score_saude", 0),
                "playbook_id":    pb["id"],
                "playbook_nome":  pb["nome"],
                "severidade":     pb["severidade"],
                "acao_ordem":     acao["ordem"],
                "acao_tipo":      acao["tipo"],
                "acao_canal":     acao.get("canal", ""),
                "acao_template":  acao.get("template", ""),
                "descricao":      acao.get("descricao", ""),
                "prazo_dias":     acao.get("prazo_dias", 1),
                "total_etapas":   acao.get("total_etapas", 1),
                "diagnostico_llm": saude.get("diagnostico_llm", ""),
                "status_acao":    "pendente",
                "origem":         NOME_AGENTE,
            }
            acoes_cs.append(entrada)
            n_novas += 1
            log.info(
                f"  acao gerada: playbook={pb['id']} etapa={acao['ordem']} "
                f"tipo={acao['tipo']} | conta={conta.get('nome_empresa','?')[:25]!r}"
            )

    _salvar(_ARQ_ACOES, acoes_cs)
    return n_novas


def _montar_contexto_cs(conta: dict, saude: dict, pipeline_entrega: list) -> dict:
    """
    Monta o dict de contexto usado pelos gatilhos dos playbooks.
    Nunca lança exceção — valores ausentes ficam como 0/None.
    """
    hoje = datetime.now()

    # dias_sem_interacao: a partir de ultimo_acompanhamento_em na conta
    dias_sem_interacao = 0
    ultima = conta.get("ultimo_acompanhamento_em") or conta.get("ultima_interacao_em")
    if ultima:
        try:
            dias_sem_interacao = (hoje - datetime.fromisoformat(ultima)).days
        except Exception:
            pass
    else:
        # Sem registro de interação → considerar inativo desde criação
        criado = conta.get("criado_em", "")
        if criado:
            try:
                dias_sem_interacao = (hoje - datetime.fromisoformat(criado)).days
            except Exception:
                pass

    # dias_sem_progresso_entrega: entregas em execução sem atualização
    conta_id = conta["id"]
    dias_sem_progresso = 0
    entregas_em_exec = [
        e for e in pipeline_entrega
        if e.get("conta_id") == conta_id
        and e.get("status_entrega") in ("onboarding", "em_execucao", "aguardando_insumo")
    ]
    for ent in entregas_em_exec:
        atualizado = ent.get("atualizado_em", ent.get("registrado_em", ""))
        if atualizado:
            try:
                dias = (hoje - datetime.fromisoformat(atualizado)).days
                dias_sem_progresso = max(dias_sem_progresso, dias)
            except Exception:
                pass

    # parcela_atrasada_dias: lê recebiveis.json se disponível
    parcela_atrasada_dias = 0
    try:
        rec_dados = _ler(_ARQ_RECEBIVEIS, [])
        if isinstance(rec_dados, dict):
            rec_dados = rec_dados.get("recebiveis", [])
        for rec in rec_dados:
            if rec.get("conta_id") != conta_id:
                continue
            if rec.get("status") not in ("em_aberto", "atrasado", "pendente"):
                continue
            venc = rec.get("data_vencimento", "")
            if not venc:
                continue
            try:
                atraso = (hoje - datetime.fromisoformat(venc)).days
                if atraso > 0:
                    parcela_atrasada_dias = max(parcela_atrasada_dias, atraso)
            except Exception:
                pass
    except Exception:
        pass

    # nps_score e feedback_sentimento: do acompanhamento mais recente
    nps_score          = None
    feedback_sentimento = None
    try:
        acomps = _ler(_ARQ_ACOMPS, [])
        acomps_conta = [
            a for a in acomps
            if a.get("conta_id") == conta_id and a.get("status") != "arquivado"
        ]
        if acomps_conta:
            mais_recente = max(
                acomps_conta,
                key=lambda a: a.get("atualizado_em", a.get("registrado_em", "")),
            )
            nps_score = mais_recente.get("nps_opcional")
            sat = mais_recente.get("satisfacao", "")
            if sat == "baixa":
                feedback_sentimento = "negativo"
            elif sat == "alta":
                feedback_sentimento = "positivo"
            elif sat:
                feedback_sentimento = "neutro"
    except Exception:
        pass

    return {
        "dias_sem_interacao":         dias_sem_interacao,
        "parcela_atrasada_dias":      parcela_atrasada_dias,
        "dias_sem_progresso_entrega": dias_sem_progresso,
        "score_saude":                saude.get("score_saude", 60),
        "nps_score":                  nps_score,
        "feedback_sentimento":        feedback_sentimento,
    }


# ─── ETAPA 2b: NPS ────────────────────────────────────────────────────────────

def _programar_nps_ciclo(contas: list, saudes: dict, log) -> int:
    """
    Chama verificar_nps_devidos() e programa NPS para contas elegíveis.
    Não envia para contas em risco/critico.
    Retorna quantidade de NPS programados neste ciclo.
    """
    try:
        from core.nps_feedback import verificar_nps_devidos, programar_nps
        devidos = verificar_nps_devidos()
        n = 0
        for item in devidos:
            resultado = programar_nps(item["conta_id"], item["gatilho"])
            if resultado:
                n += 1
                log.info(
                    f"  [nps] programado: conta={item['conta_id']} "
                    f"gatilho={item['gatilho']} motivo={item.get('motivo','')[:50]}"
                )
        return n
    except Exception as exc:
        log.warning(f"  [nps] falha ao programar ciclo NPS: {exc}")
        return 0


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
