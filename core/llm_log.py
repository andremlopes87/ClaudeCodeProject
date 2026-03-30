"""
core/llm_log.py

Auditoria estruturada de todas as chamadas LLM do router.
Registra chamadas reais e dry-run para observabilidade e estimativa de custo.

Em dry-run: custo_estimado_usd=0 mas custo_estimado_real mostra o que
custaria se o modo real estivesse ativo — útil para decidir quando ligar.

Arquivo gerenciado: dados/log_llm.json
Arquivo de incidentes: dados/log_llm_incidentes.json
"""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_LOG        = config.PASTA_DADOS / "log_llm.json"
_ARQ_INCIDENTES = config.PASTA_DADOS / "log_llm_incidentes.json"

# Custo por 1 000 tokens (USD) — espelha os valores de llm_router.py
_CUSTO_POR_MODELO = {
    "claude-haiku-4-5-20251001": {"in": 0.00080, "out": 0.00400},
    "claude-sonnet-4-6":         {"in": 0.00300, "out": 0.01500},
    "claude-sonnet-4-20250514":  {"in": 0.00300, "out": 0.01500},
}
_CUSTO_DEFAULT = {"in": 0.00300, "out": 0.01500}  # fallback → Sonnet

# Estimativa de tokens: ~4 caracteres por token (conservador para PT-BR)
_CHARS_POR_TOKEN = 4


# ─── Interface pública ────────────────────────────────────────────────────────

