"""
core/orquestrador_empresa.py — Orquestrador central da empresa.

Executa todos os agentes na ordem correta, registra cada etapa e produz
um ciclo operacional auditável. Não cria agentes novos. Não faz chamadas
externas. Apenas orquestra os agentes existentes.

Ordem do ciclo (14 etapas):
  1. agente_financeiro
  2. agente_prospeccao
  3. agente_marketing
  4. agente_comercial          (importar + processar resultados)
  5. agente_operacao_entrega
  6. agente_secretario         (consolidar + criar handoffs + deliberacoes)
  7. agente_executor_contato   (preparar execucoes dos handoffs)
  8. integrador_email          (preparar emails assistidos)
  9. integrador_canais         (processar outros canais dry-run)
  10. agente_comercial         (reabsorver efeitos gerados pelo executor)
  11. gerador_insumos_desde_contato
  12. avaliador_fechamento_comercial
  13. agente_operacao_entrega
  14. agente_secretario        (fechar retrato final do ciclo)
"""

import json
import logging
import traceback
from datetime import datetime
from pathlib import Path

import config

_PASTA_CICLOS = config.PASTA_LOGS / "empresa"
_ARQ_ESTADO   = config.PASTA_DADOS / "estado_empresa.json"
_ARQ_CICLO    = config.PASTA_DADOS / "ciclo_operacional.json"


# ─── API pública ─────────────────────────────────────────────────────────────

