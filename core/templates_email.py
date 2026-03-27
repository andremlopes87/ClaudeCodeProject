"""
core/templates_email.py — Sistema de templates de email inteligentes.

Usa o LLM Router para personalizar emails seguindo o guia de tom da Vetor.
Fallback automático para templates estáticos quando LLM indisponível ou em dry-run.

Templates definidos em dados/templates_email.json — editável sem código.

Funções públicas:
  obter_template(tipo)                           → dict | None
  gerar_email(tipo, variaveis, empresa_id)       → dict
  gerar_email_assinado(tipo, variaveis, eid)     → dict
  listar_templates()                             → list[dict]

Retorno de gerar_email / gerar_email_assinado:
  {
    "assunto": str,
    "corpo":   str,
    "fonte":   "llm" | "template",  # template = fallback estático
    "tipo":    str,
  }
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_PASTA_DADOS     = Path(__file__).parent.parent / "dados"
_ARQ_TEMPLATES   = _PASTA_DADOS / "templates_email.json"
_ARQ_GUIA_TOM    = _PASTA_DADOS / "guia_tom_comunicacao.json"
_ARQ_EXEMPLOS    = _PASTA_DADOS / "exemplos_tom_por_categoria.json"
_ARQ_ASSINATURAS = _PASTA_DADOS / "assinaturas_empresa.json"
_ARQ_IDENTIDADE  = _PASTA_DADOS / "identidade_empresa.json"

# Caches — resetados por testes via _reset_caches()
_cache_templates: Optional[dict] = None
_cache_guia: Optional[dict] = None
_cache_exemplos: Optional[dict] = None


# ─── Utilitários internos ─────────────────────────────────────────────────────

def _ler(arq: Path, padrao):
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except Exception:
        return padrao


def _carregar_templates() -> dict:
    global _cache_templates
    if _cache_templates is None:
        raw = _ler(_ARQ_TEMPLATES, {})
        _cache_templates = raw.get("templates", {})
    return _cache_templates


def _carregar_guia() -> dict:
    global _cache_guia
    if _cache_guia is None:
        _cache_guia = _ler(_ARQ_GUIA_TOM, {})
    return _cache_guia


def _carregar_exemplos() -> dict:
    global _cache_exemplos
    if _cache_exemplos is None:
        _cache_exemplos = _ler(_ARQ_EXEMPLOS, {})
    return _cache_exemplos


def _obter_exemplo_categoria(categoria: str) -> dict:
    """Busca exemplo por categoria — correspondência exata ou parcial."""
    if not categoria:
        return {}
    exemplos = _carregar_exemplos()
    if categoria in exemplos:
        return exemplos[categoria]
    cat_lower = categoria.lower().replace(" ", "_")
    for k, v in exemplos.items():
        if cat_lower in k.lower() or k.lower() in cat_lower:
            return v
    return {}


def _substituir_variaveis(texto: str, variaveis: dict) -> str:
    """Substitui {chave} no texto; ignora chaves ausentes."""
    for k, v in variaveis.items():
        texto = texto.replace("{" + k + "}", str(v) if v is not None else "")
    return texto


def _reset_caches() -> None:
    """Limpa caches — útil em testes."""
    global _cache_templates, _cache_guia, _cache_exemplos
    _cache_templates = None
    _cache_guia = None
    _cache_exemplos = None


# ─── API pública ──────────────────────────────────────────────────────────────

def obter_template(tipo: str) -> Optional[dict]:
    """Retorna o template pelo tipo. None se não encontrado."""
    return _carregar_templates().get(tipo)


def listar_templates() -> list:
    """
    Retorna lista de todos os tipos de template disponíveis.

    Útil para exibir no painel ou documentar os tipos suportados.
    """
    return [
        {
            "tipo":             k,
            "tipo_comunicacao": v.get("tipo", ""),
            "assunto_template": v.get("assunto_template", ""),
            "usa_storytelling": v.get("usa_storytelling", False),
            "variaveis":        v.get("variaveis_necessarias", []),
        }
        for k, v in _carregar_templates().items()
    ]


def gerar_email(
    tipo: str,
    variaveis: dict,
    empresa_id: Optional[str] = None,
) -> dict:
    """
    Gera email completo (assunto + corpo) para o tipo de comunicação indicado.

    Fluxo:
      a) Carrega template de dados/templates_email.json
      b) Carrega guia de tom e exemplo por categoria
      c) Se template tem instrucoes_llm ou usa_storytelling:
           chama router.redigir() com instrucoes + variaveis + guia + exemplo
      d) Se LLM indisponível / dry-run / fallback:
           usa fallback_estatico com substituição de variáveis
           Em dry-run: prefixo "[DRY-RUN]" no corpo

    Retorna:
      {"assunto": str, "corpo": str, "fonte": "llm"|"template", "tipo": str}
    """
    template = obter_template(tipo)
    if not template:
        log.warning(f"[templates_email] tipo não encontrado: {tipo!r}")
        return {"assunto": "", "corpo": "", "fonte": "erro", "tipo": tipo}

    # Assunto
    assunto = _substituir_variaveis(template.get("assunto_template", ""), variaveis)

    guia     = _carregar_guia()
    categoria = variaveis.get("categoria", "")
    exemplo  = _obter_exemplo_categoria(categoria)

    corpo: Optional[str] = None
    fonte  = "template"
    modo_llm = "dry-run"  # default conservador

    # ── Tentativa via LLM ────────────────────────────────────────────────────
    if template.get("instrucoes_llm") or template.get("usa_storytelling"):
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            modo_llm = router._modo

            res = router.redigir(
                {
                    "agente": "agente_executor_contato",
                    "tarefa": "redigir_email",
                    "dados": {
                        **{k: str(v) for k, v in variaveis.items() if v is not None},
                        "tipo_email":  tipo,
                        "instrucoes":  template.get("instrucoes_llm", ""),
                    },
                    "contexto_extra": {
                        "guia_tom":              guia,
                        "exemplo_tom_categoria": exemplo,
                        "instrucoes_template":   template.get("instrucoes_llm", ""),
                    },
                },
                empresa_id=empresa_id,
            )

            if res.get("sucesso") and not res.get("fallback_usado"):
                resultado = res.get("resultado", "")
                if isinstance(resultado, dict):
                    resultado = resultado.get("texto", "")
                if isinstance(resultado, str) and len(resultado) > 30:
                    corpo = resultado
                    fonte = "llm"
                    log.info(f"[templates_email] LLM ok — tipo={tipo}")

        except Exception as exc:
            log.warning(f"[templates_email] LLM falhou para tipo={tipo}: {exc}")

    # ── Fallback estático ────────────────────────────────────────────────────
    if not corpo:
        raw_fallback = template.get("fallback_estatico", "")
        corpo = _substituir_variaveis(raw_fallback, variaveis)
        if modo_llm == "dry-run":
            corpo = "[DRY-RUN]\n" + corpo

    return {
        "assunto": assunto,
        "corpo":   corpo,
        "fonte":   fonte,
        "tipo":    tipo,
    }


def gerar_email_assinado(
    tipo: str,
    variaveis: dict,
    empresa_id: Optional[str] = None,
) -> dict:
    """
    Gera email completo + assinatura institucional.

    Adiciona bloco de assinatura de dados/assinaturas_empresa.json
    conforme o tipo do template (comercial / financeiro / pos_venda).

    Retorna: {"assunto": str, "corpo": str, "fonte": str, "tipo": str}
    """
    resultado = gerar_email(tipo, variaveis, empresa_id=empresa_id)
    corpo = resultado.get("corpo", "")
    if not corpo:
        return resultado

    # Só adiciona assinatura se o corpo não tiver "Equipe Vetor" nem "---"
    # (fallback_estatico já inclui "Equipe Vetor"; LLM pode ou não incluir)
    if "Equipe Vetor" in corpo or "---" in corpo:
        return resultado

    try:
        assinaturas = _ler(_ARQ_ASSINATURAS, {})
        identidade  = _ler(_ARQ_IDENTIDADE, {})

        nome_empresa    = identidade.get("nome_exibicao", identidade.get("nome_empresa", "Vetor"))
        email_comercial = (identidade.get("canais") or {}).get("email_comercial_planejado", "")
        site_oficial    = (identidade.get("canais") or {}).get("site_oficial", "")

        template_obj    = obter_template(tipo)
        tipo_com        = (template_obj or {}).get("tipo", "")

        if "financeiro" in tipo_com:
            tmpl_assin = assinaturas.get("assinatura_financeiro_texto", "")
            vars_assin = {
                "nome_remetente":  assinaturas.get("nome_remetente_padrao", "Equipe Vetor"),
                "nome_empresa":    nome_empresa,
                "email_financeiro": email_comercial,
            }
        elif "pos_venda" in tipo_com:
            tmpl_assin = assinaturas.get("assinatura_institucional_texto", "")
            vars_assin = {
                "nome_empresa":    nome_empresa,
                "descricao_curta": identidade.get("proposta_valor", ""),
                "site_oficial":    site_oficial,
            }
        else:
            tmpl_assin = assinaturas.get("assinatura_comercial_texto", "")
            vars_assin = {
                "nome_remetente":  assinaturas.get("nome_remetente_padrao", "Equipe Vetor"),
                "cargo":           assinaturas.get("cargo_remetente_padrao", ""),
                "nome_empresa":    nome_empresa,
                "email_comercial": email_comercial,
            }

        if tmpl_assin:
            assinatura = _substituir_variaveis(tmpl_assin, vars_assin)
        else:
            assinatura = f"\n---\nEquipe {nome_empresa}"

        resultado["corpo"] = corpo.rstrip() + assinatura

    except Exception as exc:
        log.warning(f"[templates_email] assinatura falhou: {exc}")

    return resultado
