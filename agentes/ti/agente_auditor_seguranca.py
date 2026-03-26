"""
agentes/ti/agente_auditor_seguranca.py

Auditor de segurança autônomo da Vetor — white hacker interno.

Responsabilidade:
  Analisar código e configuração do sistema de forma ESTÁTICA e passiva,
  identificar vulnerabilidades e gerar relatórios acionáveis para o conselho.

  NUNCA modifica código.
  NUNCA executa código encontrado.
  NUNCA loga dados sensíveis — apenas referências (arquivo + linha).

Etapas:
  1. Inventário do sistema
  2. Exposição de dados sensíveis
  3. Vulnerabilidades no código
  4. Análise de configuração
  5. Análise de resiliência
  6. Análise LLM (dry-run por padrão)
  7. Gerar relatório de segurança
  8. Escalar ao conselho se necessário
  9. Atualizar memória do agente

Arquivos gerenciados:
  dados/relatorio_seguranca.json          — relatório mais recente
  dados/historico_auditorias_seguranca.json — histórico append-only
"""

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

import config
from core.llm_router import LLMRouter
from core.llm_memoria import atualizar_memoria_agente
from core.controle_agente import configurar_log_agente

# ─── Constantes ───────────────────────────────────────────────────────────────

NOME_AGENTE = "agente_auditor_seguranca"

_ARQ_RELATORIO  = config.PASTA_DADOS / "relatorio_seguranca.json"
_ARQ_HISTORICO  = config.PASTA_DADOS / "historico_auditorias_seguranca.json"
_ARQ_DELIBS     = config.PASTA_DADOS / "deliberacoes_conselho.json"
_ARQ_HANDOFFS   = config.PASTA_DADOS / "handoffs_agentes.json"

_ROOT = Path(__file__).parent.parent.parent  # raiz do projeto

log = logging.getLogger(__name__)

# ─── Padrões de análise estática ──────────────────────────────────────────────

# Regex: possíveis API keys hardcoded (sk-ant-, Bearer, passwords, tokens)
_RE_API_KEY_ANTHROPIC = re.compile(r'sk-ant-[a-zA-Z0-9\-_]{20,}')
_RE_BEARER_TOKEN      = re.compile(r'Bearer\s+[a-zA-Z0-9\-_.]{20,}')
_RE_PASSWORD_INLINE   = re.compile(
    r'(?:password|senha|pwd|secret|token|api_key)\s*=\s*["\'][^"\']{6,}["\']',
    re.IGNORECASE
)
_RE_GENERIC_KEY_LONG  = re.compile(
    r'(?:key|token|secret|credential)\s*=\s*["\'][a-zA-Z0-9+/=_\-]{32,}["\']',
    re.IGNORECASE
)

# Regex: dados pessoais em código/logs
_RE_EMAIL_LOG   = re.compile(r'(?:print|log\.\w+|logging\.\w+)\s*\(.*?[\w.+-]+@[\w-]+\.[a-z]{2,}', re.IGNORECASE)
_RE_CPF         = re.compile(r'\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b')
_RE_PHONE_BR    = re.compile(r'\b(?:\+55\s?)?(?:\(?\d{2}\)?\s?)(?:9\s?)?\d{4}[-\s]?\d{4}\b')

# Regex: execuções dinâmicas perigosas
_RE_EVAL        = re.compile(r'\beval\s*\(')
_RE_EXEC        = re.compile(r'\bexec\s*\(')
_RE_DUNDER_IMP  = re.compile(r'__import__\s*\(')
_RE_PICKLE      = re.compile(r'pickle\.load\s*\(')
_RE_OS_SYSTEM   = re.compile(r'\bos\.system\s*\(')
_RE_SUBPROCESS  = re.compile(r'subprocess\.(call|run|Popen)\s*\(.*?shell\s*=\s*True', re.DOTALL)
_RE_PATH_JOIN_INPUT = re.compile(
    r'(?:os\.path\.join|Path)\s*\([^)]*(?:input|request|user|param|arg|query)[^)]*\)',
    re.IGNORECASE
)

# Regex: try/except genérico engolindo erros
_RE_BARE_EXCEPT = re.compile(r'except\s*(?:Exception|BaseException)?\s*:\s*\n\s*pass\b')

# Regex: SQL injection
_RE_SQL_FORMAT  = re.compile(
    r'(?:execute|query)\s*\(\s*(?:f["\']|["\'][^"\']*%s|["\'][^"\']*\{)',
    re.IGNORECASE
)

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


