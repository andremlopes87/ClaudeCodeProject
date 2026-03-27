"""
core/politicas_ti.py

Politicas centralizadas para os agentes de TI da Vetor.

Governa o que os agentes de TI podem e nao podem fazer.
Configuravel pelo conselho via dados/politicas_ti.json.

Funcoes publicas:
  carregar_politicas_ti()                           -> dict
  executor_pode_aplicar(tipo, arquivo, risco)       -> (bool, str)
  executor_em_cooldown()                            -> (bool, str)
  auditor_ativo()                                   -> bool
  qualidade_ativo()                                 -> bool
  atualizar_politica_ti(secao, campo, valor)        -> bool

Governanca:
  - agentes_pausados: para individualmente cada agente de TI
  - modo_empresa=manutencao: auditor roda, executor NAO
  - modo_empresa=conservador: executor limitado a risco_maximo=baixo
"""

import fnmatch
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import config

log = logging.getLogger("politicas_ti")

_ROOT         = Path(__file__).parent.parent
_ARQ_POL      = config.PASTA_DADOS / "politicas_ti.json"
_ARQ_GOV      = config.PASTA_DADOS / "estado_governanca_conselho.json"
_ARQ_INC      = config.PASTA_DADOS / "incidentes_executor.json"

# Nomes dos agentes de TI no estado de governanca
_NOME_AUDITOR  = "auditor_seguranca"
_NOME_QUALID   = "qualidade"
_NOME_EXECUTOR = "executor_melhorias"

# Ordem de risco para comparacao
_RISCO_ORD = {"baixo": 0, "medio": 1, "alto": 2}

# Defaults seguros usados quando politicas_ti.json nao existe
_DEFAULTS: dict = {
    "executor": {
        "ativo": True,
        "modo": "dry-run",
        "max_mudancas_por_execucao": 3,
        "risco_maximo_automatico": "baixo",
        "arquivos_protegidos": [
            "core/orquestrador_empresa.py",
            "core/governanca_conselho.py",
            "core/scheduler.py",
            "main_scheduler.py",
            "main_empresa.py",
            ".env",
            "config.py",
        ],
        "arquivos_permitidos_patterns": [
            "core/*.py",
            "modulos/**/*.py",
            "agentes/**/*.py",
            "tests/**/*.py",
            "conectores/*.py",
        ],
        "tipos_mudanca_permitidos": [
            "adicionar_docstring",
            "fixar_versao_dependencia",
            "adicionar_gitignore_entry",
            "mascarar_dado_sensivel_em_log",
            "adicionar_tratamento_erro",
            "criar_teste",
            "remover_import_nao_usado",
        ],
        "tipos_mudanca_bloqueados": [
            "alterar_fluxo_agente",
            "alterar_modelo_dados",
            "alterar_arquitetura",
            "remover_funcionalidade",
            "alterar_governanca",
        ],
        "cooldown_apos_rollback_horas": 24,
        "notificar_conselho_em": ["rollback", "vulnerabilidade_critica", "teste_falhou"],
    },
    "auditor": {
        "ativo": True,
        "varrer_dados_sensiveis": True,
        "incluir_analise_llm": True,
        "severidade_minima_alerta": "alto",
    },
    "qualidade": {
        "ativo": True,
        "rodar_testes": True,
        "timeout_teste_segundos": 60,
        "incluir_analise_llm": True,
        "score_minimo_alerta": 60,
    },
}


# ─── API publica ──────────────────────────────────────────────────────────────

def carregar_politicas_ti() -> dict:
    """Carrega dados/politicas_ti.json com fallback para defaults seguros."""
    if not _ARQ_POL.exists():
        return _DEFAULTS
    try:
        dados = json.loads(_ARQ_POL.read_text(encoding="utf-8"))
        # Merge com defaults para campos ausentes
        resultado = {}
        for secao, default_sec in _DEFAULTS.items():
            resultado[secao] = {**default_sec, **(dados.get(secao) or {})}
        return resultado
    except Exception as exc:
        log.warning(f"[politicas_ti] falha ao ler politicas — usando defaults: {exc}")
        return _DEFAULTS


