"""
tests/core/test_contatos_contas.py -- Contatos associados a contas

Roda com: python tests/core/test_contatos_contas.py
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
import core.contatos_contas as mod
from core.contatos_contas import (
    criar_contato,
    obter_contatos_conta,
    obter_contatos_ativos_conta,
    obter_contato,
    atualizar_contato,
    desativar_contato,
    obter_contato_principal,
    importar_de_enriquecimento,
)


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _patch(tmpdir: str):
    mod._ARQ_CONTATOS = Path(tmpdir) / "contatos_contas.json"
    mod._ARQ_HISTORICO = Path(tmpdir) / "historico_contatos_contas.json"


def _restore(orig_c, orig_h):
    mod._ARQ_CONTATOS = orig_c
    mod._ARQ_HISTORICO = orig_h


def test_criar_contato_basico():
    orig_c, orig_h = mod._ARQ_CONTATOS, mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            c = criar_contato("conta_001", {
                "nome": "Joao Silva",
                "email": "joao@barbearia.com",
                "cargo": "dono",
            })
            check(isinstance(c, dict), "deve retornar dict")
            check(c.get("nome") == "Joao Silva", "nome deve ser salvo")
        finally:
            _restore(orig_c, orig_h)
    print("OK: criar_contato_basico")


def test_criar_contato_tem_id():
    orig_c, orig_h = mod._ARQ_CONTATOS, mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            c = criar_contato("conta_001", {
                "nome": "Maria Santos",
                "email": "maria@salao.com",
            })
            check("contato_id" in c, "deve ter campo contato_id")
            check(c["contato_id"].startswith("cont_"), "contato_id deve comecar com 'cont_'")
        finally:
            _restore(orig_c, orig_h)
    print("OK: criar_contato_tem_id")


def test_obter_contatos_conta():
    orig_c, orig_h = mod._ARQ_CONTATOS, mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            criar_contato("conta_002", {"nome": "Contato Um", "email": "um@emp.com"})
            criar_contato("conta_002", {"nome": "Contato Dois", "email": "dois@emp.com"})
            contatos = obter_contatos_conta("conta_002")
            check(len(contatos) == 2, f"deve ter 2 contatos (got {len(contatos)})")
        finally:
            _restore(orig_c, orig_h)
    print("OK: obter_contatos_conta")


def test_obter_contato_por_id():
    orig_c, orig_h = mod._ARQ_CONTATOS, mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            c = criar_contato("conta_003", {"nome": "Pedro Alves", "email": "pedro@emp.com"})
            cid = c["contato_id"]
            encontrado = obter_contato(cid)
            check(encontrado is not None, "deve encontrar contato pelo id")
            check(encontrado.get("nome") == "Pedro Alves", "nome deve corresponder")
        finally:
            _restore(orig_c, orig_h)
    print("OK: obter_contato_por_id")


def test_atualizar_contato():
    orig_c, orig_h = mod._ARQ_CONTATOS, mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            c = criar_contato("conta_004", {"nome": "Ana Lima", "email": "ana@emp.com"})
            cid = c["contato_id"]
            atualizado = atualizar_contato(cid, {"cargo": "gerente"})
            check(atualizado is not None, "deve retornar contato atualizado")
            check(atualizado.get("cargo") == "gerente", "cargo deve ser atualizado")
        finally:
            _restore(orig_c, orig_h)
    print("OK: atualizar_contato")


def test_desativar_contato():
    orig_c, orig_h = mod._ARQ_CONTATOS, mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            c = criar_contato("conta_005", {"nome": "Carlos Ramos", "email": "carlos@emp.com"})
            cid = c["contato_id"]
            resultado = desativar_contato(cid)
            check(resultado is True, "desativar deve retornar True")
            ativos = obter_contatos_ativos_conta("conta_005")
            check(len(ativos) == 0, "nao deve ter contatos ativos apos desativar")
        finally:
            _restore(orig_c, orig_h)
    print("OK: desativar_contato")


def test_obter_contato_principal_alta_confianca():
    orig_c, orig_h = mod._ARQ_CONTATOS, mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            criar_contato("conta_006", {
                "nome": "Contato Baixo",
                "email": "baixo@emp.com",
                "confianca": "baixa",
            })
            criar_contato("conta_006", {
                "nome": "Contato Alto",
                "email": "alto@emp.com",
                "confianca": "alta",
            })
            principal = obter_contato_principal("conta_006")
            check(principal is not None, "deve retornar contato principal")
            check(principal.get("confianca") == "alta", "principal deve ser o de confianca alta")
        finally:
            _restore(orig_c, orig_h)
    print("OK: obter_contato_principal_alta_confianca")


def test_obter_contato_principal_sem_contatos():
    orig_c, orig_h = mod._ARQ_CONTATOS, mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            principal = obter_contato_principal("conta_sem_contatos")
            check(principal is None, "deve retornar None quando nao ha contatos")
        finally:
            _restore(orig_c, orig_h)
    print("OK: obter_contato_principal_sem_contatos")


def test_deduplicacao_mesmo_email():
    orig_c, orig_h = mod._ARQ_CONTATOS, mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            criar_contato("conta_007", {"nome": "Fulano", "email": "fulano@emp.com"})
            criar_contato("conta_007", {"nome": "Fulano Atualizado", "email": "fulano@emp.com"})
            contatos = obter_contatos_conta("conta_007")
            check(len(contatos) == 1, f"deduplicacao: deve ter apenas 1 contato (got {len(contatos)})")
            check(contatos[0].get("nome") == "Fulano Atualizado", "nome deve ser atualizado")
        finally:
            _restore(orig_c, orig_h)
    print("OK: deduplicacao_mesmo_email")


def test_importar_de_enriquecimento():
    orig_c, orig_h = mod._ARQ_CONTATOS, mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            empresa = {
                "conta_id": "conta_008",
                "nome": "Oficina Velha",
                "email": "oficina@email.com",
                "telefone": "(11) 98765-4321",
            }
            criados = importar_de_enriquecimento(empresa)
            check(isinstance(criados, list), "deve retornar lista")
            check(len(criados) >= 1, "deve criar ao menos 1 contato de enriquecimento")
        finally:
            _restore(orig_c, orig_h)
    print("OK: importar_de_enriquecimento")


def test_criar_sem_email():
    orig_c, orig_h = mod._ARQ_CONTATOS, mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            c = criar_contato("conta_009", {
                "nome": "Sem Email",
                "telefone": "(11) 99999-0000",
            })
            check(isinstance(c, dict), "deve criar contato mesmo sem email")
            check("contato_id" in c, "deve ter contato_id")
        finally:
            _restore(orig_c, orig_h)
    print("OK: criar_sem_email")


def test_obter_contatos_conta_vazio():
    orig_c, orig_h = mod._ARQ_CONTATOS, mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            contatos = obter_contatos_conta("conta_inexistente")
            check(contatos == [], "deve retornar lista vazia quando conta nao tem contatos")
        finally:
            _restore(orig_c, orig_h)
    print("OK: obter_contatos_conta_vazio")


if __name__ == "__main__":
    testes = [
        test_criar_contato_basico,
        test_criar_contato_tem_id,
        test_obter_contatos_conta,
        test_obter_contato_por_id,
        test_atualizar_contato,
        test_desativar_contato,
        test_obter_contato_principal_alta_confianca,
        test_obter_contato_principal_sem_contatos,
        test_deduplicacao_mesmo_email,
        test_importar_de_enriquecimento,
        test_criar_sem_email,
        test_obter_contatos_conta_vazio,
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