def _nova_vuln(severidade: str, categoria: str, arquivo: str,
               linha: int, descricao: str, recomendacao: str,
               esforco: str = "baixo", risco_correcao: str = "baixo") -> dict:
    return {
        "id":               f"vuln_{uuid.uuid4().hex[:8]}",
        "severidade":       severidade,
        "categoria":        categoria,
        "arquivo":          arquivo,
        "linha":            linha,
        "descricao":        descricao,
        "recomendacao":     recomendacao,
        "esforco_estimado": esforco,
        "risco_correcao":   risco_correcao,
    }


# ─── ETAPA 1: Inventário ──────────────────────────────────────────────────────

def _etapa1_inventario() -> dict:
    log.info("  [ETAPA 1] Inventário do sistema...")

    # Arquivos Python (exclui o próprio arquivo do auditor para evitar falsos positivos
    # nos padrões de regex definidos aqui)
    _self = Path(__file__).resolve()
    py_files = [p for p in _ROOT.rglob("*.py")
                if ".git" not in p.parts
                and "__pycache__" not in p.parts
                and p.resolve() != _self]

    # Linhas de código (conta linhas não vazias)
    total_linhas = 0
    for f in py_files:
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
            total_linhas += sum(1 for l in lines if l.strip())
        except Exception:
            pass

    # Arquivos JSON em dados/
    pasta_dados = _ROOT / "dados"
    json_files = list(pasta_dados.glob("*.json")) if pasta_dados.exists() else []

    # Variáveis de ambiente
    env_files = []
    for nome in (".env", ".env.example", ".env.sample", ".env.local"):
        p = _ROOT / nome
        if p.exists():
            env_files.append(nome)

    # requirements.txt
    req_file = _ROOT / "requirements.txt"
    dependencias = []
    if req_file.exists():
        for linha in req_file.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#"):
                dependencias.append(linha)

    # Módulos (subpastas com __init__.py)
    modulos = []
    for p in _ROOT.rglob("__init__.py"):
        if ".git" not in p.parts and "__pycache__" not in p.parts:
            modulos.append(str(p.parent.relative_to(_ROOT)))

    snap = {
        "total_py_files":   len(py_files),
        "total_linhas_nao_vazias": total_linhas,
        "total_json_dados": len(json_files),
        "total_modulos":    len(modulos),
        "total_dependencias": len(dependencias),
        "env_files_presentes": env_files,
        "dependencias":     dependencias,
        "modulos":          modulos,
        "py_files":         [str(f.relative_to(_ROOT)) for f in py_files],
        "json_dados":       [f.name for f in json_files],
    }
    log.info(f"    {snap['total_py_files']} arquivos .py · "
             f"{snap['total_linhas_nao_vazias']} linhas · "
             f"{snap['total_json_dados']} JSONs em dados/")
    return snap


# ─── ETAPA 2: Exposição de dados sensíveis ────────────────────────────────────

