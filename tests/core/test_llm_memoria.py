"""
tests/core/test_llm_memoria.py -- Memoria persistente de contexto LLM

Roda com: python tests/core/test_llm_memoria.py
"""

import sys
import io
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
import core.llm_memoria as mem_mod
from core.llm_memoria import (
    atualizar_memoria_conta,
    obter_memoria_conta,
    atualizar_memoria_agente,
    obter_memoria_agente,
    gerar_contexto_llm,
    listar_contas_com_memoria,
    listar_agentes_com_memoria,
)


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _patch(tmpdir: str):
    mem_mod._ARQ_MEMORIA = Path(tmpdir) / "memoria_agentes.json"


def _restore(orig):
    mem_mod._ARQ_MEMORIA = orig


def test_atualizar_e_obter_memoria_conta():
    orig = mem_mod._ARQ_MEMORIA
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            atualizar_memoria_conta("emp_001", {
                "resumo": "Barbearia do Ze",
                "contexto_comercial": "proposta enviada",
                "canais_tentados": ["email"],
            })
            mem = obter_memoria_conta("emp_001")
            check(mem is not None, "memoria deve existir apos atualizar")
            check(mem.get("resumo") == "Barbearia do Ze", "resumo deve ser salvo")
            check(mem.get("contexto_comercial") == "proposta enviada", "contexto_comercial deve ser salvo")
            check("email" in mem.get("canais_tentados", []), "canal email deve estar na lista")
        finally:
            _restore(orig)
    print("OK: atualizar_e_obter_memoria_conta")


def test_memoria_conta_ausente_retorna_none():
    orig = mem_mod._ARQ_MEMORIA
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            mem = obter_memoria_conta("empresa_que_nao_existe")
            check(mem is None, "obter conta ausente deve retornar None")
        finally:
            _restore(orig)
    print("OK: memoria_conta_ausente_retorna_none")


def test_atualizar_e_obter_memoria_agente():
    orig = mem_mod._ARQ_MEMORIA
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            atualizar_memoria_agente("agente_comercial", {
                "resumo_ciclo_anterior": "12 oportunidades, 3 propostas"
            })
            mem = obter_memoria_agente("agente_comercial")
            check(mem is not None, "memoria de agente deve existir apos atualizar")
            check(
                mem.get("resumo_ciclo_anterior") == "12 oportunidades, 3 propostas",
                "resumo_ciclo_anterior deve ser salvo"
            )
        finally:
            _restore(orig)
    print("OK: atualizar_e_obter_memoria_agente")


def test_memoria_agente_ausente_retorna_none():
    orig = mem_mod._ARQ_MEMORIA
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            mem = obter_memoria_agente("agente_que_nao_existe")
            check(mem is None, "obter agente ausente deve retornar None")
        finally:
            _restore(orig)
    print("OK: memoria_agente_ausente_retorna_none")


def test_gerar_contexto_llm_conta():
    orig = mem_mod._ARQ_MEMORIA
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            atualizar_memoria_conta("emp_002", {
                "resumo": "Padaria da Maria",
                "contexto_comercial": "aguardando retorno",
            })
            ctx = gerar_contexto_llm(empresa_id="emp_002")
            check(isinstance(ctx, str), "contexto deve ser string")
            check(len(ctx) > 0, "contexto nao deve ser vazio apos atualizar conta")
            check("Padaria da Maria" in ctx, "contexto deve conter o resumo da conta")
        finally:
            _restore(orig)
    print("OK: gerar_contexto_llm_conta")


def test_gerar_contexto_llm_agente():
    orig = mem_mod._ARQ_MEMORIA
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            atualizar_memoria_agente("agente_prospeccao", {
                "resumo_ciclo_anterior": "15 empresas prospectadas"
            })
            ctx = gerar_contexto_llm(agente="agente_prospeccao")
            check(isinstance(ctx, str), "contexto deve ser string")
            check(len(ctx) > 0, "contexto nao deve ser vazio apos atualizar agente")
        finally:
            _restore(orig)
    print("OK: gerar_contexto_llm_agente")


def test_gerar_contexto_llm_vazio():
    orig = mem_mod._ARQ_MEMORIA
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            ctx = gerar_contexto_llm(empresa_id="nao_existe", agente="agente_desconhecido")
            check(isinstance(ctx, str), "contexto deve ser string mesmo sem dados")
            check(len(ctx) == 0, "contexto deve ser string vazia quando nao ha dados")
        finally:
            _restore(orig)
    print("OK: gerar_contexto_llm_vazio")


def test_listar_contas_com_memoria():
    orig = mem_mod._ARQ_MEMORIA
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            atualizar_memoria_conta("emp_A", {"resumo": "Empresa A"})
            atualizar_memoria_conta("emp_B", {"resumo": "Empresa B"})
            contas = listar_contas_com_memoria()
            check(len(contas) == 2, f"deve ter 2 contas na memoria (got {len(contas)})")
            check("emp_A" in contas, "emp_A deve estar na lista")
            check("emp_B" in contas, "emp_B deve estar na lista")
        finally:
            _restore(orig)
    print("OK: listar_contas_com_memoria")


def test_listar_agentes_com_memoria():
    orig = mem_mod._ARQ_MEMORIA
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            atualizar_memoria_agente("agente_x", {"resumo_ciclo_anterior": "ciclo X"})
            atualizar_memoria_agente("agente_y", {"resumo_ciclo_anterior": "ciclo Y"})
            agentes = listar_agentes_com_memoria()
            check(len(agentes) == 2, f"deve ter 2 agentes na memoria (got {len(agentes)})")
        finally:
            _restore(orig)
    print("OK: listar_agentes_com_memoria")


def test_resumo_longo_e_compactado():
    orig = mem_mod._ARQ_MEMORIA
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            resumo_longo = "X" * 600  # acima do limite de 500 chars
            atualizar_memoria_conta("emp_long", {"resumo": resumo_longo})
            mem = obter_memoria_conta("emp_long")
            check(mem is not None, "memoria deve ser criada")
            stored_resumo = mem.get("resumo", "")
            check(len(stored_resumo) <= 500, f"resumo armazenado deve ter <= 500 chars (got {len(stored_resumo)})")
        finally:
            _restore(orig)
    print("OK: resumo_longo_e_compactado")


if __name__ == "__main__":
    testes = [
        test_atualizar_e_obter_memoria_conta,
        test_memoria_conta_ausente_retorna_none,
        test_atualizar_e_obter_memoria_agente,
        test_memoria_agente_ausente_retorna_none,
        test_gerar_contexto_llm_conta,
        test_gerar_contexto_llm_agente,
        test_gerar_contexto_llm_vazio,
        test_listar_contas_com_memoria,
        test_listar_agentes_com_memoria,
        test_resumo_longo_e_compactado,
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