def executar_ciclo_empresa() -> dict:
    """
    Executa um ciclo operacional completo da empresa.
    Retorna o dict do ciclo com todas as etapas e resumo.

    Confiabilidade:
      - Lock exclusivo: impede dois ciclos simultâneos
      - Checkpoints por etapa: rastreabilidade e diagnóstico
      - Incidentes automáticos em falhas relevantes
      - Saúde calculada ao fim de cada ciclo
      - Lock sempre liberado em finally
    """
    from core.confiabilidade_empresa import (
        adquirir_lock_ciclo,
        liberar_lock_ciclo,
        registrar_checkpoint_etapa,
        finalizar_checkpoint_etapa,
        registrar_incidente_operacional,
        calcular_saude_empresa,
        marcar_recovery_executado,
        etapa_ja_concluida_neste_ciclo,
    )

    _PASTA_CICLOS.mkdir(parents=True, exist_ok=True)
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)

    agora     = datetime.now()
    ts        = agora.strftime("%Y-%m-%d_%H-%M-%S")
    ciclo_id  = f"ciclo_{ts}"
    inicio_ts = agora.isoformat(timespec="seconds")

    log = _configurar_log_ciclo(ciclo_id, ts)
    log.info("=" * 64)
    log.info(f"CICLO EMPRESA — {ciclo_id}")
    log.info("=" * 64)

    # ── Lock de ciclo ─────────────────────────────────────────────────────────
    lock_adquirido = adquirir_lock_ciclo(ciclo_id)
    if not lock_adquirido:
        msg = "Lock de ciclo ativo — outro ciclo em execução. Abortando."
        log.warning(msg)
        registrar_incidente_operacional(
            tipo_incidente="reprocessamento_bloqueado",
            severidade="media",
            area="operacao",
            agente="orquestrador",
            titulo="Ciclo bloqueado por lock ativo",
            descricao=msg,
            ciclo_id=ciclo_id,
            acao_tomada="ciclo_abortado",
        )
        ciclo = _montar_ciclo_vazio(ciclo_id, inicio_ts, "bloqueado_lock", msg)
        _salvar_ciclo(ciclo)
        return ciclo

    # Marcar recovery como executado se havia recovery pendente
    marcar_recovery_executado(ciclo_id)

    try:
        # ── Falha estrutural ──────────────────────────────────────────────────
        falha = detectar_falha_estrutural()
        if falha:
            log.error(f"FALHA ESTRUTURAL: {falha}")
            registrar_incidente_operacional(
                tipo_incidente="falha_etapa",
                severidade="critica",
                area="operacao",
                agente="orquestrador",
                titulo="Falha estrutural antes de iniciar ciclo",
                descricao=falha,
                ciclo_id=ciclo_id,
                acao_tomada="ciclo_abortado",
            )
            ciclo = _montar_ciclo_vazio(ciclo_id, inicio_ts, "falha_estrutural", falha)
            _salvar_ciclo(ciclo)
            return ciclo

        # ── Políticas operacionais ────────────────────────────────────────────
        try:
            from core.politicas_empresa import derivar_e_salvar_politicas
            politicas = derivar_e_salvar_politicas()
            log.info(
                f"Politicas derivadas: modo={politicas.get('modo_empresa','?')} "
                f"| score_ganho={politicas.get('fechamento_comercial',{}).get('score_ganho','?')}"
            )
        except Exception as _e:
            log.warning(f"Falha ao derivar politicas: {_e}")
            registrar_incidente_operacional(
                tipo_incidente="politicas_inconsistentes",
                severidade="baixa",
                area="operacao",
                agente="orquestrador",
                titulo="Falha ao derivar políticas operacionais",
                descricao=str(_e),
                ciclo_id=ciclo_id,
            )

        estado = carregar_estado_empresa()
        etapas = []
        erros  = []

        # ── Governança ────────────────────────────────────────────────────────
        governanca       = _carregar_estado_governanca_seguro()
        agentes_pausados = set(governanca.get("agentes_pausados", []))
        areas_pausadas   = set(governanca.get("areas_pausadas", []))
        modo_empresa     = governanca.get("modo_empresa", "normal")
        if agentes_pausados or areas_pausadas or modo_empresa != "normal":
            log.info(
                f"GOVERNANCA ATIVA: modo={modo_empresa} | "
                f"pausados={agentes_pausados} | areas={areas_pausadas}"
            )

        # ── Sequência do ciclo ────────────────────────────────────────────────
        sequencia = [
            ("agente_financeiro",               _importar_financeiro,       "1/14"),
            ("agente_prospeccao",               _importar_prospeccao,       "2/14"),
            ("agente_marketing",                _importar_marketing,        "3/14"),
            ("agente_comercial",                _importar_comercial,        "4/14"),
            ("agente_operacao_entrega",         _importar_entrega,          "5/14"),
            ("agente_secretario",               _importar_secretario,       "6/14"),
            ("agente_executor_contato",         _importar_executor,         "7/14"),
            ("integrador_email",                _importar_integrador_email, "8/14"),
            ("integrador_canais",               _importar_integrador,       "9/14"),
            ("agente_comercial",                _importar_comercial,        "10/14"),
            ("gerador_insumos_desde_contato",   _importar_gerador,          "11/14"),
            ("avaliador_fechamento_comercial",  _importar_avaliador,        "12/14"),
            ("agente_operacao_entrega",         _importar_entrega,          "13/14"),
            ("agente_secretario",               _importar_secretario,       "14/14"),
        ]

        for nome, importador, posicao in sequencia:
            area = _AREA_DO_AGENTE.get(nome, "operacao")

            # Verificar pausa por governança
            if nome in agentes_pausados:
                log.info(f"[{posicao}] {nome} PAUSADO — pulando")
                etapa = _etapa_pausada(nome, posicao, "pausado_conselho")
                etapas.append(etapa)
                finalizar_checkpoint_etapa(ciclo_id, nome, posicao, "pulada", resumo={"motivo": "pausado_conselho"})
                continue
            if area in areas_pausadas:
                log.info(f"[{posicao}] {nome} (area '{area}' pausada) — pulando")
                etapa = _etapa_pausada(nome, posicao, f"area_{area}_pausada")
                etapas.append(etapa)
                finalizar_checkpoint_etapa(ciclo_id, nome, posicao, "pulada", resumo={"motivo": f"area_{area}_pausada"})
                continue

            # Proteção contra reprocessamento indevido na mesma posição
            if etapa_ja_concluida_neste_ciclo(ciclo_id, nome, posicao):
                log.warning(f"[{posicao}] {nome} já concluído neste ciclo — bloqueando reprocessamento")
                registrar_incidente_operacional(
                    tipo_incidente="reprocessamento_bloqueado",
                    severidade="baixa",
                    area=area,
                    agente=nome,
                    titulo=f"Reprocessamento bloqueado: {nome} [{posicao}]",
                    descricao=f"Etapa já concluída no ciclo {ciclo_id}",
                    ciclo_id=ciclo_id,
                )
                continue

            # Registrar checkpoint: inicio
            registrar_checkpoint_etapa(ciclo_id, nome, posicao)
            log.info(f"[{posicao}] Iniciando {nome}...")

            etapa = executar_etapa_agente(nome, importador, log)
            etapas.append(etapa)

            if etapa["status"] == "erro":
                erros.append({"etapa": nome, "posicao": posicao, "erro": etapa["erro"]})
                finalizar_checkpoint_etapa(
                    ciclo_id, nome, posicao, "falhou",
                    resumo=etapa.get("resumo", {}),
                    erro=etapa.get("erro"),
                )
                # Registrar incidente para falhas de agente
                registrar_incidente_operacional(
                    tipo_incidente="falha_etapa",
                    severidade="alta",
                    area=area,
                    agente=nome,
                    titulo=f"Falha no agente {nome} [{posicao}]",
                    descricao=str(etapa.get("erro", ""))[:300],
                    ciclo_id=ciclo_id,
                    referencia_id=posicao,
                    acao_tomada="ciclo_continuou_sem_agente",
                )
            else:
                finalizar_checkpoint_etapa(
                    ciclo_id, nome, posicao, "concluida",
                    resumo=etapa.get("resumo", {}),
                )

            log.info(f"[{posicao}] {nome} → {etapa['status']} ({etapa['duracao_ms']}ms)")

        # ── Resumo e persistência ─────────────────────────────────────────────
        status_geral = _calcular_status_geral(etapas)
        resumo       = montar_resumo_final_ciclo(etapas)

        ciclo = {
            "ciclo_id":      ciclo_id,
            "iniciado_em":   inicio_ts,
            "finalizado_em": datetime.now().isoformat(timespec="seconds"),
            "status_geral":  status_geral,
            "etapas":        etapas,
            "resumo_final":  resumo,
            "erros":         erros,
            "observacoes":   f"{len(erros)} erro(s) em {len(etapas)} etapas",
        }

        _salvar_ciclo(ciclo)
        estado = _atualizar_estado_empresa(estado, ciclo)
        salvar_estado_empresa(estado)

        # ── Observabilidade ───────────────────────────────────────────────────
        try:
            from core.observabilidade_empresa import executar_observabilidade
            executar_observabilidade()
        except Exception as exc:
            log.warning(f"Observabilidade nao atualizada: {exc}")

        # ── Saúde da empresa ──────────────────────────────────────────────────
        try:
            saude = calcular_saude_empresa()
            log.info(
                f"Saude calculada: {saude['status_geral']} "
                f"(score={saude['score_saude']}) | alertas={len(saude['alertas'])}"
            )
        except Exception as exc:
            log.warning(f"Saude nao calculada: {exc}")

        log.info("=" * 64)
        log.info(f"CICLO CONCLUIDO — {status_geral}")
        log.info(f"  deliberacoes pendentes     : {resumo.get('deliberacoes_pendentes', '?')}")
        log.info(f"  handoffs pendentes         : {resumo.get('handoffs_pendentes', '?')}")
        log.info(f"  pipeline (oportunidades)   : {resumo.get('pipeline_total', '?')}")
        log.info(f"  follow-ups para integracao : {resumo.get('followups_aguardando_integracao', '?')}")
        log.info(f"  riscos financeiros         : {resumo.get('riscos_financeiros', '?')}")
        log.info(f"  erros no ciclo             : {len(erros)}")
        log.info("=" * 64)

        return ciclo

    finally:
        # Sempre liberar o lock, mesmo em exceção inesperada
        liberar_lock_ciclo(ciclo_id)