def _etapa2_exposicao(py_files: list) -> list:
    log.info("  [ETAPA 2] Análise de exposição de dados sensíveis...")
    vulns = []

    for arq_path in py_files:
        try:
            conteudo = arq_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        rel = str(arq_path.relative_to(_ROOT))
        linhas = conteudo.splitlines()

        for i, linha in enumerate(linhas, 1):
            # API key Anthropic hardcoded
            if _RE_API_KEY_ANTHROPIC.search(linha):
                vulns.append(_nova_vuln(
                    "critico", "exposicao_dados", rel, i,
                    "Possível API key Anthropic (sk-ant-...) hardcoded no código",
                    "Mover para variável de ambiente .env e carregar com os.environ.get()",
                    "baixo", "baixo",
                ))

            # Bearer token hardcoded
            if _RE_BEARER_TOKEN.search(linha):
                vulns.append(_nova_vuln(
                    "critico", "exposicao_dados", rel, i,
                    "Token Bearer hardcoded detectado",
                    "Mover para .env; nunca commitar credenciais no código",
                    "baixo", "baixo",
                ))

            # Senha/token inline
            if _RE_PASSWORD_INLINE.search(linha):
                # Ignorar comentários e exemplos óbvios
                stripped = linha.strip()
                if not stripped.startswith("#") and "example" not in linha.lower() \
                        and "placeholder" not in linha.lower():
                    vulns.append(_nova_vuln(
                        "alto", "exposicao_dados", rel, i,
                        "Possível credencial (password/token/secret) atribuída inline",
                        "Verificar se é valor real; se sim, mover para .env",
                        "baixo", "baixo",
                    ))

            # Chave genérica longa
            if _RE_GENERIC_KEY_LONG.search(linha):
                stripped = linha.strip()
                if not stripped.startswith("#"):
                    vulns.append(_nova_vuln(
                        "medio", "exposicao_dados", rel, i,
                        "String longa atribuída a variável com nome de credencial",
                        "Confirmar se é valor real; preferir variáveis de ambiente",
                        "baixo", "baixo",
                    ))

            # Email em log/print
            if _RE_EMAIL_LOG.search(linha):
                vulns.append(_nova_vuln(
                    "medio", "exposicao_dados", rel, i,
                    "Possível email de cliente sendo logado/impresso em texto plano",
                    "Mascarar dados pessoais em logs: email[:3]+'***@***'",
                    "baixo", "baixo",
                ))

            # CPF em código
            if _RE_CPF.search(linha) and not linha.strip().startswith("#"):
                vulns.append(_nova_vuln(
                    "alto", "exposicao_dados", rel, i,
                    "Padrão de CPF detectado no código (dado pessoal sensível — LGPD)",
                    "Verificar se CPF real está hardcoded; se sim, remover",
                    "baixo", "baixo",
                ))

    # Verificar se .env está no .gitignore
    gitignore = _ROOT / ".gitignore"
    if gitignore.exists():
        conteudo_gi = gitignore.read_text(encoding="utf-8")
        if ".env" not in conteudo_gi:
            vulns.append(_nova_vuln(
                "critico", "exposicao_dados", ".gitignore", 0,
                ".env NÃO está coberto pelo .gitignore — credenciais podem ser commitadas",
                "Adicionar linha '.env' ao .gitignore imediatamente",
                "baixo", "baixo",
            ))
        if "dados/" not in conteudo_gi and "dados" not in conteudo_gi:
            vulns.append(_nova_vuln(
                "alto", "exposicao_dados", ".gitignore", 0,
                "Pasta dados/ NÃO está no .gitignore — dados de clientes podem ser commitados",
                "Adicionar 'dados/' ao .gitignore",
                "baixo", "baixo",
            ))
    else:
        vulns.append(_nova_vuln(
            "critico", "exposicao_dados", ".gitignore", 0,
            ".gitignore não encontrado — risco alto de commitar credenciais e dados",
            "Criar .gitignore cobrindo: .env, dados/, logs/, __pycache__/",
            "baixo", "baixo",
        ))

    log.info(f"    {len(vulns)} achados de exposição")
    return vulns


# ─── ETAPA 3: Vulnerabilidades no código ─────────────────────────────────────