def executor_pode_aplicar(tipo_mudanca: str, arquivo: str, risco: str) -> tuple:
    """
    Verifica se o executor tem permissao para aplicar uma mudanca.

    Ordem de verificacao:
      1. Executor ativo nas politicas
      2. Arquivo na lista de protegidos
      3. Arquivo fora da whitelist de patterns
      4. Tipo de mudanca bloqueado
      5. Tipo de mudanca nao na lista de permitidos (se lista nao vazia)
      6. Risco acima do maximo configurado
      7. Overrides de governanca (modo_empresa)

    Retorna (permitido: bool, motivo: str).
    motivo = "" quando permitido=True.
    """
    pol = carregar_politicas_ti()
    exec_pol = pol.get("executor", {})
    gov      = _ler_governanca()

    # 1. Executor ativo
    if not exec_pol.get("ativo", True):
        return False, "executor desativado nas politicas de TI"

    if _NOME_EXECUTOR in gov.get("agentes_pausados", []):
        return False, "executor pausado pela governanca do conselho"

    # 2. Arquivo protegido (blacklist absoluta)
    arq_norm = _normalizar_caminho(arquivo)
    for protegido in exec_pol.get("arquivos_protegidos", []):
        if _caminhos_equivalentes(arq_norm, protegido):
            return False, f"arquivo protegido: {protegido}"

    # 3. Arquivo fora da whitelist
    patterns = exec_pol.get("arquivos_permitidos_patterns", [])
    if patterns and not _arquivo_na_whitelist(arq_norm, patterns):
        return False, f"arquivo fora da whitelist de patterns permitidos"

    # 4. Tipo bloqueado
    if tipo_mudanca in exec_pol.get("tipos_mudanca_bloqueados", []):
        return False, f"tipo bloqueado: {tipo_mudanca}"

    # 5. Tipo nao na lista de permitidos (se lista definida)
    permitidos = exec_pol.get("tipos_mudanca_permitidos", [])
    if permitidos and tipo_mudanca not in permitidos:
        return False, f"tipo nao permitido: {tipo_mudanca}"

    # 6. Risco acima do maximo
    risco_max = _risco_maximo_efetivo(exec_pol, gov)
    if _RISCO_ORD.get(risco, 1) > _RISCO_ORD.get(risco_max, 0):
        return False, f"risco '{risco}' acima do maximo configurado '{risco_max}'"

    # 7. Modo manutencao: executor bloqueado
    modo_empresa = gov.get("modo_empresa", "normal")
    if modo_empresa == "manutencao":
        return False, "empresa em modo manutencao — executor bloqueado"

    return True, ""


def executor_em_cooldown() -> tuple:
    """
    Verifica se houve rollback recente dentro do cooldown configurado.
    Retorna (em_cooldown: bool, motivo: str).
    """
    pol = carregar_politicas_ti()
    horas = pol["executor"].get("cooldown_apos_rollback_horas", 24)

    if not _ARQ_INC.exists():
        return False, ""

    try:
        incidentes = json.loads(_ARQ_INC.read_text(encoding="utf-8"))
    except Exception:
        return False, ""

    agora = datetime.now()
    limite = agora - timedelta(hours=horas)

    for inc in reversed(incidentes):
        if inc.get("tipo") != "rollback":
            continue
        try:
            ts = datetime.fromisoformat(inc["timestamp"])
            if ts >= limite:
                horas_atras = (agora - ts).total_seconds() / 3600
                return True, (
                    f"rollback em {inc['timestamp'][:16]} "
                    f"({horas_atras:.1f}h atras — cooldown={horas}h)"
                )
        except Exception:
            continue

    return False, ""


def auditor_ativo() -> bool:
    """
    Retorna True se o auditor esta habilitado.
    Respeita politicas_ti.json e governanca do conselho.
    """
    pol = carregar_politicas_ti()
    if not pol["auditor"].get("ativo", True):
        return False

    gov = _ler_governanca()
    if _NOME_AUDITOR in gov.get("agentes_pausados", []):
        return False

    # Auditor roda mesmo em manutencao
    return True


