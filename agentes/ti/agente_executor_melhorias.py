"""
agentes/ti/agente_executor_melhorias.py

Agente executor de melhorias da Vetor.

Este e o UNICO agente que modifica codigo no projeto.
Tem mais guardas que qualquer outro agente.

Responsabilidade:
  Consumir recomendacoes do auditor de seguranca e do analisador de qualidade,
  aplicar as mudancas com seguranca (backup, testes, rollback automatico).

Regras criticas:
  - Maximo 3 mudancas por execucao (configuravel, nunca > 10)
  - NUNCA alterar: orquestrador, governanca, scheduler, .env, main_scheduler
  - SEMPRE backup ANTES de qualquer mudanca
  - SEMPRE testes DEPOIS de qualquer mudanca
  - SEMPRE reverter se qualquer teste falhar
  - NUNCA aplicar mudanca de alto risco sem aprovacao do conselho
  - Em dry-run: NUNCA aplicar — apenas simular e registrar

Etapas:
  1. Carregar recomendacoes pendentes
  2. Classificar por risco de execucao
  3. Planejar mudancas (LLM ou mecanico)
  4. Executar mudancas (com guardas) — ou simular em dry-run
  5. Gerar relatorio de execucao
  6. Escalar ao conselho
  7. Atualizar memoria

Arquivos gerenciados:
  dados/relatorio_melhorias.json    — relatorio mais recente
  dados/historico_melhorias.json    — historico append-only
  dados/handoffs_agentes.json       — handoffs consumidos/atualizados
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import config
from core.llm_router import LLMRouter
from core.llm_memoria import atualizar_memoria_agente
from core.controle_agente import configurar_log_agente
from core.guardas_codigo import (
    criar_backup_pre_mudanca,
    verificar_integridade_pos_mudanca,
    reverter_mudanca,
    validar_mudanca_proposta,
)

# ─── Constantes ───────────────────────────────────────────────────────────────

NOME_AGENTE  = "agente_executor_melhorias"
_ROOT        = Path(__file__).parent.parent.parent

_ARQ_REL_SEG  = config.PASTA_DADOS / "relatorio_seguranca.json"
_ARQ_REL_QUAL = config.PASTA_DADOS / "relatorio_qualidade.json"
_ARQ_HANDOFFS = config.PASTA_DADOS / "handoffs_agentes.json"
_ARQ_HIST_MEL = config.PASTA_DADOS / "historico_melhorias.json"
_ARQ_REL_MEL  = config.PASTA_DADOS / "relatorio_melhorias.json"
_ARQ_DELIBS   = config.PASTA_DADOS / "deliberacoes_conselho.json"

_MAX_MUDANCAS_PADRAO = 3
_MAX_MUDANCAS_LIMITE = 10

log = logging.getLogger(NOME_AGENTE)


# ─── Ponto de entrada ─────────────────────────────────────────────────────────

def executar(dry_run: bool = False, max_mudancas: int = _MAX_MUDANCAS_PADRAO) -> dict:
    """
    Executa o ciclo completo do agente executor de melhorias.

    dry_run: True = planeja mas nao aplica nada (status = "simulada").
    max_mudancas: limite de mudancas por execucao.
    Retorna resumo do ciclo.
    """
    _, _ = configurar_log_agente(NOME_AGENTE)

    # Garantir limite de seguranca
    max_mudancas = min(max_mudancas, _MAX_MUDANCAS_LIMITE)

    # Forcar dry-run se LLM em modo simulado
    modo_llm = getattr(config, "LLM_MODO", "dry-run")
    if modo_llm == "dry-run":
        dry_run = True
        log.info("[executor] LLM em dry-run — modo simulacao ativado automaticamente")

    modo_str = "DRY-RUN" if dry_run else "REAL"
    log.info(f"[executor] iniciando ciclo | modo={modo_str} | max_mudancas={max_mudancas}")

    # ETAPA 1 — Carregar pendentes
    log.info("[executor] etapa 1 — carregando recomendacoes pendentes")
    pendentes = _etapa1_carregar_pendentes()
    log.info(f"[executor] {len(pendentes)} recomendacoes pendentes encontradas")

    # ETAPA 2 — Classificar por risco
    log.info("[executor] etapa 2 — classificando por risco")
    classificadas = _etapa2_classificar(pendentes)

    # ETAPA 3 — Planejar (respeita max_mudancas)
    log.info("[executor] etapa 3 — planejando mudancas")
    planos = _etapa3_planejar(classificadas, max_mudancas, dry_run)

    # ETAPA 4 — Executar (ou simular)
    log.info(f"[executor] etapa 4 — {'simulando' if dry_run else 'aplicando'} mudancas")
    resultados = _etapa4_executar(planos, dry_run)

    # ETAPA 5 — Relatorio
    log.info("[executor] etapa 5 — gerando relatorio")
    relatorio = _etapa5_relatorio(resultados, dry_run)

    # ETAPA 6 — Escaladas ao conselho
    log.info("[executor] etapa 6 — escalando ao conselho")
    n_escaladas = _etapa6_escalar(classificadas["alto"])

    # ETAPA 7 — Memoria
    log.info("[executor] etapa 7 — atualizando memoria")
    _etapa7_memoria(relatorio, dry_run)

    resumo = {
        "data_execucao":            relatorio["data_execucao"],
        "modo":                     modo_str,
        "recomendacoes_processadas": relatorio["recomendacoes_processadas"],
        "aplicadas_com_sucesso":    relatorio["aplicadas_com_sucesso"],
        "revertidas":               relatorio["revertidas"],
        "escaladas_conselho":       n_escaladas,
        "pendentes_llm_real":       relatorio["pendentes_llm_real"],
        "simuladas":                relatorio.get("simuladas", 0),
        "puladas":                  relatorio["puladas"],
    }
    log.info(
        f"[executor] ciclo concluido — aplicadas={resumo['aplicadas_com_sucesso']} "
        f"revertidas={resumo['revertidas']} escaladas={resumo['escaladas_conselho']}"
    )
    return resumo


# ─── ETAPA 1 — Carregar pendentes ─────────────────────────────────────────────

def _etapa1_carregar_pendentes() -> list:
    """
    Lê relatórios de segurança, qualidade e handoffs.
    Filtra apenas itens ainda não executados.
    Retorna lista normalizada de recomendações.
    """
    ja_executados = _ids_ja_executados()
    pendentes: list = []

    # --- Relatório de segurança ---
    if _ARQ_REL_SEG.exists():
        try:
            rel = json.loads(_ARQ_REL_SEG.read_text(encoding="utf-8"))
            for v in rel.get("vulnerabilidades", []):
                vid = v.get("id", "")
                if vid and vid not in ja_executados:
                    sev = v.get("severidade", "medio")
                    pendentes.append({
                        "id":              vid,
                        "origem":          "seguranca",
                        "prioridade":      _sev_para_prioridade(sev),
                        "categoria":       v.get("categoria", ""),
                        "arquivo":         v.get("arquivo", ""),
                        "linha":           v.get("linha", 0),
                        "descricao":       v.get("descricao", ""),
                        "acao_sugerida":   v.get("recomendacao", ""),
                        "risco_correcao":  v.get("risco_correcao", "medio"),
                        "esforco":         v.get("esforco_estimado", "medio"),
                    })
        except Exception as exc:
            log.warning(f"[executor] falha ao ler relatorio_seguranca: {exc}")

    # --- Relatório de qualidade ---
    if _ARQ_REL_QUAL.exists():
        try:
            rel = json.loads(_ARQ_REL_QUAL.read_text(encoding="utf-8"))
            for r in rel.get("recomendacoes", []):
                rid = r.get("id", "")
                if rid and rid not in ja_executados:
                    pendentes.append({
                        "id":             rid,
                        "origem":         "qualidade",
                        "prioridade":     r.get("prioridade", "media"),
                        "categoria":      r.get("categoria", ""),
                        "arquivo":        "",
                        "linha":          0,
                        "descricao":      r.get("descricao", ""),
                        "acao_sugerida":  r.get("acao_sugerida", ""),
                        "risco_correcao": r.get("risco_correcao", "medio"),
                        "esforco":        r.get("esforco_estimado", "medio"),
                    })
        except Exception as exc:
            log.warning(f"[executor] falha ao ler relatorio_qualidade: {exc}")

    # --- Handoffs destinados a este agente ---
    if _ARQ_HANDOFFS.exists():
        try:
            handoffs = json.loads(_ARQ_HANDOFFS.read_text(encoding="utf-8"))
            for h in handoffs:
                # Suportar dois formatos de handoff
                destino = h.get("destino") or h.get("agente_destino", "")
                if destino != NOME_AGENTE:
                    continue
                hid = h.get("id", "")
                if hid and hid not in ja_executados:
                    payload = h.get("payload", {})
                    recs = payload.get("recomendacoes", []) if "recomendacoes" in payload else [payload]
                    for rec in recs:
                        if not rec:
                            continue
                        pendentes.append({
                            "id":             f"{hid}_{rec.get('rec_id', uuid.uuid4().hex[:8])}",
                            "origem":         "handoff",
                            "prioridade":     h.get("prioridade", rec.get("prioridade", "media")),
                            "categoria":      rec.get("categoria", ""),
                            "arquivo":        rec.get("arquivo", ""),
                            "linha":          0,
                            "descricao":      rec.get("descricao", ""),
                            "acao_sugerida":  rec.get("acao", rec.get("acao_sugerida", "")),
                            "risco_correcao": rec.get("risco", rec.get("risco_correcao", "medio")),
                            "esforco":        rec.get("esforco", "medio"),
                        })
        except Exception as exc:
            log.warning(f"[executor] falha ao ler handoffs: {exc}")

    # Deduplicar por id
    vistos: set = set()
    unicos = []
    for p in pendentes:
        if p["id"] not in vistos:
            vistos.add(p["id"])
            unicos.append(p)

    return unicos


def _ids_ja_executados() -> set:
    """Retorna conjunto de ids já presentes no histórico de melhorias."""
    if not _ARQ_HIST_MEL.exists():
        return set()
    try:
        hist = json.loads(_ARQ_HIST_MEL.read_text(encoding="utf-8"))
        return {e.get("rec_id", "") for e in hist if e.get("rec_id")}
    except Exception:
        return set()


# ─── ETAPA 2 — Classificar por risco ─────────────────────────────────────────

def _etapa2_classificar(pendentes: list) -> dict:
    """
    Separa recomendações em três grupos por risco_correcao.
    Também aplica prioridade: critico > alto > medio.
    Nunca inclui baixo/informativo no grupo automatico.
    """
    baixo: list  = []
    medio: list  = []
    alto:  list  = []

    for rec in pendentes:
        risco = rec.get("risco_correcao", "medio")
        prio  = rec.get("prioridade", "media")

        # Ignorar informativas e baixas de forma automatica
        if prio in ("baixo", "informativo"):
            continue

        if risco == "baixo":
            baixo.append(rec)
        elif risco == "medio":
            medio.append(rec)
        else:
            alto.append(rec)

    # Ordenar por prioridade dentro de cada grupo
    _ordem_prio = {"critico": 0, "alta": 1, "medio": 2, "media": 2, "baixo": 3}
    for grupo in (baixo, medio, alto):
        grupo.sort(key=lambda r: _ordem_prio.get(r.get("prioridade", "media"), 4))

    log.info(f"[executor] classificados: baixo={len(baixo)} medio={len(medio)} alto={len(alto)}")
    return {"baixo": baixo, "medio": medio, "alto": alto}


# ─── ETAPA 3 — Planejar mudancas ─────────────────────────────────────────────

def _etapa3_planejar(classificadas: dict, max_mudancas: int, dry_run: bool) -> list:
    """
    Cria planos de execucao para risco baixo e medio.
    Alto: nao planejar — serao escalados.
    Respeita limite max_mudancas.
    """
    planos: list = []
    router = LLMRouter()

    candidatos = classificadas["baixo"] + classificadas["medio"]
    candidatos = candidatos[:max_mudancas]

    for rec in candidatos:
        risco = rec.get("risco_correcao", "medio")

        # risco medio sem LLM real: registrar como pendente_llm_real
        if risco == "medio" and dry_run:
            planos.append({
                "rec":      rec,
                "tipo":     "pendente_llm_real",
                "descricao_plano": "Aguarda LLM real para gerar plano seguro de refatoracao",
                "mudanca":  None,
            })
            continue

        # Tentar gerar plano via LLM
        plano_llm = _planejar_com_llm(router, rec)

        if plano_llm:
            planos.append({
                "rec":             rec,
                "tipo":            "llm",
                "descricao_plano": plano_llm.get("plano", ""),
                "mudanca":         plano_llm.get("mudanca"),
            })
        elif risco == "baixo":
            # Fallback mecanico para risco baixo
            plano_mec = _planejar_mecanico(rec)
            planos.append({
                "rec":             rec,
                "tipo":            "mecanico",
                "descricao_plano": plano_mec.get("descricao", ""),
                "mudanca":         plano_mec.get("mudanca"),
            })
        else:
            planos.append({
                "rec":             rec,
                "tipo":            "pendente_llm_real",
                "descricao_plano": "LLM nao gerou plano valido; aguarda modo real",
                "mudanca":         None,
            })

    return planos


def _planejar_com_llm(router: LLMRouter, rec: dict) -> "dict | None":
    """Solicita plano de mudanca ao LLM. Retorna None em dry-run."""
    try:
        ctx = {
            "rec_id":       rec["id"],
            "descricao":    rec["descricao"],
            "acao":         rec["acao_sugerida"],
            "arquivo":      rec.get("arquivo", ""),
            "risco":        rec.get("risco_correcao", "medio"),
            "instrucao": (
                "Gerar plano de mudanca minimo e seguro para esta recomendacao. "
                "Descrever: arquivo a alterar, tipo de alteracao, linhas aproximadas. "
                "Maximo 3 frases. Se nao for possivel de forma segura, responder 'nao_aplicavel'."
            ),
        }
        resultado = router.decidir(ctx)
        texto = resultado.get("decisao") or resultado.get("texto") or ""
        if not texto or "nao_aplicavel" in texto.lower():
            return None
        return {"plano": texto[:300], "mudanca": None}
    except Exception:
        return None


def _planejar_mecanico(rec: dict) -> dict:
    """
    Gera plano mecanico para recomendacoes de risco baixo.
    Suporta: requirements.txt sem versao fixada.
    """
    descricao = rec.get("descricao", "").lower()
    acao      = rec.get("acao_sugerida", "")

    # Caso: versao nao fixada em requirements.txt
    if "versao" in descricao and "requirements" in descricao:
        return {
            "descricao": f"Fixar versao em requirements.txt: {acao[:80]}",
            "mudanca": {
                "tipo":           "requirements_fixar_versao",
                "arquivo_alvo":   str(_ROOT / "requirements.txt"),
                "linhas_alteradas": 1,
                "contexto":       acao,
            },
        }

    return {
        "descricao": f"Melhoria planejada: {acao[:80]}",
        "mudanca":   None,
    }


# ─── ETAPA 4 — Executar mudancas ─────────────────────────────────────────────

def _etapa4_executar(planos: list, dry_run: bool) -> list:
    """
    Aplica (ou simula) cada plano individualmente.
    Nunca aplica em lote — sempre um de cada vez com guardas.
    """
    resultados: list = []

    for plano in planos:
        rec    = plano["rec"]
        tipo   = plano["tipo"]
        mudanca = plano.get("mudanca")

        # Casos que nao envolvem aplicacao
        if tipo == "pendente_llm_real":
            resultados.append(_resultado_pendente(rec, plano["descricao_plano"]))
            continue

        if mudanca is None:
            resultados.append(_resultado_simulado(rec, plano["descricao_plano"]))
            continue

        if dry_run:
            resultados.append(_resultado_simulado(rec, plano["descricao_plano"]))
            continue

        # Aplicacao real (apenas quando dry_run=False e mudanca definida)
        resultado = _aplicar_com_guardas(rec, mudanca, plano["descricao_plano"])
        resultados.append(resultado)

    return resultados


def _aplicar_com_guardas(rec: dict, mudanca: dict, descricao_plano: str) -> dict:
    """
    Aplica uma mudanca com guardas completas:
    validar → backup → aplicar → verificar → (rollback se falhou)
    """
    arquivo_alvo = mudanca.get("arquivo_alvo", "")
    mel_id       = f"mel_{uuid.uuid4().hex[:8]}"
    agora        = datetime.now().isoformat(timespec="seconds")

    # a) Validar
    validacao = validar_mudanca_proposta(arquivo_alvo, mudanca)
    if not validacao["permitida"]:
        log.warning(f"[executor] mudanca bloqueada: {validacao['motivo']}")
        return {
            "id":           mel_id,
            "rec_id":       rec["id"],
            "arquivo":      arquivo_alvo,
            "descricao":    descricao_plano,
            "status":       "pulada",
            "motivo":       validacao["motivo"],
            "backup_path":  None,
            "testes_pos":   None,
            "timestamp":    agora,
        }

    # b) Backup
    backup_path = criar_backup_pre_mudanca()

    # c) Aplicar mudanca
    erro_aplicacao = _aplicar_mudanca_arquivo(mudanca)
    if erro_aplicacao:
        # Nao conseguiu aplicar — rollback preventivo
        reverter_mudanca(backup_path)
        log.error(f"[executor] falha ao aplicar mudanca: {erro_aplicacao}")
        return {
            "id":          mel_id,
            "rec_id":      rec["id"],
            "arquivo":     arquivo_alvo,
            "descricao":   descricao_plano,
            "status":      "revertida",
            "motivo":      f"Erro ao aplicar: {erro_aplicacao}",
            "backup_path": backup_path,
            "testes_pos":  None,
            "timestamp":   agora,
        }

    # d) Verificar integridade
    integridade = verificar_integridade_pos_mudanca(backup_path)

    if integridade["integro"]:
        log.info(f"[executor] mudanca aplicada com sucesso: {rec['id']}")
        _registrar_historico(mel_id, rec["id"], arquivo_alvo, "aplicada", backup_path, agora)
        return {
            "id":          mel_id,
            "rec_id":      rec["id"],
            "arquivo":     arquivo_alvo,
            "descricao":   descricao_plano,
            "status":      "aplicada",
            "motivo":      None,
            "backup_path": backup_path,
            "testes_pos": {
                "passaram": integridade["testes_passaram"],
                "falharam": integridade["testes_falharam"],
            },
            "timestamp":   agora,
        }
    else:
        # e) Reverter
        log.warning(f"[executor] integridade falhou — revertendo: {integridade['erros'][:2]}")
        reverter_mudanca(backup_path)
        _registrar_historico(mel_id, rec["id"], arquivo_alvo, "revertida", backup_path, agora)
        return {
            "id":          mel_id,
            "rec_id":      rec["id"],
            "arquivo":     arquivo_alvo,
            "descricao":   descricao_plano,
            "status":      "revertida",
            "motivo":      " | ".join(integridade["erros"][:3]),
            "backup_path": backup_path,
            "testes_pos": {
                "passaram": integridade["testes_passaram"],
                "falharam": integridade["testes_falharam"],
            },
            "timestamp":   agora,
        }


def _aplicar_mudanca_arquivo(mudanca: dict) -> "str | None":
    """
    Aplica a mudanca em disco. Retorna None se ok, mensagem de erro se falhou.
    Suporta: requirements_fixar_versao.
    """
    tipo         = mudanca.get("tipo", "")
    arquivo_alvo = Path(mudanca.get("arquivo_alvo", ""))

    if tipo == "requirements_fixar_versao":
        return _fixar_versao_requirements(arquivo_alvo, mudanca.get("contexto", ""))

    return f"Tipo de mudanca nao suportado mecanicamente: {tipo}"


def _fixar_versao_requirements(arq: Path, contexto: str) -> "str | None":
    """
    Tenta fixar a versao de uma dependencia em requirements.txt.
    Usa 'pip show' para obter a versao instalada.
    """
    import subprocess, sys, re

    if not arq.exists():
        return f"Arquivo nao encontrado: {arq}"

    # Extrair nome do pacote do contexto
    # contexto tem formato como: "Fixar versao exata: mudar para 'anthropic==anthropic'"
    pacote_match = re.search(r"'([a-zA-Z0-9_\-]+)", contexto)
    if not pacote_match:
        return "Nao foi possivel extrair nome do pacote do contexto"

    nome_pacote = pacote_match.group(1)

    # Obter versao instalada
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "show", nome_pacote],
            capture_output=True, text=True, timeout=15,
        )
        versao_match = re.search(r"^Version:\s+(.+)$", proc.stdout, re.MULTILINE)
        if not versao_match:
            return f"Versao de '{nome_pacote}' nao encontrada via pip show"
        versao = versao_match.group(1).strip()
    except Exception as exc:
        return f"Erro ao consultar pip: {exc}"

    # Atualizar requirements.txt
    try:
        linhas = arq.read_text(encoding="utf-8").splitlines(keepends=True)
        novas  = []
        alterado = False
        for linha in linhas:
            ln_strip = linha.strip()
            if not ln_strip or ln_strip.startswith("#"):
                novas.append(linha)
                continue
            nome_ln = re.split(r"[>=<!;\[]", ln_strip)[0].strip().lower()
            if nome_ln == nome_pacote.lower() and "==" not in ln_strip:
                novas.append(f"{nome_pacote}>={versao}\n")
                alterado = True
            else:
                novas.append(linha)
        if not alterado:
            return f"Linha de '{nome_pacote}' nao encontrada em requirements.txt"
        arq.write_text("".join(novas), encoding="utf-8")
        return None
    except Exception as exc:
        return f"Erro ao escrever requirements.txt: {exc}"


# ─── Helpers de resultado ─────────────────────────────────────────────────────

def _resultado_simulado(rec: dict, descricao_plano: str) -> dict:
    return {
        "id":          f"mel_{uuid.uuid4().hex[:8]}",
        "rec_id":      rec["id"],
        "arquivo":     rec.get("arquivo", ""),
        "descricao":   descricao_plano or rec.get("acao_sugerida", "")[:100],
        "status":      "simulada",
        "motivo":      "dry-run ativo",
        "backup_path": None,
        "testes_pos":  None,
        "timestamp":   datetime.now().isoformat(timespec="seconds"),
    }


def _resultado_pendente(rec: dict, motivo: str) -> dict:
    return {
        "id":          f"mel_{uuid.uuid4().hex[:8]}",
        "rec_id":      rec["id"],
        "arquivo":     rec.get("arquivo", ""),
        "descricao":   rec.get("acao_sugerida", "")[:100],
        "status":      "pendente",
        "motivo":      motivo,
        "backup_path": None,
        "testes_pos":  None,
        "timestamp":   datetime.now().isoformat(timespec="seconds"),
    }


# ─── ETAPA 5 — Relatorio ─────────────────────────────────────────────────────

def _etapa5_relatorio(resultados: list, dry_run: bool) -> dict:
    """Salva relatorio de execucao e appenda no historico."""
    agora     = datetime.now().isoformat(timespec="seconds")
    contadores = {s: 0 for s in ("aplicada", "revertida", "simulada", "pendente", "pulada")}
    for r in resultados:
        s = r.get("status", "pulada")
        contadores[s] = contadores.get(s, 0) + 1

    relatorio = {
        "data_execucao":             agora,
        "modo":                      "dry-run" if dry_run else "real",
        "recomendacoes_processadas": len(resultados),
        "aplicadas_com_sucesso":     contadores["aplicada"],
        "revertidas":                contadores["revertida"],
        "simuladas":                 contadores["simulada"],
        "pendentes_llm_real":        contadores["pendente"],
        "puladas":                   contadores["pulada"],
        "mudancas":                  resultados,
    }

    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    _ARQ_REL_MEL.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Historico append
    hist: list = []
    if _ARQ_HIST_MEL.exists():
        try:
            hist = json.loads(_ARQ_HIST_MEL.read_text(encoding="utf-8"))
        except Exception:
            hist = []

    # Appenda apenas resumo (nao duplicar dados grandes)
    hist.append({
        "data":                  agora,
        "modo":                  relatorio["modo"],
        "processadas":           relatorio["recomendacoes_processadas"],
        "aplicadas":             relatorio["aplicadas_com_sucesso"],
        "revertidas":            relatorio["revertidas"],
        "simuladas":             relatorio["simuladas"],
        "pendentes_llm_real":    relatorio["pendentes_llm_real"],
        "puladas":               relatorio["puladas"],
    })
    _ARQ_HIST_MEL.write_text(
        json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    log.info(f"[executor] relatorio salvo: {_ARQ_REL_MEL}")
    return relatorio


# ─── ETAPA 6 — Escalar ao conselho ────────────────────────────────────────────

def _etapa6_escalar(alto: list) -> int:
    """Cria deliberacoes para recomendacoes de alto risco."""
    if not alto:
        return 0

    escaladas = 0
    try:
        from core.deliberacoes import criar_ou_atualizar_deliberacao
        agora = datetime.now().isoformat(timespec="seconds")
        for rec in alto:
            item = {
                "item_id":       f"exec_{rec['id']}",
                "agente_origem": NOME_AGENTE,
                "tipo":          "melhoria_alto_risco",
                "descricao":     rec["descricao"],
                "acao_sugerida": rec["acao_sugerida"],
                "urgencia":      "media",
            }
            criar_ou_atualizar_deliberacao(item)
            escaladas += 1
    except Exception as exc:
        log.warning(f"[executor] falha ao escalar ao conselho: {exc}")

    log.info(f"[executor] {escaladas} recomendacoes de alto risco escaladas ao conselho")
    return escaladas


# ─── ETAPA 7 — Memoria ───────────────────────────────────────────────────────

def _etapa7_memoria(relatorio: dict, dry_run: bool) -> None:
    """Atualiza memoria do agente."""
    atualizar_memoria_agente(NOME_AGENTE, {
        "ultima_execucao":       relatorio["data_execucao"],
        "modo":                  relatorio["modo"],
        "aplicadas_total":       relatorio["aplicadas_com_sucesso"],
        "revertidas_total":      relatorio["revertidas"],
        "pendentes_llm_real":    relatorio["pendentes_llm_real"],
        "resumo": (
            f"Ultima execucao ({relatorio['modo']}): "
            f"{relatorio['recomendacoes_processadas']} processadas, "
            f"{relatorio['aplicadas_com_sucesso']} aplicadas, "
            f"{relatorio['revertidas']} revertidas."
        ),
    })


# ─── Historico de melhorias ───────────────────────────────────────────────────

def _registrar_historico(mel_id: str, rec_id: str, arquivo: str,
                         status: str, backup_path: str, timestamp: str) -> None:
    """Registra execucao no historico append-only."""
    hist: list = []
    if _ARQ_HIST_MEL.exists():
        try:
            hist = json.loads(_ARQ_HIST_MEL.read_text(encoding="utf-8"))
        except Exception:
            hist = []

    # Append com rec_id para deduplicacao futura
    hist.append({
        "mel_id":     mel_id,
        "rec_id":     rec_id,
        "arquivo":    arquivo,
        "status":     status,
        "backup":     backup_path,
        "timestamp":  timestamp,
    })
    try:
        _ARQ_HIST_MEL.write_text(
            json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as exc:
        log.warning(f"[executor] falha ao salvar historico: {exc}")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _sev_para_prioridade(sev: str) -> str:
    mapa = {"critico": "critico", "alto": "alta", "medio": "media",
            "baixo": "baixa", "informativo": "informativo"}
    return mapa.get(sev, "media")