def _etapa3_vulnerabilidades_codigo(py_files: list) -> list:
    log.info("  [ETAPA 3] Análise de vulnerabilidades no código...")
    vulns = []

    for arq_path in py_files:
        try:
            conteudo = arq_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        rel = str(arq_path.relative_to(_ROOT))
        linhas = conteudo.splitlines()

        for i, linha in enumerate(linhas, 1):
            stripped = linha.strip()
            if stripped.startswith("#"):
                continue

            # eval()
            if _RE_EVAL.search(linha):
                vulns.append(_nova_vuln(
                    "critico", "execucao_perigosa", rel, i,
                    "eval() detectado — execução dinâmica de código arbitrário",
                    "Substituir por json.loads(), ast.literal_eval() ou lógica explícita",
                    "medio", "medio",
                ))

            # exec()
            if _RE_EXEC.search(linha):
                vulns.append(_nova_vuln(
                    "critico", "execucao_perigosa", rel, i,
                    "exec() detectado — execução dinâmica de código arbitrário",
                    "Refatorar para importação explícita ou mapeamento de funções",
                    "medio", "medio",
                ))

            # __import__
            if _RE_DUNDER_IMP.search(linha):
                vulns.append(_nova_vuln(
                    "alto", "execucao_perigosa", rel, i,
                    "__import__() detectado — importação dinâmica pode ser vetor de ataque",
                    "Preferir importlib.import_module() com validação do nome do módulo",
                    "medio", "baixo",
                ))

            # pickle.load
            if _RE_PICKLE.search(linha):
                vulns.append(_nova_vuln(
                    "alto", "execucao_perigosa", rel, i,
                    "pickle.load() detectado — desserialização insegura de dados não confiáveis",
                    "Substituir por json.loads(); nunca deserializar pickle de fonte externa",
                    "medio", "baixo",
                ))

            # os.system
            if _RE_OS_SYSTEM.search(linha):
                vulns.append(_nova_vuln(
                    "alto", "execucao_perigosa", rel, i,
                    "os.system() detectado — preferir subprocess com lista de argumentos",
                    "Usar subprocess.run(['cmd', 'arg1'], check=True) sem shell=True",
                    "baixo", "baixo",
                ))

            # subprocess com shell=True
            if _RE_SUBPROCESS.search(linha):
                vulns.append(_nova_vuln(
                    "alto", "execucao_perigosa", rel, i,
                    "subprocess chamado com shell=True — injection por entrada não sanitizada",
                    "Passar argumentos como lista: subprocess.run(['cmd', arg], check=True)",
                    "baixo", "baixo",
                ))

            # SQL injection
            if _RE_SQL_FORMAT.search(linha):
                vulns.append(_nova_vuln(
                    "critico", "execucao_perigosa", rel, i,
                    "Possível SQL injection — query construída com formatação de string",
                    "Usar parâmetros preparados (cursor.execute(sql, (param,)))",
                    "medio", "baixo",
                ))

            # Path traversal
            if _RE_PATH_JOIN_INPUT.search(linha):
                vulns.append(_nova_vuln(
                    "alto", "execucao_perigosa", rel, i,
                    "Caminho de arquivo construído com variável de input — risco de path traversal",
                    "Validar e normalizar o caminho: usar .resolve() e verificar se está dentro da pasta permitida",
                    "medio", "baixo",
                ))

        # Bloco try/except bare (análise multiline simplificada)
        if _RE_BARE_EXCEPT.search(conteudo):
            vulns.append(_nova_vuln(
                "medio", "execucao_perigosa", rel, 0,
                "try/except genérico com 'pass' detectado — erros engolidos silenciosamente",
                "Logar o erro (log.warning(exc)) antes do pass, ou tratar especificamente",
                "baixo", "baixo",
            ))

    log.info(f"    {len(vulns)} achados de vulnerabilidade de código")
    return vulns


# ─── ETAPA 4: Configuração ────────────────────────────────────────────────────

