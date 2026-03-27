"""
core/politicas_empresa.py — Traduz governança do conselho em políticas operacionais.

Lê estado_governanca_conselho.json + diretrizes_conselho.json e deriva
politicas_operacionais.json com thresholds e comportamentos ajustados por modo.

Cada agente lê as políticas no início de sua execução via carregar_politicas().
Não há acoplamento direto: os agentes lêem o arquivo gerado.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

# ─── Arquivos ──────────────────────────────────────────────────────────────────

_ARQ_ESTADO_GOV    = "estado_governanca_conselho.json"
_ARQ_DIRETRIZES    = "diretrizes_conselho.json"
_ARQ_POLITICAS     = "politicas_operacionais.json"
_ARQ_HIST_POLITICAS = "historico_aplicacao_politicas.json"


# ─── Políticas padrão por modo ─────────────────────────────────────────────────

_POLITICAS_POR_MODO: dict = {
    "normal": {
        "financeiro": {
            "urgencias_escalamento": ["imediata", "alta"],
            "escalar_alertas_urgencia": ["imediata"],
        },
        "comercial": {
            "foco_curto_prazo": False,
            "ordenar_por_linhas_priorizadas": True,
        },
        "fechamento_comercial": {
            "score_ganho": 8,
            "score_pronto": 5,
            "exigir_escopo_para_ganho": False,
        },
        "prospeccao": {
            "limite_novas_por_ciclo": 0,   # 0 = sem limite
            "ritmo": "normal",
        },
        "marketing": {
            "complexidades_sensiveis": ["alta", "muito_alta"],
            "rigor_deliberacao": "normal",
        },
        "entrega": {
            "priorizar_desbloqueio": False,
        },
    },
    "conservador": {
        "financeiro": {
            "urgencias_escalamento": ["imediata", "alta", "media"],
            "escalar_alertas_urgencia": ["imediata", "alta"],
        },
        "comercial": {
            "foco_curto_prazo": True,
            "ordenar_por_linhas_priorizadas": True,
        },
        "fechamento_comercial": {
            "score_ganho": 9,
            "score_pronto": 6,
            "exigir_escopo_para_ganho": True,
        },
        "prospeccao": {
            "limite_novas_por_ciclo": 10,
            "ritmo": "reduzido",
        },
        "marketing": {
            "complexidades_sensiveis": ["media", "alta", "muito_alta"],
            "rigor_deliberacao": "alto",
        },
        "entrega": {
            "priorizar_desbloqueio": True,
        },
    },
    "foco_caixa": {
        "financeiro": {
            "urgencias_escalamento": ["imediata", "alta", "media"],
            "escalar_alertas_urgencia": ["imediata", "alta"],
        },
        "comercial": {
            "foco_curto_prazo": True,
            "ordenar_por_linhas_priorizadas": True,
        },
        "fechamento_comercial": {
            "score_ganho": 8,
            "score_pronto": 5,
            "exigir_escopo_para_ganho": True,
        },
        "prospeccao": {
            "limite_novas_por_ciclo": 5,
            "ritmo": "reduzido",
        },
        "marketing": {
            "complexidades_sensiveis": ["media", "alta", "muito_alta"],
            "rigor_deliberacao": "maximo",
        },
        "entrega": {
            "priorizar_desbloqueio": True,
        },
    },
    "foco_crescimento": {
        "financeiro": {
            "urgencias_escalamento": ["imediata"],
            "escalar_alertas_urgencia": ["imediata"],
        },
        "comercial": {
            "foco_curto_prazo": False,
            "ordenar_por_linhas_priorizadas": True,
        },
        "fechamento_comercial": {
            "score_ganho": 7,
            "score_pronto": 4,
            "exigir_escopo_para_ganho": False,
        },
        "prospeccao": {
            "limite_novas_por_ciclo": 0,
            "ritmo": "alto",
        },
        "marketing": {
            "complexidades_sensiveis": ["alta", "muito_alta"],
            "rigor_deliberacao": "normal",
        },
        "entrega": {
            "priorizar_desbloqueio": False,
        },
    },
    "manutencao": {
        "financeiro": {
            "urgencias_escalamento": ["imediata", "alta", "media"],
            "escalar_alertas_urgencia": ["imediata", "alta"],
        },
        "comercial": {
            "foco_curto_prazo": True,
            "ordenar_por_linhas_priorizadas": True,
        },
        "fechamento_comercial": {
            "score_ganho": 9,
            "score_pronto": 7,
            "exigir_escopo_para_ganho": True,
        },
        "prospeccao": {
            "limite_novas_por_ciclo": 3,
            "ritmo": "minimo",
        },
        "marketing": {
            "complexidades_sensiveis": ["media", "alta", "muito_alta"],
            "rigor_deliberacao": "alto",
        },
        "entrega": {
            "priorizar_desbloqueio": True,
        },
    },
}


# ─── API pública ───────────────────────────────────────────────────────────────

def carregar_politicas() -> dict:
    """
    Carrega politicas_operacionais.json atual.
    Se não existir, deriva e salva a partir da governança ativa.
    Retorna sempre um dict com as seções esperadas pelos agentes.
    """
    caminho = config.PASTA_DADOS / _ARQ_POLITICAS
    if caminho.exists():
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # Fallback: derivar agora
    return derivar_e_salvar_politicas()


def derivar_e_salvar_politicas() -> dict:
    """
    Lê governança ativa, deriva políticas operacionais, salva e retorna.
    Chamado pelo orquestrador no início de cada ciclo e após cada comando de governança.
    """
    gov      = carregar_governanca_conselho()
    politicas = derivar_politicas_operacionais(gov)
    salvar_politicas_operacionais(politicas)
    registrar_historico_aplicacao_politica(gov, politicas)
    return politicas


def resumir_politicas_ativas() -> dict:
    """Snapshot resumido das políticas para exibição no painel."""
    p = carregar_politicas()
    return {
        "modo_empresa":        p.get("modo_empresa", "normal"),
        "score_ganho":         p.get("fechamento_comercial", {}).get("score_ganho", 8),
        "score_pronto":        p.get("fechamento_comercial", {}).get("score_pronto", 5),
        "limite_prosp":        p.get("prospeccao", {}).get("limite_novas_por_ciclo", 0),
        "urgencias_financeiro": p.get("financeiro", {}).get("urgencias_escalamento", ["imediata","alta"]),
        "rigor_marketing":     p.get("marketing", {}).get("rigor_deliberacao", "normal"),
        "linhas_priorizadas":  p.get("linhas_priorizadas", []),
        "gerado_em":           p.get("gerado_em", "—"),
    }


# ─── Derivação interna ─────────────────────────────────────────────────────────

def carregar_governanca_conselho() -> dict:
    """Lê estado_governanca_conselho.json."""
    caminho = config.PASTA_DADOS / _ARQ_ESTADO_GOV
    if not caminho.exists():
        return {"modo_empresa": "normal", "linhas_priorizadas": [], "diretrizes_ativas_ids": []}
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"modo_empresa": "normal", "linhas_priorizadas": [], "diretrizes_ativas_ids": []}


def _carregar_diretrizes() -> list:
    """Lê diretrizes_conselho.json (apenas ativas)."""
    caminho = config.PASTA_DADOS / _ARQ_DIRETRIZES
    if not caminho.exists():
        return []
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            todas = json.load(f)
        return [d for d in todas if d.get("status") == "ativa"]
    except Exception:
        return []


def derivar_politicas_operacionais(gov: dict) -> dict:
    """
    Traduz estado de governança → políticas operacionais.

    1. Parte das políticas base do modo atual.
    2. Aplica modulações das diretrizes ativas.
    3. Injeta linhas priorizadas e metadados.
    """
    modo = gov.get("modo_empresa", "normal")
    if modo not in _POLITICAS_POR_MODO:
        modo = "normal"

    # Deep-copy das políticas base
    import copy
    pol = copy.deepcopy(_POLITICAS_POR_MODO[modo])

    # Aplicar diretrizes
    diretrizes = _carregar_diretrizes()
    pol = aplicar_diretrizes_sobre_politicas(pol, diretrizes, modo)

    # Injetar metadados de contexto
    pol["modo_empresa"]       = modo
    pol["linhas_priorizadas"] = gov.get("linhas_priorizadas", [])
    pol["agentes_pausados"]   = gov.get("agentes_pausados", [])
    pol["areas_pausadas"]     = gov.get("areas_pausadas", [])
    pol["gerado_em"]          = datetime.now().isoformat(timespec="seconds")

    return pol


def aplicar_diretrizes_sobre_politicas(pol: dict, diretrizes: list, modo: str) -> dict:
    """
    Modula políticas a partir de palavras-chave nas diretrizes ativas.

    Regras:
    - diretriz com "foco_caixa" ou "reduzir_custo" → score_ganho+1, limite_prosp reduz
    - diretriz com "crescimento" ou "expansao"     → score_ganho-1 (mínimo 6)
    - diretriz com "cautela" ou "conservador"      → escalar alertas de "alta" também
    - diretriz com "qualidade" ou "entrega"        → priorizar_desbloqueio=True
    """
    for d in diretrizes:
        texto = (d.get("titulo", "") + " " + d.get("descricao", "")).lower()

        if any(k in texto for k in ("foco_caixa", "reduzir_custo", "corte")):
            pol["fechamento_comercial"]["score_ganho"] = min(
                pol["fechamento_comercial"]["score_ganho"] + 1, 10
            )
            if pol["prospeccao"]["limite_novas_por_ciclo"] == 0:
                pol["prospeccao"]["limite_novas_por_ciclo"] = 8

        if any(k in texto for k in ("crescimento", "expansao", "acelerar")):
            pol["fechamento_comercial"]["score_ganho"] = max(
                pol["fechamento_comercial"]["score_ganho"] - 1, 6
            )

        if any(k in texto for k in ("cautela", "conservador", "risco")):
            urgencias = pol["financeiro"]["urgencias_escalamento"]
            if "alta" not in urgencias:
                urgencias.append("alta")
            alertas = pol["financeiro"]["escalar_alertas_urgencia"]
            if "alta" not in alertas:
                alertas.append("alta")

        if any(k in texto for k in ("qualidade", "entrega", "desbloqueio")):
            pol["entrega"]["priorizar_desbloqueio"] = True

    return pol


def salvar_politicas_operacionais(politicas: dict) -> None:
    import os
    caminho = config.PASTA_DADOS / _ARQ_POLITICAS
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conteudo = json.dumps(politicas, ensure_ascii=False, indent=2)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)


def registrar_historico_aplicacao_politica(gov: dict, politicas: dict) -> None:
    """Registra snapshot no histórico de aplicação de políticas."""
    caminho = config.PASTA_DADOS / _ARQ_HIST_POLITICAS
    try:
        if caminho.exists():
            with open(caminho, "r", encoding="utf-8") as f:
                historico = json.load(f)
        else:
            historico = []
    except Exception:
        historico = []

    registro = {
        "timestamp":          datetime.now().isoformat(timespec="seconds"),
        "modo_empresa":       politicas.get("modo_empresa", "normal"),
        "score_ganho":        politicas.get("fechamento_comercial", {}).get("score_ganho"),
        "score_pronto":       politicas.get("fechamento_comercial", {}).get("score_pronto"),
        "limite_prosp":       politicas.get("prospeccao", {}).get("limite_novas_por_ciclo"),
        "urgencias_fin":      politicas.get("financeiro", {}).get("urgencias_escalamento"),
        "rigor_mkt":          politicas.get("marketing", {}).get("rigor_deliberacao"),
        "linhas_priorizadas": politicas.get("linhas_priorizadas", []),
    }
    # Manter apenas os últimos 200 registros
    historico.append(registro)
    historico = historico[-200:]

    import os
    conteudo = json.dumps(historico, ensure_ascii=False, indent=2)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)