def executar_etapa_agente(nome: str, importador, log) -> dict:
    """
    Executa um agente de forma segura com try/except.
    Captura qualquer exceção sem derrubar o ciclo inteiro.
    Retorna dict com nome, status, resumo, erro, duracao_ms.
    """
    inicio = datetime.now()
    try:
        fn       = importador()
        resultado = fn()
        duracao  = int((datetime.now() - inicio).total_seconds() * 1000)
        return {
            "nome_agente":   nome,
            "iniciado_em":   inicio.isoformat(timespec="seconds"),
            "finalizado_em": datetime.now().isoformat(timespec="seconds"),
            "status":        "ok",
            "resumo":        resultado,
            "erro":          None,
            "duracao_ms":    duracao,
        }
    except Exception as exc:
        duracao = int((datetime.now() - inicio).total_seconds() * 1000)
        tb      = traceback.format_exc()
        log.error(f"  [{nome}] ERRO — {exc}\n{tb}")
        return {
            "nome_agente":   nome,
            "iniciado_em":   inicio.isoformat(timespec="seconds"),
            "finalizado_em": datetime.now().isoformat(timespec="seconds"),
            "status":        "erro",
            "resumo":        {},
            "erro":          str(exc),
            "duracao_ms":    duracao,
        }


def detectar_falha_estrutural() -> str | None:
    """
    Verifica pré-condições mínimas antes de iniciar o ciclo.
    Retorna mensagem de erro ou None se tudo OK.
    """
    if not config.BASE_DIR.exists():
        return f"BASE_DIR nao encontrado: {config.BASE_DIR}"
    try:
        config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return f"Nao foi possivel garantir PASTA_DADOS: {exc}"
    return None