def _etapa4_configuracao() -> list:
    log.info("  [ETAPA 4] Análise de configuração...")
    vulns = []

    # .gitignore — cobertura
    gitignore = _ROOT / ".gitignore"
    if gitignore.exists():
        gi_conteudo = gitignore.read_text(encoding="utf-8")
        for item, descricao in [
            ("__pycache__", "Cache Python"),
            ("*.pyc",       "Bytecode compilado"),
            ("logs/",       "Pasta de logs"),
        ]:
            if item not in gi_conteudo:
                vulns.append(_nova_vuln(
                    "baixo", "configuracao", ".gitignore", 0,
                    f"{descricao} ({item}) não coberto pelo .gitignore",
                    f"Adicionar '{item}' ao .gitignore",
                    "baixo", "baixo",
                ))

    # requirements.txt — versões fixadas
    req_file = _ROOT / "requirements.txt"
    if req_file.exists():
        nao_fixadas = []
        for linha in req_file.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha or linha.startswith("#"):
                continue
            # Dependência sem versão fixa (sem ==)
            if "==" not in linha and ">=" not in linha and "<" not in linha:
                nao_fixadas.append(linha)
        if nao_fixadas:
            vulns.append(_nova_vuln(
                "medio", "configuracao", "requirements.txt", 0,
                f"Dependências sem versão fixada: {', '.join(nao_fixadas)} — risco de supply chain",
                "Fixar versões com == para todas as dependências (pip freeze > requirements.txt)",
                "baixo", "baixo",
            ))
        # Dependências com >= (menos grave, mas ainda relevante)
        com_range = [l.strip() for l in req_file.read_text(encoding="utf-8").splitlines()
                     if l.strip() and not l.strip().startswith("#") and ">=" in l and "==" not in l]
        if com_range:
            vulns.append(_nova_vuln(
                "baixo", "configuracao", "requirements.txt", 0,
                f"Dependências com versão mínima (>=) mas não fixadas: {', '.join(com_range[:3])}",
                "Considerar fixar com == para reproducibilidade garantida",
                "baixo", "baixo",
            ))

    # config.py — não deve ter credenciais
    config_file = _ROOT / "config.py"
    if config_file.exists():
        conteudo_cfg = config_file.read_text(encoding="utf-8", errors="ignore")
        if _RE_API_KEY_ANTHROPIC.search(conteudo_cfg):
            vulns.append(_nova_vuln(
                "critico", "configuracao", "config.py", 0,
                "API key Anthropic detectada em config.py",
                "Remover imediatamente; usar .env com os.environ.get('ANTHROPIC_API_KEY')",
                "baixo", "baixo",
            ))
        if _RE_PASSWORD_INLINE.search(conteudo_cfg):
            vulns.append(_nova_vuln(
                "alto", "configuracao", "config.py", 0,
                "Possível credencial inline em config.py",
                "Mover para .env; config.py não deve conter segredos",
                "baixo", "baixo",
            ))

    # Painel do conselho — proteção de acesso
    app_file = _ROOT / "conselho_app" / "app.py"
    if app_file.exists():
        conteudo_app = app_file.read_text(encoding="utf-8", errors="ignore")
        tem_auth = any(kw in conteudo_app for kw in
                       ["Depends(", "HTTPBasic", "OAuth2", "api_key", "Authorization",
                        "middleware", "authenticate"])
        if not tem_auth:
            vulns.append(_nova_vuln(
                "alto", "configuracao", "conselho_app/app.py", 0,
                "Painel do conselho (FastAPI) sem autenticação detectada — acesso aberto",
                "Adicionar HTTPBasic ou token simples; mínimo: acessível apenas em rede local",
                "medio", "medio",
            ))

        # CORS
        tem_cors = "CORSMiddleware" in conteudo_app or "add_middleware" in conteudo_app
        if not tem_cors:
            vulns.append(_nova_vuln(
                "informativo", "configuracao", "conselho_app/app.py", 0,
                "CORS não configurado explicitamente no painel FastAPI",
                "Se exposto à rede, configurar CORSMiddleware com origins explícitas",
                "baixo", "baixo",
            ))

    # LLM Router — timeout configurado
    router_file = _ROOT / "core" / "llm_router.py"
    if router_file.exists():
        conteudo_r = router_file.read_text(encoding="utf-8", errors="ignore")
        if "timeout" not in conteudo_r.lower():
            vulns.append(_nova_vuln(
                "medio", "configuracao", "core/llm_router.py", 0,
                "Timeout não encontrado nas chamadas LLM — risco de hang em modo real",
                "Garantir timeout em todas as chamadas HTTP ao LLM (config.LLM_TIMEOUT)",
                "baixo", "baixo",
            ))

    log.info(f"    {len(vulns)} achados de configuração")
    return vulns


# ─── ETAPA 5: Resiliência ─────────────────────────────────────────────────────

