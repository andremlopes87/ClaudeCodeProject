"""
agentes/ti/agente_qualidade.py

Agente de qualidade autonomo da Vetor.

Responsabilidade:
  Rodar testes, analisar cobertura, detectar fragiliades de codigo e
  gerar recomendacoes priorizadas para o conselho.

  NUNCA modifica codigo.
  Testes executados via subprocess com timeout — nunca travam.
  Custo zero (dry-run).

Etapas:
  1. Rodar todos os testes
  2. Analise de cobertura de testes
  3. Analise de qualidade de codigo
  4. Analise de dependencias
  5. LLM: analise inteligente e tendencias
  6. Gerar relatorio de qualidade
  7. Gerar handoffs para executor
  8. Atualizar memoria do agente

Arquivos gerenciados:
  dados/relatorio_qualidade.json       -- relatorio mais recente
  dados/historico_qualidade.json       -- historico append-only
"""

import ast
import json
import logging
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

import config
from core.llm_router import LLMRouter
from core.llm_memoria import atualizar_memoria_agente
from core.controle_agente import configurar_log_agente

# ─── Constantes ───────────────────────────────────────────────────────────────

NOME_AGENTE = "agente_qualidade"

_ROOT       = Path(__file__).parent.parent.parent
_ARQ_REL    = config.PASTA_DADOS / "relatorio_qualidade.json"
_ARQ_HIST   = config.PASTA_DADOS / "historico_qualidade.json"
_ARQ_HF     = config.PASTA_DADOS / "handoffs_agentes.json"

_TIMEOUT_TESTE_S = 60      # segundos por arquivo de teste
_LINHAS_ATENCAO  = 300
_LINHAS_RISCO    = 500
_LINHAS_FUNCAO   = 50      # funcao com mais de N linhas = complexa
_NESTING_MAXIMO  = 4       # nivel de indentacao que indica excesso de nesting

log = logging.getLogger(NOME_AGENTE)

# ─── Ponto de entrada ─────────────────────────────────────────────────────────

def executar() -> dict:
    """Executa o ciclo completo do agente de qualidade. Retorna resumo."""

    _, arq_log = configurar_log_agente(NOME_AGENTE)
    log.info("[qualidade] iniciando ciclo")

    # ETAPA 1 — Testes
    log.info("[qualidade] etapa 1 — rodando testes")
    resultado_testes = _etapa1_rodar_testes()

    # ETAPA 2 — Cobertura
    log.info("[qualidade] etapa 2 — analisando cobertura")
    resultado_cobertura = _etapa2_cobertura(resultado_testes)

    # ETAPA 3 — Qualidade de codigo
    log.info("[qualidade] etapa 3 — analisando qualidade do codigo")
    resultado_qualidade = _etapa3_qualidade_codigo()

    # ETAPA 4 — Dependencias
    log.info("[qualidade] etapa 4 — analisando dependencias")
    resultado_deps = _etapa4_dependencias()

    # ETAPA 5 — LLM
    log.info("[qualidade] etapa 5 — analise LLM")
    narrativa = _etapa5_llm(resultado_testes, resultado_cobertura,
                            resultado_qualidade, resultado_deps)

    # ETAPA 6 — Gerar relatorio
    log.info("[qualidade] etapa 6 — gerando relatorio")
    recomendacoes = _gerar_recomendacoes(resultado_testes, resultado_cobertura,
                                         resultado_qualidade, resultado_deps)
    score = _calcular_score(resultado_testes, resultado_cobertura,
                            resultado_qualidade, recomendacoes)
    relatorio = _etapa6_relatorio(resultado_testes, resultado_cobertura,
                                  resultado_qualidade, resultado_deps,
                                  recomendacoes, score, narrativa)

    # ETAPA 7 — Handoffs
    log.info("[qualidade] etapa 7 — gerando handoffs")
    _etapa7_handoffs(recomendacoes)

    # ETAPA 8 — Memoria
    log.info("[qualidade] etapa 8 — atualizando memoria")
    _etapa8_memoria(relatorio)

    resumo = {
        "data_analise":          relatorio["data_analise"],
        "taxa_testes":           resultado_testes["taxa_sucesso"],
        "taxa_cobertura_modulos": resultado_cobertura["taxa_cobertura_modulos"],
        "score_qualidade":       score,
        "total_recomendacoes":   len(recomendacoes),
        "recomendacoes_altas":   sum(1 for r in recomendacoes if r["prioridade"] == "alta"),
    }
    log.info(f"[qualidade] ciclo concluido — score={score}/100")
    return resumo