def montar_resumo_final_ciclo(etapas: list) -> dict:
    """
    Extrai métricas-chave dos resultados dos agentes.
    Usa a última execução de cada agente (quando rodado mais de uma vez no ciclo).
    Complementa com leitura direta dos arquivos de dados para maior precisão.
    """
    # Pegar último resumo bem-sucedido por agente
    por_agente: dict[str, dict] = {}
    for etapa in etapas:
        if etapa["status"] == "ok":
            por_agente[etapa["nome_agente"]] = etapa["resumo"]

    fin  = por_agente.get("agente_financeiro", {})
    prs  = por_agente.get("agente_prospeccao", {})
    mkt  = por_agente.get("agente_marketing", {})
    com  = por_agente.get("agente_comercial", {})
    ent  = por_agente.get("agente_operacao_entrega", {})
    ger  = por_agente.get("gerador_insumos_desde_contato", {})
    exe  = por_agente.get("agente_executor_contato", {})
    intg = por_agente.get("integrador_canais", {})
    eml  = por_agente.get("integrador_email", {})
    aval = por_agente.get("avaliador_fechamento_comercial", {})

    return {
        "deliberacoes_pendentes":          _contar_deliberacoes_pendentes(),
        "handoffs_pendentes":              _contar_handoffs_pendentes(),
        "pipeline_total":                  com.get("pipeline_total", 0),
        "followups_aguardando_integracao": _contar_followups_aguardando_integracao(),
        "riscos_financeiros":              fin.get("total_riscos", 0),
        "risco_caixa":                     fin.get("risco_caixa", False),
        "saldo_atual":                     fin.get("saldo_atual", 0.0),
        "leads_prospectados_no_ciclo":     prs.get("prontas_para_handoff", 0),
        "mkt_handoffs_criados":            mkt.get("handoffs_criados", 0),
        "mkt_importadas":                  mkt.get("importadas", 0),
        "oportunidades_novas_no_ciclo":    com.get("oportunidades_novas", 0),
        "resultados_aplicados":            com.get("resultados_aplicados", 0),
        "entregas_abertas":                ent.get("abertas", 0),
        "entregas_pipeline_total":         ent.get("pipeline_entrega", 0),
        "insumos_gerados_auto":            ger.get("insumos_gerados", 0),
        "insumos_aplicados":               ent.get("insumos_aplicados", 0),
        "execucoes_preparadas":            exe.get("preparados", 0),
        "resultados_gerados_integrador":   intg.get("resultados_gerados", 0),
        "emails_preparados_no_ciclo":      eml.get("preparados", 0),
        "emails_bloqueados_no_ciclo":      eml.get("bloqueados", 0),
        "promovidos_ganho":                aval.get("promovidos_ganho", 0),
        "promovidos_pronto_para_entrega":  aval.get("promovidos_pronto", 0),
        "escalados_fechamento":            aval.get("escalados", 0),
        "erros_no_ciclo":                  sum(1 for e in etapas if e["status"] == "erro"),
    }