def _etapa5_resiliencia() -> list:
    log.info("  [ETAPA 5] Análise de resiliência...")
    vulns = []

    # Escrita concorrente em JSON — verificar se há uso de lock
    pasta_dados = _ROOT / "dados"
    modulos_core = list((_ROOT / "core").glob("*.py")) if (_ROOT / "core").exists() else []
    usa_filelock = False
    usa_threading_lock = False
    for arq in modulos_core:
        try:
            c = arq.read_text(encoding="utf-8", errors="ignore")
            if "filelock" in c.lower() or "FileLock" in c:
                usa_filelock = True
            if "threading.Lock" in c or "RLock" in c:
                usa_threading_lock = True
        except Exception:
            pass

    if not usa_filelock and not usa_threading_lock:
        vulns.append(_nova_vuln(
            "medio", "resiliencia", "core/", 0,
            "Escrita em arquivos JSON sem mecanismo de lock detectado — risco de corrupção em execução concorrente",
            "Para múltiplos agentes simultâneos, considerar filelock ou serialização de escrita via fila",
            "medio", "medio",
        ))

    # Lock do scheduler — stale lock
    sched_file = _ROOT / "core" / "scheduler.py"
    if sched_file.exists():
        conteudo_s = sched_file.read_text(encoding="utf-8", errors="ignore")
        tem_stale_check = "stale" in conteudo_s.lower() or "lock" in conteudo_s.lower()
        tem_timeout_lock = "timeout" in conteudo_s.lower() and "lock" in conteudo_s.lower()
        if not tem_stale_check:
            vulns.append(_nova_vuln(
                "baixo", "resiliencia", "core/scheduler.py", 0,
                "Scheduler não tem verificação de stale lock — crash pode deixar agente travado",
                "Adicionar verificação de timeout no lock: se lock > N minutos, liberar",
                "medio", "baixo",
            ))

    # Fallback do LLM Router
    router_file = _ROOT / "core" / "llm_router.py"
    if router_file.exists():
        conteudo_r = router_file.read_text(encoding="utf-8", errors="ignore")
        tem_fallback = "fallback" in conteudo_r.lower() or "dry" in conteudo_r.lower()
        if not tem_fallback:
            vulns.append(_nova_vuln(
                "medio", "resiliencia", "core/llm_router.py", 0,
                "LLM Router sem fallback detectado — se API cair em modo real, agentes quebram",
                "Garantir fallback para dry-run quando API LLM não responder",
                "baixo", "baixo",
            ))

    # Ausência de timeout nos agentes
    agentes_sem_timeout = []
    agentes_dir = _ROOT / "agentes"
    if agentes_dir.exists():
        for arq in agentes_dir.rglob("agente_*.py"):
            try:
                c = arq.read_text(encoding="utf-8", errors="ignore")
                if "timeout" not in c.lower() and "signal" not in c.lower():
                    agentes_sem_timeout.append(str(arq.relative_to(_ROOT)))
            except Exception:
                pass

    if len(agentes_sem_timeout) > 2:
        vulns.append(_nova_vuln(
            "medio", "resiliencia",
            f"agentes/ ({len(agentes_sem_timeout)} arquivos)", 0,
            f"{len(agentes_sem_timeout)} agentes sem timeout próprio — risco de loop eterno travando o scheduler",
            "Adicionar timeout de execução via signal.alarm (Unix) ou thread com join(timeout=N)",
            "medio", "medio",
        ))

    # dados/ sem backup
    backup_script = any([
        (_ROOT / "backup.py").exists(),
        (_ROOT / "backup.sh").exists(),
        (_ROOT / "scripts").exists(),
    ])
    if not backup_script:
        vulns.append(_nova_vuln(
            "baixo", "resiliencia", "infraestrutura", 0,
            "Nenhum script de backup de dados/ identificado — perda total possível",
            "Criar script de backup periódico de dados/ (zip + timestamp); considerar S3/GDrive",
            "medio", "baixo",
        ))

    # config.py — CONFIABILIDADE_EMPRESA: lock sem TTL
    conf_emp = _ROOT / "core" / "confiabilidade_empresa.py"
    if conf_emp.exists():
        c = conf_emp.read_text(encoding="utf-8", errors="ignore")
        tem_ttl = "ttl" in c.lower() or "max_" in c.lower() or "horas" in c.lower() or "minutos" in c.lower()
        if not tem_ttl:
            vulns.append(_nova_vuln(
                "baixo", "resiliencia", "core/confiabilidade_empresa.py", 0,
                "Lock de ciclo sem TTL explícito detectado — possível lock eterno após crash",
                "Adicionar TTL ao lock de ciclo: liberar automaticamente se > N horas",
                "baixo", "baixo",
            ))

    log.info(f"    {len(vulns)} achados de resiliência")
    return vulns


# ─── ETAPA 6: Análise LLM ─────────────────────────────────────────────────────

def _etapa6_llm(snapshot: dict, todas_vulns: list) -> str:
    log.info("  [ETAPA 6] Análise LLM dos achados...")

    # Resumo compacto para o LLM (sem dados sensíveis)
    resumo_vulns = {
        sev: [{"arquivo": v["arquivo"], "descricao": v["descricao"]}
              for v in todas_vulns if v["severidade"] == sev]
        for sev in ("critico", "alto", "medio", "baixo", "informativo")
    }

    router = LLMRouter()
    resultado = router.analisar({
        "agente": NOME_AGENTE,
        "tarefa": "auditoria_seguranca",
        "dados": {
            "total_py_files":   snapshot["total_py_files"],
            "total_linhas":     snapshot["total_linhas_nao_vazias"],
            "total_dependencias": snapshot["total_dependencias"],
            "vulnerabilidades_por_severidade": {
                k: len(v) for k, v in resumo_vulns.items()
            },
            "criticas": resumo_vulns.get("critico", [])[:3],
            "altas":    resumo_vulns.get("alto",    [])[:3],
        },
    })

    if isinstance(resultado, dict):
        return resultado.get("analise", str(resultado))
    return str(resultado)


# ─── ETAPA 7: Relatório ───────────────────────────────────────────────────────

