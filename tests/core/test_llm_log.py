"""
tests/core/test_llm_log.py -- Auditoria de chamadas LLM

Roda com: python tests/core/test_llm_log.py
"""

import sys
import io
import json
import tempfile
from pathlib import Path
from datetime import date

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
import core.llm_log as llm_log_mod
from core.llm_log import (
    registrar_chamada_llm,
    carregar_log,
    resumo_custos_dia,
    resumo_custos_periodo,
)


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _patch(tmpdir: str):
    llm_log_mod._ARQ_LOG = Path(tmpdir) / "log_llm.json"
    llm_log_mod._ARQ_INCIDENTES = Path(tmpdir) / "log_llm_incidentes.json"


def _restore():
    llm_log_mod._ARQ_LOG = config.PASTA_DADOS / "log_llm.json"
    llm_log_mod._ARQ_INCIDENTES = config.PASTA_DADOS / "log_llm_incidentes.json"


def _entrada_dry_run(agente="agente_teste", tipo="classificar", payload_chars=200):
    return {
        "agente": agente,
        "tipo_tarefa": tipo,
        "modelo_usado": "dry-run",
        "modo": "dry-run",
        "tokens_entrada": 0,
        "tokens_saida": 0,
        "custo_estimado_usd": 0.0,
        "sucesso": True,
        "fallback_usado": False,
        "erro": None,
        "payload_chars": payload_chars,
        "modelo_simulado": "claude-haiku-4-5-20251001",
        "ciclo_id": None,
    }


def test_registrar_chamada_dry_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            registrar_chamada_llm(_entrada_dry_run())
            log = carregar_log()
            check(len(log) == 1, "deve ter 1 entrada no log")
            check(log[0].get("agente") == "agente_teste", "agente deve ser 'agente_teste'")
        finally:
            _restore()
    print("OK: registrar_chamada_dry_run")


def test_registrar_campos_obrigatorios():
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            registrar_chamada_llm(_entrada_dry_run())
            log = carregar_log()
            entrada = log[0]
            campos = [
                "timestamp", "agente", "tipo_tarefa", "modelo_usado",
                "modo", "tokens_entrada", "tokens_saida",
                "custo_estimado_usd", "custo_estimado_real",
                "sucesso", "fallback_usado", "erro",
            ]
            for campo in campos:
                check(campo in entrada, f"campo '{campo}' deve estar na entrada do log")
        finally:
            _restore()
    print("OK: registrar_campos_obrigatorios")


def test_custo_estimado_real_maior_zero():
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            entrada = _entrada_dry_run(payload_chars=400)
            registrar_chamada_llm(entrada)
            log = carregar_log()
            check(
                log[0].get("custo_estimado_real", 0.0) > 0.0,
                "custo_estimado_real deve ser > 0 quando payload_chars > 0 e modelo_simulado definido"
            )
        finally:
            _restore()
    print("OK: custo_estimado_real_maior_zero")


def test_resumo_custos_dia_vazio():
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            resumo = resumo_custos_dia()
            check(isinstance(resumo, dict), "resumo deve ser dict")
            check(resumo.get("total_chamadas") == 0, "total_chamadas deve ser 0 sem dados")
        finally:
            _restore()
    print("OK: resumo_custos_dia_vazio")


def test_resumo_custos_dia_com_dados():
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            registrar_chamada_llm(_entrada_dry_run())
            hoje = date.today().isoformat()
            resumo = resumo_custos_dia(hoje)
            check(resumo.get("total_chamadas") == 1, "total_chamadas deve ser 1")
        finally:
            _restore()
    print("OK: resumo_custos_dia_com_dados")


def test_resumo_custos_periodo_vazio():
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            resumo = resumo_custos_periodo(dias=7)
            check(isinstance(resumo, dict), "resumo periodo deve ser dict")
            check(resumo.get("total_chamadas") == 0, "total_chamadas deve ser 0 sem dados")
        finally:
            _restore()
    print("OK: resumo_custos_periodo_vazio")


def test_carregar_log_vazio():
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            log = carregar_log()
            check(log == [], "carregar_log sem arquivo deve retornar lista vazia")
        finally:
            _restore()
    print("OK: carregar_log_vazio")


def test_multiplas_chamadas_acumulam():
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            for i in range(3):
                registrar_chamada_llm(_entrada_dry_run(agente=f"agente_{i}"))
            log = carregar_log()
            check(len(log) == 3, f"deve ter 3 entradas no log (got {len(log)})")
        finally:
            _restore()
    print("OK: multiplas_chamadas_acumulam")


if __name__ == "__main__":
    testes = [
        test_registrar_chamada_dry_run,
        test_registrar_campos_obrigatorios,
        test_custo_estimado_real_maior_zero,
        test_resumo_custos_dia_vazio,
        test_resumo_custos_dia_com_dados,
        test_resumo_custos_periodo_vazio,
        test_carregar_log_vazio,
        test_multiplas_chamadas_acumulam,
    ]
    falhos = []
    for t in testes:
        try:
            t()
        except AssertionError as e:
            falhos.append(f"{t.__name__}: {e}")
        except Exception as e:
            falhos.append(f"{t.__name__}: ERRO INESPERADO: {e}")
            import traceback; traceback.print_exc()

    print(f"\nResultado: {len(testes)-len(falhos)}/{len(testes)} testes passaram")
    if falhos:
        print("Falhos:")
        for f in falhos:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("TODOS OS TESTES PASSARAM")
