"""
core/guardas_codigo.py

Modulo de protecao para o agente executor de melhorias.

Fornece:
  criar_backup_pre_mudanca()          — copia todos os .py para backup datado
  verificar_integridade_pos_mudanca() — py_compile + testes rapidos
  reverter_mudanca()                  — restaura arquivos do backup
  validar_mudanca_proposta()          — whitelist/blacklist de arquivos

Este modulo e chamado EXCLUSIVAMENTE por agente_executor_melhorias.
Qualquer outro uso deve ser revisado antes de aceito.
"""

import json
import logging
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger("guardas_codigo")

_ROOT         = Path(__file__).parent.parent
_DIR_BACKUPS  = config.PASTA_DADOS / "backups"
_MAX_BACKUPS  = 10
_TIMEOUT_TESTES_S = 120   # timeout para rodar a suite completa

# ─── Whitelist: apenas estas pastas (e config.py) podem ser alteradas ─────────
_WHITELIST_PASTAS = {
    str(_ROOT / "core"),
    str(_ROOT / "modulos"),
    str(_ROOT / "agentes"),
    str(_ROOT / "tests"),
}
_WHITELIST_ARQUIVOS = {
    str(_ROOT / "config.py"),
    str(_ROOT / "requirements.txt"),
    str(_ROOT / ".gitignore"),
}

# ─── Blacklist: estes arquivos NUNCA podem ser alterados ──────────────────────
_BLACKLIST_ARQUIVOS = {
    str(_ROOT / "main_scheduler.py"),
    str(_ROOT / "core" / "orquestrador_empresa.py"),
    str(_ROOT / "core" / "governanca_conselho.py"),
    str(_ROOT / "core" / "scheduler.py"),
    str(_ROOT / ".env"),
    str(_ROOT / "core" / "guardas_codigo.py"),   # nunca alterar as proprias guardas
}

# Limite de linhas alteradas por aplicacao
_MAX_LINHAS_ALTERADAS = 50


# ─── API publica ──────────────────────────────────────────────────────────────

def criar_backup_pre_mudanca() -> str:
    """
    Copia todos os .py do projeto para dados/backups/backup_TIMESTAMP/.
    Mantém apenas os ultimos _MAX_BACKUPS backups.
    Retorna o caminho absoluto do backup criado.
    """
    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = _DIR_BACKUPS / f"backup_{ts}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Pastas a copiar
    pastas_fonte = [
        _ROOT / "core",
        _ROOT / "agentes",
        _ROOT / "modulos",
        _ROOT / "tests",
    ]
    arquivos_raiz = list(_ROOT.glob("*.py"))
    arquivos_conf = [_ROOT / "requirements.txt", _ROOT / ".gitignore", _ROOT / "config.py"]

    copiados = 0
    for pasta in pastas_fonte:
        if not pasta.exists():
            continue
        for py in pasta.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            rel    = py.relative_to(_ROOT)
            destino = backup_dir / rel
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(py, destino)
            copiados += 1

    for arq in arquivos_raiz + arquivos_conf:
        if arq.exists():
            destino = backup_dir / arq.name
            shutil.copy2(arq, destino)
            copiados += 1

    log.info(f"[guardas] backup criado: {backup_dir} ({copiados} arquivos)")

    # Limpar backups antigos
    _limpar_backups_antigos()

    return str(backup_dir)


def verificar_integridade_pos_mudanca(backup_path: str) -> dict:
    """
    Verifica integridade apos uma mudanca:
      a) Todos os .py compilam (py_compile)
      b) Suite de testes passa

    Retorna: {"integro": bool, "erros": [...], "testes_passaram": N, "testes_falharam": N}
    """
    erros: list = []

    # a) Verificacao de compilacao
    for pasta in [_ROOT / "core", _ROOT / "agentes", _ROOT / "modulos"]:
        if not pasta.exists():
            continue
        for py in pasta.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "py_compile", str(py)],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode != 0:
                    erros.append(f"Compilacao falhou: {py.relative_to(_ROOT)} — {result.stderr.strip()[:120]}")
            except subprocess.TimeoutExpired:
                erros.append(f"Timeout ao compilar: {py.relative_to(_ROOT)}")
            except Exception as exc:
                erros.append(f"Erro ao compilar {py.relative_to(_ROOT)}: {exc}")

    if erros:
        return {"integro": False, "erros": erros, "testes_passaram": 0, "testes_falharam": 0}

    # b) Rodar suite de testes
    testes_passaram = 0
    testes_falharam = 0
    dir_testes = _ROOT / "tests"

    if dir_testes.exists():
        for arq_teste in sorted(dir_testes.rglob("test_*.py")):
            try:
                proc = subprocess.run(
                    [sys.executable, str(arq_teste)],
                    capture_output=True, text=True,
                    timeout=60, cwd=str(_ROOT),
                )
                if proc.returncode == 0:
                    testes_passaram += 1
                else:
                    testes_falharam += 1
                    saida = (proc.stdout + proc.stderr).strip()[-200:]
                    erros.append(f"Teste falhou: {arq_teste.relative_to(_ROOT)} — {saida}")
            except subprocess.TimeoutExpired:
                testes_falharam += 1
                erros.append(f"Timeout: {arq_teste.relative_to(_ROOT)}")
            except Exception as exc:
                testes_falharam += 1
                erros.append(f"Erro: {arq_teste.relative_to(_ROOT)} — {exc}")

    integro = (testes_falharam == 0 and not erros)
    return {
        "integro":          integro,
        "erros":            erros[:10],
        "testes_passaram":  testes_passaram,
        "testes_falharam":  testes_falharam,
    }