def _calcular_score(vulns: list) -> int:
    """
    Score de segurança 0-100.

    Pontuação por categoria (com teto por severidade para evitar score zero
    em projetos com muitos achados médios/baixos):
      - Críticas:  até -30 pts  (máx 2 antes de travar no teto)
      - Altas:     até -25 pts
      - Médias:    até -20 pts
      - Baixas:    até -10 pts
    Score mínimo possível: 15 (apenas com muitas críticas e altas)
    """
    contadores = {"critico": 0, "alto": 0, "medio": 0, "baixo": 0, "informativo": 0}
    for v in vulns:
        contadores[v["severidade"]] = contadores.get(v["severidade"], 0) + 1

    perda  = 0
    perda += min(30, contadores["critico"]    * 15)
    perda += min(25, contadores["alto"]       *  5)
    perda += min(20, contadores["medio"]      *  2)
    perda += min(10, contadores["baixo"]      *  1)
    return max(15, 100 - perda)


def _etapa7_relatorio(snapshot: dict, todas_vulns: list, narrativa: str) -> dict:
    log.info("  [ETAPA 7] Gerando relatório de segurança...")

    contadores = {sev: 0 for sev in ("critico", "alto", "medio", "baixo", "informativo")}
    for v in todas_vulns:
        contadores[v["severidade"]] = contadores.get(v["severidade"], 0) + 1

    score = _calcular_score(todas_vulns)

    relatorio = {
        "data_auditoria":    _agora(),
        "agente":            NOME_AGENTE,
        "snapshot_sistema":  {k: v for k, v in snapshot.items()
                              if k not in ("py_files", "json_dados", "modulos")},
        "vulnerabilidades":  todas_vulns,
        "resumo": {
            "total_vulnerabilidades": len(todas_vulns),
            "criticas":     contadores["critico"],
            "altas":        contadores["alto"],
            "medias":       contadores["medio"],
            "baixas":       contadores["baixo"],
            "informativas": contadores["informativo"],
            "score_seguranca": score,
        },
        "narrativa_llm": narrativa,
    }

    _salvar(_ARQ_RELATORIO, relatorio)
    log.info(f"    relatório salvo — score={score} criticas={contadores['critico']} altas={contadores['alto']}")
    return relatorio


def _etapa7_historico(relatorio: dict) -> None:
    historico = _ler(_ARQ_HISTORICO, [])
    entrada = {
        "data_auditoria":        relatorio["data_auditoria"],
        "score_seguranca":       relatorio["resumo"]["score_seguranca"],
        "total_vulnerabilidades": relatorio["resumo"]["total_vulnerabilidades"],
        "criticas":              relatorio["resumo"]["criticas"],
        "altas":                 relatorio["resumo"]["altas"],
    }
    historico.append(entrada)
    # Manter apenas últimas 50 auditorias
    _salvar(_ARQ_HISTORICO, historico[-50:])


# ─── ETAPA 8: Escalar ao conselho ────────────────────────────────────────────

def _etapa8_escalacao(relatorio: dict) -> None:
    resumo = relatorio["resumo"]
    log.info("  [ETAPA 8] Verificando necessidade de escalação...")

    if resumo["criticas"] > 0:
        _criar_deliberacao(relatorio)
    elif resumo["altas"] > 0:
        _criar_handoff(relatorio)
    else:
        log.info("    sem escalação necessária")


def _criar_deliberacao(relatorio: dict) -> None:
    delibs = _ler(_ARQ_DELIBS, [])

    # Verificar se já existe deliberação de segurança em aberto
    ja_existe = any(
        d.get("tipo") == "seguranca_critica" and d.get("status") in ("pendente", "em_analise")
        for d in delibs
    )
    if ja_existe:
        log.info("    deliberação de segurança crítica já existe em aberto — pulando")
        return

    resumo = relatorio["resumo"]
    top_criticas = [v["descricao"] for v in relatorio["vulnerabilidades"]
                    if v["severidade"] == "critico"][:3]

    delib = {
        "id":           f"delib_{uuid.uuid4().hex[:8]}",
        "tipo":         "seguranca_critica",
        "titulo":       f"SEGURANÇA: {resumo['criticas']} vulnerabilidade(s) crítica(s) detectada(s)",
        "descricao":    (
            f"Auditoria automática de {relatorio['data_auditoria'][:10]} identificou "
            f"{resumo['criticas']} vulnerabilidade(s) crítica(s) e {resumo['altas']} alta(s). "
            f"Score de segurança: {resumo['score_seguranca']}/100. "
            f"Principais achados: " + " | ".join(top_criticas)
        ),
        "urgencia":     "imediata",
        "impacto":      "alto",
        "status":       "pendente",
        "criado_em":    _agora(),
        "criado_por":   NOME_AGENTE,
        "referencia_ids": [],
    }
    delibs.append(delib)
    _salvar(_ARQ_DELIBS, delibs)
    log.info(f"    deliberação de segurança criada: {delib['id']}")