def qualidade_ativo() -> bool:
    """
    Retorna True se o agente de qualidade esta habilitado.
    Respeita politicas_ti.json e governanca do conselho.
    """
    pol = carregar_politicas_ti()
    if not pol["qualidade"].get("ativo", True):
        return False

    gov = _ler_governanca()
    if _NOME_QUALID in gov.get("agentes_pausados", []):
        return False

    # Em manutencao: qualidade NAO roda (apenas auditor roda)
    if gov.get("modo_empresa") == "manutencao":
        return False

    return True


def atualizar_politica_ti(secao: str, campo: str, valor) -> bool:
    """
    Atualiza um campo em dados/politicas_ti.json.
    Permite ao conselho mudar politicas via painel.

    Retorna True se atualizado com sucesso.
    """
    pol = carregar_politicas_ti()

    if secao not in pol:
        log.warning(f"[politicas_ti] secao desconhecida: {secao}")
        return False

    if campo not in pol[secao] and campo not in _DEFAULTS.get(secao, {}):
        log.warning(f"[politicas_ti] campo desconhecido: {secao}.{campo}")
        return False

    pol[secao][campo] = valor

    try:
        import os
        _ARQ_POL.parent.mkdir(parents=True, exist_ok=True)
        conteudo = json.dumps(pol, ensure_ascii=False, indent=2)
        tmp = _ARQ_POL.with_suffix(_ARQ_POL.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(conteudo)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _ARQ_POL)
        log.info(f"[politicas_ti] atualizado: {secao}.{campo} = {valor!r}")
        return True
    except Exception as exc:
        log.error(f"[politicas_ti] falha ao salvar politicas: {exc}")
        return False


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _ler_governanca() -> dict:
    """Le estado_governanca_conselho.json com fallback seguro."""
    if not _ARQ_GOV.exists():
        return {"modo_empresa": "normal", "agentes_pausados": []}
    try:
        return json.loads(_ARQ_GOV.read_text(encoding="utf-8"))
    except Exception:
        return {"modo_empresa": "normal", "agentes_pausados": []}


def _risco_maximo_efetivo(exec_pol: dict, gov: dict) -> str:
    """
    Determina o risco maximo efetivo considerando politicas + governanca.
    Modo conservador forca risco_maximo = baixo independente das politicas.
    """
    risco_pol = exec_pol.get("risco_maximo_automatico", "baixo")
    if gov.get("modo_empresa") == "conservador":
        # Nao pode ser mais alto que "baixo" em modo conservador
        if _RISCO_ORD.get(risco_pol, 0) > _RISCO_ORD["baixo"]:
            return "baixo"
    return risco_pol


def _normalizar_caminho(arquivo: str) -> str:
    """Normaliza separadores de caminho para comparacao."""
    return str(arquivo).replace("\\", "/").lstrip("/")


def _caminhos_equivalentes(arq_norm: str, protegido: str) -> bool:
    """Compara caminhos normalizados — verifica se o arquivo e o protegido."""
    prot_norm = _normalizar_caminho(protegido)
    # Match exato ou sufixo
    return arq_norm == prot_norm or arq_norm.endswith("/" + prot_norm)


def _arquivo_na_whitelist(arq_norm: str, patterns: list) -> bool:
    """
    Verifica se o caminho normalizado bate com algum pattern da whitelist.
    Suporta: core/*.py, agentes/**/*.py, etc.
    """
    for pattern in patterns:
        pat_norm = _normalizar_caminho(pattern)
        if fnmatch.fnmatch(arq_norm, pat_norm):
            return True
        # Para patterns com **, testar tambem o sufixo do caminho
        if "**" in pat_norm:
            partes = pat_norm.split("**/")
            prefixo = partes[0].rstrip("/")
            sufixo  = partes[-1]
            if arq_norm.startswith(prefixo + "/") and fnmatch.fnmatch(arq_norm, pat_norm):
                return True
            # fnmatch nao suporta ** nativamente: fazer match manual
            if arq_norm.startswith(prefixo + "/") and arq_norm.endswith("/" + sufixo.lstrip("*/")):
                return True
            if arq_norm.startswith(prefixo + "/") and fnmatch.fnmatch(
                arq_norm[len(prefixo) + 1:], sufixo
            ):
                return True
    return False