def reverter_mudanca(backup_path: str) -> bool:
    """
    Restaura todos os arquivos do backup para o projeto.
    Loga o rollback como incidente.
    Retorna True se rollback foi bem-sucedido.
    """
    bkp = Path(backup_path)
    if not bkp.exists():
        log.error(f"[guardas] backup nao encontrado: {backup_path}")
        return False

    restaurados = 0
    erros_rest  = []

    for arq_bkp in bkp.rglob("*"):
        if not arq_bkp.is_file():
            continue
        rel = arq_bkp.relative_to(bkp)
        destino = _ROOT / rel
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arq_bkp, destino)
            restaurados += 1
        except Exception as exc:
            erros_rest.append(f"{rel}: {exc}")

    sucesso = len(erros_rest) == 0
    log.warning(
        f"[guardas] ROLLBACK {'OK' if sucesso else 'PARCIAL'}: "
        f"{restaurados} arquivos restaurados de {backup_path}"
        + (f" | erros: {erros_rest[:3]}" if erros_rest else "")
    )

    # Registrar incidente
    _registrar_incidente_rollback(backup_path, restaurados, erros_rest)

    return sucesso


def validar_mudanca_proposta(arquivo: str, mudanca: dict) -> dict:
    """
    Valida se uma mudanca proposta pode ser aplicada.
    Retorna: {"permitida": bool, "motivo": str}
    """
    arq = Path(arquivo).resolve()

    # Arquivo deve existir
    if not arq.exists():
        return {"permitida": False, "motivo": f"Arquivo nao encontrado: {arquivo}"}

    arq_str = str(arq)

    # Blacklist tem prioridade absoluta
    if arq_str in _BLACKLIST_ARQUIVOS:
        return {"permitida": False, "motivo": f"Arquivo na blacklist de protecao: {arq.name}"}

    # Verificar se algum componente do caminho e blacklistado por nome
    nomes_blacklist = {"main_scheduler", "orquestrador_empresa",
                       "governanca_conselho", ".env"}
    if arq.stem in nomes_blacklist:
        return {"permitida": False, "motivo": f"Arquivo protegido: {arq.name}"}

    # Whitelist: deve estar em pasta ou arquivo permitido
    em_whitelist = arq_str in _WHITELIST_ARQUIVOS
    if not em_whitelist:
        for pasta in _WHITELIST_PASTAS:
            if arq_str.startswith(pasta):
                em_whitelist = True
                break

    if not em_whitelist:
        return {"permitida": False, "motivo": f"Arquivo fora da whitelist: {arquivo}"}

    # Tamanho da mudanca
    linhas_alteradas = mudanca.get("linhas_alteradas", 0)
    if linhas_alteradas > _MAX_LINHAS_ALTERADAS:
        return {
            "permitida": False,
            "motivo": f"Mudanca muito grande: {linhas_alteradas} linhas > {_MAX_LINHAS_ALTERADAS} permitidas",
        }

    return {"permitida": True, "motivo": "ok"}


# ─── Internos ─────────────────────────────────────────────────────────────────

def _limpar_backups_antigos() -> None:
    """Remove backups excedentes, mantendo apenas os _MAX_BACKUPS mais recentes."""
    if not _DIR_BACKUPS.exists():
        return
    backups = sorted(
        [d for d in _DIR_BACKUPS.iterdir() if d.is_dir() and d.name.startswith("backup_")],
        key=lambda d: d.name,
    )
    excedentes = backups[: max(0, len(backups) - _MAX_BACKUPS)]
    for bkp in excedentes:
        try:
            shutil.rmtree(bkp)
            log.info(f"[guardas] backup antigo removido: {bkp.name}")
        except Exception as exc:
            log.warning(f"[guardas] falha ao remover backup {bkp.name}: {exc}")


def _registrar_incidente_rollback(backup_path: str, restaurados: int, erros: list) -> None:
    """Appenda incidente de rollback no log de incidentes."""
    arq = config.PASTA_DADOS / "incidentes_executor.json"
    historico: list = []
    if arq.exists():
        try:
            historico = json.loads(arq.read_text(encoding="utf-8"))
        except Exception:
            historico = []
    historico.append({
        "tipo":         "rollback",
        "timestamp":    datetime.now().isoformat(timespec="seconds"),
        "backup_path":  backup_path,
        "restaurados":  restaurados,
        "erros":        erros[:5],
    })
    try:
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        log.warning(f"[guardas] falha ao salvar incidente: {exc}")