def _criar_handoff(relatorio: dict) -> None:
    handoffs = _ler(_ARQ_HANDOFFS, [])
    resumo   = relatorio["resumo"]

    # Verificar se já existe handoff de segurança pendente
    ja_existe = any(
        h.get("tipo") == "seguranca_alta" and h.get("status") == "pendente"
        for h in handoffs
    )
    if ja_existe:
        log.info("    handoff de segurança alta já existe — pulando")
        return

    handoff = {
        "id":          f"hoff_{uuid.uuid4().hex[:8]}",
        "tipo":        "seguranca_alta",
        "origem":      NOME_AGENTE,
        "destino":     "conselho",
        "status":      "pendente",
        "prioridade":  "alta",
        "titulo":      f"Segurança: {resumo['altas']} vulnerabilidade(s) alta(s) para revisão",
        "descricao":   (
            f"Auditoria de {relatorio['data_auditoria'][:10]}: "
            f"score={resumo['score_seguranca']}/100. "
            f"{resumo['altas']} alta(s), {resumo['medias']} média(s). "
            f"Consultar dados/relatorio_seguranca.json para detalhes."
        ),
        "criado_em":   _agora(),
        "payload": {
            "score_seguranca": resumo["score_seguranca"],
            "altas": resumo["altas"],
            "medias": resumo["medias"],
        },
    }
    handoffs.append(handoff)
    _salvar(_ARQ_HANDOFFS, handoffs)
    log.info(f"    handoff de segurança criado: {handoff['id']}")


# ─── ETAPA 9: Memória ─────────────────────────────────────────────────────────

def _etapa9_memoria(relatorio: dict) -> None:
    log.info("  [ETAPA 9] Atualizando memória do agente...")
    resumo = relatorio["resumo"]
    atualizar_memoria_agente(NOME_AGENTE, {
        "ultima_auditoria":        relatorio["data_auditoria"],
        "score_seguranca":         resumo["score_seguranca"],
        "total_vulnerabilidades":  resumo["total_vulnerabilidades"],
        "criticas":                resumo["criticas"],
        "altas":                   resumo["altas"],
        "medias":                  resumo["medias"],
    })


# ─── Ponto de entrada público ─────────────────────────────────────────────────

def executar() -> dict:
    """
    Executa o ciclo completo de auditoria de segurança.
    Retorna resumo do relatório gerado.
    """
    configurar_log_agente(NOME_AGENTE)
    log.info("=" * 60)
    log.info(f"AUDITOR DE SEGURANÇA ✦ {_agora()}")
    log.info("=" * 60)

    # Etapa 1 — Inventário
    snapshot = _etapa1_inventario()
    py_files = [_ROOT / p for p in snapshot["py_files"]]

    # Etapas 2-5 — Análise
    vulns_exposicao   = _etapa2_exposicao(py_files)
    vulns_codigo      = _etapa3_vulnerabilidades_codigo(py_files)
    vulns_config      = _etapa4_configuracao()
    vulns_resiliencia = _etapa5_resiliencia()

    todas_vulns = vulns_exposicao + vulns_codigo + vulns_config + vulns_resiliencia

    # Etapa 6 — LLM
    narrativa = _etapa6_llm(snapshot, todas_vulns)

    # Etapa 7 — Relatório
    relatorio = _etapa7_relatorio(snapshot, todas_vulns, narrativa)
    _etapa7_historico(relatorio)

    # Etapa 8 — Escalação
    _etapa8_escalacao(relatorio)

    # Etapa 9 — Memória
    _etapa9_memoria(relatorio)

    resumo = relatorio["resumo"]
    log.info("=" * 60)
    log.info(
        f"AUDITORIA CONCLUÍDA ✦ score={resumo['score_seguranca']}/100 "
        f"criticas={resumo['criticas']} altas={resumo['altas']} "
        f"medias={resumo['medias']} total={resumo['total_vulnerabilidades']}"
    )
    log.info("=" * 60)

    return relatorio["resumo"]