# ─── ETAPA 1 — Rodar testes ───────────────────────────────────────────────────

def _etapa1_rodar_testes() -> dict:
    """Descobre e executa todos os test_*.py em tests/ com subprocess."""

    dir_testes = _ROOT / "tests"
    if not dir_testes.exists():
        return {
            "total_arquivos": 0, "passaram": 0, "falharam": 0,
            "erros": 0, "timeout": 0, "taxa_sucesso": 100.0, "detalhes": []
        }

    arquivos = sorted(dir_testes.rglob("test_*.py"))
    total = len(arquivos)
    passaram = falharam = erros = timeouts = 0
    detalhes = []

    for arq in arquivos:
        rel = str(arq.relative_to(_ROOT))
        resultado_arq = _executar_teste(arq)
        detalhes.append({
            "arquivo": rel,
            "status": resultado_arq["status"],
            "duracao_ms": resultado_arq["duracao_ms"],
            "saida_resumo": resultado_arq["saida_resumo"],
        })
        if resultado_arq["status"] == "passou":
            passaram += 1
        elif resultado_arq["status"] == "falhou":
            falharam += 1
        elif resultado_arq["status"] == "timeout":
            timeouts += 1
        else:
            erros += 1

    taxa = round((passaram / total * 100), 1) if total > 0 else 100.0
    return {
        "total_arquivos": total,
        "passaram":       passaram,
        "falharam":       falharam,
        "erros":          erros,
        "timeout":        timeouts,
        "taxa_sucesso":   taxa,
        "detalhes":       detalhes,
    }


def _executar_teste(arq: Path) -> dict:
    """Executa um arquivo de teste com subprocess e retorna status."""

    inicio = datetime.now()
    try:
        proc = subprocess.run(
            [sys.executable, str(arq)],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_TESTE_S,
            cwd=str(_ROOT),
        )
        duracao_ms = int((datetime.now() - inicio).total_seconds() * 1000)
        if proc.returncode == 0:
            return {"status": "passou", "duracao_ms": duracao_ms,
                    "saida_resumo": _resumir_saida(proc.stdout)}
        else:
            saida = (proc.stdout + proc.stderr)[-500:]
            return {"status": "falhou", "duracao_ms": duracao_ms,
                    "saida_resumo": _resumir_saida(saida)}
    except subprocess.TimeoutExpired:
        duracao_ms = int((datetime.now() - inicio).total_seconds() * 1000)
        return {"status": "timeout", "duracao_ms": duracao_ms,
                "saida_resumo": f"Timeout apos {_TIMEOUT_TESTE_S}s"}
    except Exception as exc:
        duracao_ms = int((datetime.now() - inicio).total_seconds() * 1000)
        return {"status": "erro", "duracao_ms": duracao_ms,
                "saida_resumo": str(exc)[:200]}


def _resumir_saida(saida: str) -> str:
    """Pega as ultimas 3 linhas relevantes da saida."""
    linhas = [l.strip() for l in saida.strip().splitlines() if l.strip()]
    return " | ".join(linhas[-3:])[:200] if linhas else ""


# ─── ETAPA 2 — Cobertura ──────────────────────────────────────────────────────