def registrar_chamada_llm(dados: dict) -> None:
    """
    Registra uma chamada LLM (real ou dry-run) em dados/log_llm.json.

    Campos esperados em dados:
      agente         : str  — quem chamou
      tipo_tarefa    : str  — classificar | redigir | decidir | analisar | resumir
      modelo_usado   : str  — "dry-run" ou nome do modelo real
      modo           : str  — "dry-run" | "real"
      tokens_entrada : int  — 0 em dry-run
      tokens_saida   : int  — 0 em dry-run
      custo_estimado_usd : float — 0.0 em dry-run
      sucesso        : bool
      fallback_usado : bool
      erro           : str | None
      payload_chars  : int  — tamanho do payload serializado (para estimativa dry-run)
      modelo_simulado: str  — modelo que SERIA usado em dry-run (para custo simulado)
      ciclo_id       : str | None  — opcional
    """
    agora           = datetime.now().isoformat(timespec="seconds")
    payload_chars   = dados.get("payload_chars", 0)
    modelo_simulado = dados.get("modelo_simulado", "")
    modo            = dados.get("modo", "dry-run")

    # Custo estimado em modo real (mesmo que a chamada seja dry-run)
    custo_real = dados.get("custo_estimado_usd", 0.0)
    if modo == "dry-run" and payload_chars > 0 and modelo_simulado:
        tok_in_est  = max(1, payload_chars // _CHARS_POR_TOKEN)
        tok_out_est = max(1, tok_in_est // 2)
        tabela      = _CUSTO_POR_MODELO.get(modelo_simulado, _CUSTO_DEFAULT)
        custo_real  = (tok_in_est * tabela["in"] + tok_out_est * tabela["out"]) / 1000

    entrada = {
        "timestamp":           agora,
        "agente":              dados.get("agente", "desconhecido"),
        "tipo_tarefa":         dados.get("tipo_tarefa", "—"),
        "modelo_usado":        dados.get("modelo_usado", "dry-run"),
        "modo":                modo,
        "tokens_entrada":      dados.get("tokens_entrada", 0),
        "tokens_saida":        dados.get("tokens_saida", 0),
        "custo_estimado_usd":  dados.get("custo_estimado_usd", 0.0),
        "custo_estimado_real": round(custo_real, 8),
        "sucesso":             dados.get("sucesso", True),
        "fallback_usado":      dados.get("fallback_usado", False),
        "erro":                dados.get("erro"),
        "ciclo_id":            dados.get("ciclo_id"),
    }

    _append(entrada)


def resumo_custos_dia(data: str = None) -> dict:
    """
    Resumo de custos de um dia específico.

    Args:
      data: "YYYY-MM-DD" (padrão: hoje)

    Returns:
      total_chamadas, total_tokens, custo_total_usd (real), custo_simulado_usd,
      por_agente, por_modelo, por_tipo
    """
    if data is None:
        data = date.today().isoformat()
    historico = _ler()
    entradas  = [e for e in historico if e.get("timestamp", "").startswith(data)]
    return _calcular_resumo(entradas)


def resumo_custos_periodo(dias: int = 7) -> dict:
    """
    Resumo de custos dos últimos N dias (inclusive hoje).

    Returns:
      mesma estrutura de resumo_custos_dia
    """
    desde     = (date.today() - timedelta(days=dias - 1)).isoformat()
    historico = _ler()
    entradas  = [e for e in historico if e.get("timestamp", "") >= desde]
    return _calcular_resumo(entradas)


def carregar_log() -> list:
    """Retorna todas as entradas do log."""
    return _ler()


# ─── Cálculo de resumo ────────────────────────────────────────────────────────

def _calcular_resumo(entradas: list) -> dict:
    """Agrega métricas de custo e uso para uma lista de entradas do log."""
    total_tokens_in  = sum(e.get("tokens_entrada", 0) for e in entradas)
    total_tokens_out = sum(e.get("tokens_saida",   0) for e in entradas)
    custo_total      = sum(e.get("custo_estimado_usd",  0.0) for e in entradas)
    custo_simulado   = sum(e.get("custo_estimado_real", 0.0) for e in entradas)

    por_agente: dict = {}
    por_modelo: dict = {}
    por_tipo:   dict = {}

    for e in entradas:
        _incrementar(por_agente, e.get("agente",      "desconhecido"), e)
        _incrementar(por_modelo, e.get("modelo_usado", "dry-run"),      e)
        _incrementar(por_tipo,   e.get("tipo_tarefa",  "—"),            e)

    return {
        "total_chamadas":     len(entradas),
        "total_tokens":       total_tokens_in + total_tokens_out,
        "custo_total_usd":    round(custo_total,    8),
        "custo_simulado_usd": round(custo_simulado, 8),
        "por_agente":         por_agente,
        "por_modelo":         por_modelo,
        "por_tipo":           por_tipo,
    }


def _incrementar(grupo: dict, chave: str, entrada: dict) -> None:
    if chave not in grupo:
        grupo[chave] = {
            "chamadas":          0,
            "tokens":            0,
            "custo_usd":         0.0,
            "custo_simulado_usd": 0.0,
        }
    grupo[chave]["chamadas"] += 1
    grupo[chave]["tokens"]   += (
        entrada.get("tokens_entrada", 0) + entrada.get("tokens_saida", 0)
    )
    grupo[chave]["custo_usd"]          += entrada.get("custo_estimado_usd",  0.0)
    grupo[chave]["custo_simulado_usd"] += entrada.get("custo_estimado_real", 0.0)


# ─── I/O ──────────────────────────────────────────────────────────────────────

def _ler() -> list:
    """Lê o log. Se corrompido, registra incidente e retorna lista vazia."""
    if not _ARQ_LOG.exists():
        return []
    try:
        with open(_ARQ_LOG, encoding="utf-8") as f:
            dados = json.load(f)
            return dados if isinstance(dados, list) else []
    except Exception as exc:
        log.warning(f"[llm_log] log corrompido, criando novo: {exc}")
        _registrar_incidente(f"log_llm.json corrompido e recriado: {exc}")
        return []


def _append(entrada: dict) -> None:
    """Lê o log, adiciona entrada e salva."""
    historico = _ler()
    historico.append(entrada)
    try:
        import os
        _ARQ_LOG.parent.mkdir(parents=True, exist_ok=True)
        conteudo = json.dumps(historico, ensure_ascii=False, indent=2)
        tmp = _ARQ_LOG.with_suffix(_ARQ_LOG.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(conteudo)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _ARQ_LOG)
    except Exception as exc:
        log.warning(f"[llm_log] falha ao salvar log: {exc}")


def _registrar_incidente(msg: str) -> None:
    """Salva incidente de log em arquivo separado para auditoria."""
    try:
        incs: list = []
        if _ARQ_INCIDENTES.exists():
            try:
                incs = json.loads(_ARQ_INCIDENTES.read_text(encoding="utf-8"))
                if not isinstance(incs, list):
                    incs = []
            except Exception:
                incs = []
        incs.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "msg":       msg,
        })
        import os
        _ARQ_INCIDENTES.parent.mkdir(parents=True, exist_ok=True)
        conteudo = json.dumps(incs, ensure_ascii=False, indent=2)
        tmp = _ARQ_INCIDENTES.with_suffix(_ARQ_INCIDENTES.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(conteudo)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _ARQ_INCIDENTES)
    except Exception as _err:
        log.warning("erro ignorado: %s", _err)