def carregar_estado_empresa() -> dict:
    if not _ARQ_ESTADO.exists():
        return _estado_empresa_inicial()
    with open(_ARQ_ESTADO, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_estado_empresa(estado: dict) -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    with open(_ARQ_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


# ─── Importadores lazy ────────────────────────────────────────────────────────
# Retornam a função executar() de cada agente. Lazy para evitar importação
# antecipada que poderia registrar loggers antes do ciclo estar pronto.

def _importar_financeiro():
    from agentes.financeiro.agente_financeiro import executar
    return executar

def _importar_comercial():
    from agentes.comercial.agente_comercial import executar
    return executar

def _importar_secretario():
    from agentes.secretario.agente_secretario import executar
    return executar

def _importar_executor():
    from agentes.executor_contato.agente_executor_contato import executar
    return executar

def _importar_integrador():
    from core.integrador_canais import executar
    return executar

def _importar_integrador_email():
    from core.integrador_email import executar
    return executar

def _importar_prospeccao():
    from agentes.prospeccao.agente_prospeccao import executar
    return executar

def _importar_marketing():
    from agentes.marketing.agente_marketing import executar
    return executar

def _importar_entrega():
    from agentes.operacao_entrega.agente_operacao_entrega import executar
    return executar

def _importar_gerador():
    from modulos.entrega.gerador_insumos_desde_contato import executar
    return executar

def _importar_avaliador():
    from modulos.comercial.avaliador_fechamento_comercial import executar
    return executar


# ─── Leitura de dados para resumo ────────────────────────────────────────────

def _contar_handoffs_pendentes() -> int:
    arq = config.PASTA_DADOS / "handoffs_agentes.json"
    if not arq.exists():
        return 0
    with open(arq, "r", encoding="utf-8") as f:
        return sum(1 for h in json.load(f) if h.get("status") == "pendente")


def _contar_deliberacoes_pendentes() -> int:
    arq = config.PASTA_DADOS / "deliberacoes_conselho.json"
    if not arq.exists():
        return 0
    with open(arq, "r", encoding="utf-8") as f:
        return sum(1 for d in json.load(f) if d.get("status") in ("pendente", "em_analise"))


def _contar_followups_aguardando_integracao() -> int:
    arq = config.PASTA_DADOS / "fila_execucao_contato.json"
    if not arq.exists():
        return 0
    with open(arq, "r", encoding="utf-8") as f:
        return sum(1 for e in json.load(f) if e.get("pronto_para_integracao"))


# ─── Status e persistência ────────────────────────────────────────────────────

def _calcular_status_geral(etapas: list) -> str:
    executadas = [e for e in etapas if e["status"] != "pausado"]
    n_erros = sum(1 for e in executadas if e["status"] == "erro")
    n_pausados = sum(1 for e in etapas if e["status"] == "pausado")
    base = len(executadas) if executadas else 1
    if n_erros == 0:
        return "concluido_com_pausas" if n_pausados else "concluido"
    if n_erros < base // 2:
        return "concluido_com_alertas"
    if n_erros < base:
        return "falha_parcial"
    return "falha_estrutural"


def _configurar_log_ciclo(ciclo_id: str, ts: str) -> logging.Logger:
    caminho = _PASTA_CICLOS / f"ciclo_empresa_{ts}.log"
    log = logging.getLogger(ciclo_id)
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        fh = logging.FileHandler(caminho, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        log.addHandler(sh)
    return log


def _salvar_ciclo(ciclo: dict) -> None:
    """Persiste o último ciclo em ciclo_operacional.json."""
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    with open(_ARQ_CICLO, "w", encoding="utf-8") as f:
        json.dump(ciclo, f, ensure_ascii=False, indent=2)


def _atualizar_estado_empresa(estado: dict, ciclo: dict) -> dict:
    resumo = ciclo.get("resumo_final", {})
    estado["ultimo_ciclo_id"]        = ciclo["ciclo_id"]
    estado["ultima_execucao"]         = ciclo["finalizado_em"]
    estado["status_empresa"]          = ciclo["status_geral"]
    estado["agentes_ativos"]          = [
        "agente_financeiro",
        "agente_comercial",
        "agente_secretario",
        "agente_executor_contato",
    ]
    estado["ultima_ordem_execucao"]   = [e["nome_agente"] for e in ciclo["etapas"]]
    estado["contadores_basicos"]      = {
        "pipeline_total":            resumo.get("pipeline_total", 0),
        "handoffs_pendentes":        resumo.get("handoffs_pendentes", 0),
        "deliberacoes_pendentes":    resumo.get("deliberacoes_pendentes", 0),
        "riscos_financeiros":        resumo.get("riscos_financeiros", 0),
        "followups_para_integracao": resumo.get("followups_aguardando_integracao", 0),
    }
    estado["ultimo_resumo"] = resumo
    return estado


# ─── Governança ───────────────────────────────────────────────────────────────

_AREA_DO_AGENTE = {
    "agente_financeiro":              "financeiro",
    "agente_prospeccao":              "prospeccao",
    "agente_marketing":               "marketing",
    "agente_comercial":               "comercial",
    "agente_secretario":              "operacao",
    "agente_executor_contato":        "comercial",
    "integrador_email":               "comercial",
    "integrador_canais":              "comercial",
    "agente_operacao_entrega":        "entrega",
    "gerador_insumos_desde_contato":  "entrega",
    "avaliador_fechamento_comercial": "comercial",
}


def _carregar_estado_governanca_seguro() -> dict:
    try:
        from core.governanca_conselho import carregar_estado_governanca
        return carregar_estado_governanca()
    except Exception:
        return {}


def _etapa_pausada(nome: str, posicao: str, motivo: str) -> dict:
    agora = datetime.now().isoformat(timespec="seconds")
    return {
        "nome_agente":   nome,
        "iniciado_em":   agora,
        "finalizado_em": agora,
        "status":        "pausado",
        "resumo":        {},
        "erro":          None,
        "duracao_ms":    0,
        "motivo_pausa":  motivo,
    }


def _estado_empresa_inicial() -> dict:
    return {
        "ultimo_ciclo_id":        None,
        "ultima_execucao":        None,
        "status_empresa":         "nao_iniciado",
        "agentes_ativos":         [],
        "ultima_ordem_execucao":  [],
        "contadores_basicos":     {},
        "ultimo_resumo":          {},
    }


def _montar_ciclo_vazio(ciclo_id: str, inicio_ts: str, status: str, observacao: str) -> dict:
    return {
        "ciclo_id":      ciclo_id,
        "iniciado_em":   inicio_ts,
        "finalizado_em": datetime.now().isoformat(timespec="seconds"),
        "status_geral":  status,
        "etapas":        [],
        "resumo_final":  {},
        "erros":         [{"erro": observacao}],
        "observacoes":   observacao,
    }