def _etapa2_cobertura(resultado_testes: dict) -> dict:
    """Mapeia modulos em core/, agentes/, modulos/ vs arquivos de teste."""

    dir_testes = _ROOT / "tests"
    # Coletar todos os arquivos de teste existentes
    arquivos_teste = set()
    if dir_testes.exists():
        for p in dir_testes.rglob("test_*.py"):
            # Mapear: test_foo.py → foo
            nome = p.stem[len("test_"):]   # remove prefixo "test_"
            arquivos_teste.add(nome)

    # Modulos analisados
    pastas_modulos = [
        _ROOT / "core",
        _ROOT / "agentes",
        _ROOT / "modulos",
    ]

    modulos_total        = 0
    modulos_com_teste    = 0
    funcoes_total        = 0
    funcoes_cobertas     = 0
    modulos_sem_teste    = []
    mapa_modulos         = []

    for pasta in pastas_modulos:
        if not pasta.exists():
            continue
        for py in pasta.rglob("*.py"):
            if py.name in ("__init__.py",):
                continue
            if "__pycache__" in py.parts:
                continue

            modulos_total += 1
            nome_modulo   = py.stem
            rel_path      = str(py.relative_to(_ROOT))

            # Verificar se existe teste correspondente
            tem_teste = nome_modulo in arquivos_teste

            # Extrair funcoes/classes publicas
            publicas = _extrair_publicas(py)
            n_funcoes = len(publicas)
            funcoes_total += n_funcoes

            # Estimativa de cobertura: se tem teste, assume cobertura parcial
            # (nao temos acesso ao coverage real sem pytest-cov)
            n_cobertas = n_funcoes if tem_teste else 0
            funcoes_cobertas += n_cobertas

            if tem_teste:
                modulos_com_teste += 1
            else:
                modulos_sem_teste.append(rel_path)

            mapa_modulos.append({
                "modulo":            rel_path,
                "tem_teste":         tem_teste,
                "funcoes_publicas":  n_funcoes,
                "funcoes_cobertas":  n_cobertas,
                "funcoes_lista":     publicas[:10],  # max 10 para nao inchar
            })

    taxa_mod = round(modulos_com_teste / modulos_total * 100, 1) if modulos_total else 0.0
    taxa_fn  = round(funcoes_cobertas  / funcoes_total  * 100, 1) if funcoes_total  else 0.0

    return {
        "modulos_total":           modulos_total,
        "modulos_com_teste":       modulos_com_teste,
        "funcoes_total":           funcoes_total,
        "funcoes_cobertas":        funcoes_cobertas,
        "taxa_cobertura_modulos":  taxa_mod,
        "taxa_cobertura_funcoes":  taxa_fn,
        "modulos_sem_teste":       modulos_sem_teste,
        "mapa_modulos":            mapa_modulos,
    }


def _extrair_publicas(py: Path) -> list:
    """Extrai nomes de funcoes e classes publicas (sem prefixo _)."""
    publicas = []
    try:
        src = py.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    publicas.append(node.name)
    except Exception:
        pass
    return publicas


# ─── ETAPA 3 — Qualidade de codigo ───────────────────────────────────────────

def _etapa3_qualidade_codigo() -> dict:
    """Analisa arquivos .py buscando problemas de qualidade."""

    arquivos_grandes      = []
    funcoes_complexas     = []
    sem_docstring         = []
    duplicacoes_suspeitas = []
    todos_pendentes       = []
    nesting_profundo      = []

    # Mapa de nomes de funcao para detectar duplicacoes entre modulos
    nomes_funcoes: dict[str, list] = {}

    pastas = [
        _ROOT / "core",
        _ROOT / "agentes",
        _ROOT / "modulos",
    ]

    for pasta in pastas:
        if not pasta.exists():
            continue
        for py in pasta.rglob("*.py"):
            if "__pycache__" in py.parts or py.name == "__init__.py":
                continue

            rel = str(py.relative_to(_ROOT))
            try:
                linhas = py.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue

            n_linhas = len(linhas)

            # Arquivos grandes
            if n_linhas > _LINHAS_ATENCAO:
                nivel = "risco" if n_linhas > _LINHAS_RISCO else "atencao"
                arquivos_grandes.append({
                    "arquivo": rel, "linhas": n_linhas, "nivel": nivel
                })

            # TODOs e FIXMEs
            for i, linha in enumerate(linhas, 1):
                ln = linha.strip()
                if re.search(r"\b(TODO|FIXME|HACK|XXX|NOQA)\b", ln, re.IGNORECASE):
                    todos_pendentes.append({
                        "arquivo": rel, "linha": i, "texto": ln[:120]
                    })

            # Analise AST
            try:
                src = "\n".join(linhas)
                tree = ast.parse(src)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue

                nome_fn = node.name

                # Funcoes publicas sem docstring
                if not nome_fn.startswith("_"):
                    tem_doc = (
                        isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)
                    ) if node.body else False
                    if not tem_doc:
                        sem_docstring.append({
                            "arquivo": rel,
                            "funcao":  nome_fn,
                            "linha":   node.lineno,
                        })

                # Funcoes complexas por tamanho
                fim = getattr(node, "end_lineno", node.lineno)
                tamanho = fim - node.lineno
                if tamanho > _LINHAS_FUNCAO:
                    funcoes_complexas.append({
                        "arquivo": rel,
                        "funcao":  nome_fn,
                        "linha":   node.lineno,
                        "tamanho": tamanho,
                    })

                # Nesting profundo (heuristica por indentacao)
                for subnode in ast.walk(node):
                    if isinstance(subnode, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                        col = getattr(subnode, "col_offset", 0)
                        nivel_nesting = col // 4
                        if nivel_nesting >= _NESTING_MAXIMO:
                            nesting_profundo.append({
                                "arquivo": rel,
                                "funcao":  nome_fn,
                                "linha":   getattr(subnode, "lineno", node.lineno),
                                "nivel":   nivel_nesting,
                            })
                            break  # um por funcao e suficiente

                # Mapa para deteccao de duplicacoes
                if not nome_fn.startswith("_") and len(nome_fn) > 4:
                    nomes_funcoes.setdefault(nome_fn, []).append(rel)

    # Duplicacoes: mesmo nome em 3+ arquivos diferentes
    for nome_fn, arquivos in nomes_funcoes.items():
        if len(arquivos) >= 3:
            duplicacoes_suspeitas.append({
                "funcao":   nome_fn,
                "arquivos": arquivos[:5],
                "ocorrencias": len(arquivos),
            })

    # Ordenar por impacto
    arquivos_grandes.sort(key=lambda x: x["linhas"], reverse=True)
    funcoes_complexas.sort(key=lambda x: x["tamanho"], reverse=True)
    sem_docstring_count = len(sem_docstring)

    return {
        "arquivos_grandes":        arquivos_grandes[:10],
        "funcoes_complexas":       funcoes_complexas[:10],
        "sem_docstring":           sem_docstring[:20],
        "sem_docstring_total":     sem_docstring_count,
        "duplicacoes_suspeitas":   duplicacoes_suspeitas[:10],
        "todos_pendentes":         todos_pendentes[:20],
        "todos_total":             len(todos_pendentes),
        "nesting_profundo":        nesting_profundo[:10],
    }


# ─── ETAPA 4 — Dependencias ───────────────────────────────────────────────────

def _etapa4_dependencias() -> dict:
    """Analisa requirements.txt vs imports reais no codigo."""

    req_file = _ROOT / "requirements.txt"
    declaradas: set[str] = set()
    sem_versao: list[str] = []

    if req_file.exists():
        for linha in req_file.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#"):
                continue
            # Extrair nome do pacote (ignorar versao e extras)
            nome = re.split(r"[>=<!;\[]", linha)[0].strip().lower()
            if nome:
                declaradas.add(nome)
                # Verificar se versao esta fixada
                if not re.search(r"==", linha):
                    sem_versao.append(linha)

    # Coletar imports do codigo
    _RE_IMPORT = re.compile(r"^\s*(?:import|from)\s+([\w\.]+)", re.MULTILINE)
    importados: set[str] = set()

    for pasta in [_ROOT / "core", _ROOT / "agentes", _ROOT / "modulos"]:
        if not pasta.exists():
            continue
        for py in pasta.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            try:
                src = py.read_text(encoding="utf-8", errors="ignore")
                for m in _RE_IMPORT.finditer(src):
                    raiz = m.group(1).split(".")[0].lower()
                    importados.add(raiz)
            except Exception:
                pass

    # Stdlib e modulos internos (excluir do comparativo)
    _STDLIB = {
        "os", "sys", "re", "json", "logging", "datetime", "pathlib", "time",
        "uuid", "math", "random", "typing", "collections", "itertools",
        "functools", "io", "copy", "hashlib", "base64", "urllib", "http",
        "html", "email", "ast", "subprocess", "threading", "multiprocessing",
        "dataclasses", "abc", "enum", "contextlib", "traceback", "warnings",
        "inspect", "importlib", "pkgutil", "platform", "shutil", "tempfile",
        "string", "textwrap", "struct", "socket", "ssl", "concurrent",
        "queue", "heapq", "bisect", "array", "decimal", "fractions",
        "csv", "sqlite3", "xml", "unittest", "pdb", "cProfile", "timeit",
        "dis", "gc", "weakref", "ctypes", "unicodedata", "locale", "gettext",
        "argparse", "configparser", "logging", "signal", "errno", "stat",
        "__future__", "builtins",
    }
    _INTERNOS = {
        "config", "core", "agentes", "modulos", "conselho_app", "conectores",
        "tests",
    }

    externos_importados = {
        p for p in importados - _STDLIB - _INTERNOS
        if not p.startswith("main_")
    }
    nao_declaradas = [p for p in sorted(externos_importados)
                      if p not in declaradas]
    nao_utilizadas  = [p for p in sorted(declaradas)
                       if p not in externos_importados
                       and p not in {"python-dotenv", "python-multipart"}]

    return {
        "total":            len(declaradas),
        "sem_versao_fixada": sem_versao,
        "nao_declaradas":   nao_declaradas,
        "nao_utilizadas":   nao_utilizadas,
    }


# ─── ETAPA 5 — LLM ───────────────────────────────────────────────────────────

def _etapa5_llm(testes: dict, cobertura: dict, qualidade: dict, deps: dict) -> str:
    """Solicita analise inteligente ao router LLM."""
    try:
        router = LLMRouter()
        ctx = {
            "testes_taxa_sucesso":        testes["taxa_sucesso"],
            "testes_falharam":            testes["falharam"],
            "cobertura_modulos_pct":      cobertura["taxa_cobertura_modulos"],
            "modulos_sem_teste_count":    len(cobertura["modulos_sem_teste"]),
            "modulos_sem_teste_exemplos": cobertura["modulos_sem_teste"][:5],
            "arquivos_grandes":           [a["arquivo"] for a in qualidade["arquivos_grandes"][:5]],
            "funcoes_complexas_count":    len(qualidade["funcoes_complexas"]),
            "sem_docstring_total":        qualidade["sem_docstring_total"],
            "todos_total":                qualidade["todos_total"],
            "deps_nao_declaradas":        deps["nao_declaradas"][:5],
            "instrucao": (
                "Analisar qualidade geral do codigo Python, identificar padroes frageis, "
                "sugerir melhorias priorizadas. Considerar boas praticas de Python, "
                "padroes de agentes de IA, e tendencias em sistemas multi-agente. "
                "Responder em portugues, de forma objetiva e acionavel."
            ),
        }
        resultado = router.analisar(ctx)
        return resultado.get("analise") or resultado.get("texto") or _narrativa_mecanica(testes, cobertura, qualidade)
    except Exception:
        return _narrativa_mecanica(testes, cobertura, qualidade)


def _narrativa_mecanica(testes: dict, cobertura: dict, qualidade: dict) -> str:
    """Narrativa de fallback gerada mecanicamente."""
    partes = []
    partes.append(f"Taxa de testes: {testes['taxa_sucesso']}% dos arquivos passaram.")
    partes.append(f"Cobertura de modulos: {cobertura['taxa_cobertura_modulos']}% tem teste.")
    n_grandes = len(qualidade["arquivos_grandes"])
    if n_grandes:
        partes.append(f"{n_grandes} arquivo(s) com excesso de linhas — candidatos a refatoracao.")
    if qualidade["sem_docstring_total"] > 10:
        partes.append(f"{qualidade['sem_docstring_total']} funcoes publicas sem docstring.")
    if qualidade["todos_total"]:
        partes.append(f"{qualidade['todos_total']} TODO/FIXME pendentes no codigo.")
    return " ".join(partes)


# ─── Recomendacoes ────────────────────────────────────────────────────────────

def _gerar_recomendacoes(testes: dict, cobertura: dict, qualidade: dict, deps: dict) -> list:
    """Gera lista de recomendacoes priorizadas."""
    recs = []
    seq = [0]  # contador mutavel

    def _rec(prioridade: str, categoria: str, descricao: str,
             acao: str, esforco: str, risco: str, impacto: str):
        seq[0] += 1
        recs.append({
            "id":             f"rec_{seq[0]:03d}",
            "prioridade":     prioridade,
            "categoria":      categoria,
            "descricao":      descricao,
            "acao_sugerida":  acao,
            "esforco_estimado": esforco,
            "risco_correcao": risco,
            "impacto":        impacto,
        })

    # Testes falhando
    falharam = [d for d in testes["detalhes"] if d["status"] != "passou"]
    for det in falharam[:3]:
        _rec("alta", "testes",
             f"Teste falhou: {det['arquivo']} ({det['status']})",
             f"Corrigir falha em {det['arquivo']}: {det.get('saida_resumo','')[:80]}",
             "baixo", "baixo", "alto")

    # Cobertura baixa
    if cobertura["taxa_cobertura_modulos"] < 50:
        _rec("alta", "cobertura",
             f"Cobertura de modulos critica: {cobertura['taxa_cobertura_modulos']}%",
             "Criar testes para os modulos core/ prioritariamente",
             "alto", "baixo", "alto")
    elif cobertura["taxa_cobertura_modulos"] < 75:
        _rec("media", "cobertura",
             f"Cobertura de modulos abaixo do ideal: {cobertura['taxa_cobertura_modulos']}%",
             "Adicionar testes para modulos descobertos listados no relatorio",
             "medio", "baixo", "medio")

    # Modulos sem teste (top 5)
    for mod in cobertura["modulos_sem_teste"][:5]:
        _rec("media", "cobertura",
             f"Modulo sem teste: {mod}",
             f"Criar arquivo de teste correspondente em tests/",
             "medio", "baixo", "medio")

    # Arquivos grandes
    for arq in qualidade["arquivos_grandes"][:3]:
        if arq["nivel"] == "risco":
            _rec("media", "qualidade",
                 f"Arquivo muito grande: {arq['arquivo']} ({arq['linhas']} linhas)",
                 "Dividir em modulos menores com responsabilidades claras",
                 "alto", "medio", "medio")

    # Funcoes complexas
    if len(qualidade["funcoes_complexas"]) > 5:
        _rec("media", "qualidade",
             f"{len(qualidade['funcoes_complexas'])} funcoes com mais de {_LINHAS_FUNCAO} linhas",
             "Refatorar as 3 maiores funcoes identificadas no relatorio",
             "medio", "medio", "medio")

    # Dependencias nao declaradas
    for dep in deps["nao_declaradas"][:3]:
        _rec("alta", "dependencias",
             f"Dependencia nao declarada em requirements.txt: {dep}",
             f"Adicionar '{dep}' ao requirements.txt com versao fixada",
             "baixo", "baixo", "alto")

    # Dependencias sem versao fixada
    for dep in deps["sem_versao_fixada"][:3]:
        _rec("baixa", "dependencias",
             f"Dependencia sem versao fixada: {dep}",
             f"Fixar versao exata: mudar para '{dep}=={dep}'",
             "baixo", "baixo", "baixo")

    # TODOs pendentes
    if qualidade["todos_total"] > 10:
        _rec("baixa", "qualidade",
             f"{qualidade['todos_total']} comentarios TODO/FIXME pendentes",
             "Revisar e resolver ou deletar comentarios obsoletos",
             "medio", "baixo", "baixo")

    return recs


# ─── Score ────────────────────────────────────────────────────────────────────

def _calcular_score(testes: dict, cobertura: dict, qualidade: dict,
                    recomendacoes: list) -> int:
    """Calcula score de qualidade de 0 a 100."""
    score = 100

    # Penalidade por testes falhando (max 30)
    n_falhou = testes["falharam"] + testes["erros"] + testes["timeout"]
    score -= min(30, n_falhou * 10)

    # Penalidade por cobertura baixa (max 25)
    cob = cobertura["taxa_cobertura_modulos"]
    if cob < 25:
        score -= 25
    elif cob < 50:
        score -= 15
    elif cob < 75:
        score -= 8

    # Penalidade por arquivos grandes risco (max 10)
    n_risco = sum(1 for a in qualidade["arquivos_grandes"] if a["nivel"] == "risco")
    score -= min(10, n_risco * 3)

    # Penalidade por recomendacoes altas (max 20)
    n_altas = sum(1 for r in recomendacoes if r["prioridade"] == "alta")
    score -= min(20, n_altas * 5)

    return max(10, score)


# ─── ETAPA 6 — Relatorio ──────────────────────────────────────────────────────

def _etapa6_relatorio(testes: dict, cobertura: dict, qualidade: dict, deps: dict,
                      recomendacoes: list, score: int, narrativa: str) -> dict:
    """Salva relatorio JSON e appenda no historico."""
    agora = datetime.now().isoformat(timespec="seconds")

    relatorio = {
        "data_analise":   agora,
        "testes":         testes,
        "cobertura":      cobertura,
        "qualidade":      qualidade,
        "dependencias":   deps,
        "recomendacoes":  recomendacoes,
        "score_qualidade": score,
        "narrativa_llm":  narrativa,
    }

    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    _ARQ_REL.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info(f"[qualidade] relatorio salvo em {_ARQ_REL}")

    # Historico append-only (resumo compacto)
    historico: list = []
    if _ARQ_HIST.exists():
        try:
            historico = json.loads(_ARQ_HIST.read_text(encoding="utf-8"))
            if not isinstance(historico, list):
                historico = []
        except Exception:
            historico = []

    historico.append({
        "data":                    agora,
        "score":                   score,
        "taxa_testes":             testes["taxa_sucesso"],
        "taxa_cobertura_modulos":  cobertura["taxa_cobertura_modulos"],
        "total_recomendacoes":     len(recomendacoes),
        "recomendacoes_altas":     sum(1 for r in recomendacoes if r["prioridade"] == "alta"),
    })
    _ARQ_HIST.write_text(
        json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return relatorio


# ─── ETAPA 7 — Handoffs ───────────────────────────────────────────────────────

def _etapa7_handoffs(recomendacoes: list) -> None:
    """Cria handoffs para agente_executor_melhorias."""
    altas  = [r for r in recomendacoes if r["prioridade"] == "alta"]
    medias = [r for r in recomendacoes if r["prioridade"] == "media"]

    handoffs: list = []
    if _ARQ_HF.exists():
        try:
            handoffs = json.loads(_ARQ_HF.read_text(encoding="utf-8"))
            if not isinstance(handoffs, list):
                handoffs = []
        except Exception:
            handoffs = []

    agora = datetime.now().isoformat(timespec="seconds")

    # Um handoff por recomendacao alta
    for rec in altas:
        handoffs.append({
            "id":          str(uuid.uuid4()),
            "origem":      NOME_AGENTE,
            "destino":     "agente_executor_melhorias",
            "tipo":        "recomendacao_qualidade",
            "prioridade":  "alta",
            "criado_em":   agora,
            "status":      "pendente",
            "payload": {
                "rec_id":       rec["id"],
                "categoria":    rec["categoria"],
                "descricao":    rec["descricao"],
                "acao":         rec["acao_sugerida"],
                "esforco":      rec["esforco_estimado"],
                "risco":        rec["risco_correcao"],
                "impacto":      rec["impacto"],
            },
        })

    # Handoff consolidado para medias
    if medias:
        handoffs.append({
            "id":         str(uuid.uuid4()),
            "origem":     NOME_AGENTE,
            "destino":    "agente_executor_melhorias",
            "tipo":       "recomendacoes_qualidade_consolidadas",
            "prioridade": "media",
            "criado_em":  agora,
            "status":     "pendente",
            "payload": {
                "total":         len(medias),
                "recomendacoes": medias,
            },
        })

    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    _ARQ_HF.write_text(
        json.dumps(handoffs, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info(f"[qualidade] {len(altas)} handoffs altos + 1 consolidado ({len(medias)} medias) gerados")


# ─── ETAPA 8 — Memoria ───────────────────────────────────────────────────────

def _etapa8_memoria(relatorio: dict) -> None:
    """Atualiza memoria do agente com delta vs analise anterior."""
    historico: list = []
    if _ARQ_HIST.exists():
        try:
            historico = json.loads(_ARQ_HIST.read_text(encoding="utf-8"))
        except Exception:
            historico = []

    score_atual = relatorio["score_qualidade"]
    cob_atual   = relatorio["cobertura"]["taxa_cobertura_modulos"]
    taxa_atual  = relatorio["testes"]["taxa_sucesso"]

    delta_score = None
    delta_cob   = None
    delta_taxa  = None

    if len(historico) >= 2:
        anterior    = historico[-2]  # penultimo (o ultimo e o atual)
        delta_score = score_atual - anterior.get("score", score_atual)
        delta_cob   = cob_atual   - anterior.get("taxa_cobertura_modulos", cob_atual)
        delta_taxa  = taxa_atual  - anterior.get("taxa_testes", taxa_atual)

    def _fmt_delta(d):
        if d is None:
            return "(primeira analise)"
        sinal = "+" if d >= 0 else ""
        return f"{sinal}{d:.1f}"

    resumo = (
        f"Ultima analise: score={score_atual}/100 ({_fmt_delta(delta_score)}), "
        f"cobertura_modulos={cob_atual}% ({_fmt_delta(delta_cob)}), "
        f"testes_taxa={taxa_atual}% ({_fmt_delta(delta_taxa)}), "
        f"recomendacoes_altas={relatorio['testes']['falharam']}"
    )

    atualizar_memoria_agente(NOME_AGENTE, {
        "ultima_analise":          relatorio["data_analise"],
        "score":                   score_atual,
        "taxa_testes":             taxa_atual,
        "taxa_cobertura_modulos":  cob_atual,
        "total_recomendacoes":     len(relatorio["recomendacoes"]),
        "resumo":                  resumo,
    })
    log.info(f"[qualidade] memoria atualizada: {resumo}")
