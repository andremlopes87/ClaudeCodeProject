"""
tests/core/test_canais.py -- Framework unificado de canais

Roda com: python tests/core/test_canais.py
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
import core.canais as canais_mod
from core.canais import (
    obter_canal,
    canais_ativos,
    melhor_canal_para_contato,
    preparar_envio,
    CanalEmail,
    _CanalDryRunGenerico,
)


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _patch(tmpdir: str):
    canais_mod._ARQUIVO_ESTADO = Path(tmpdir) / "estado_canais.json"
    canais_mod._estado_cache = None


def _restore(orig_arq, orig_cache):
    canais_mod._ARQUIVO_ESTADO = orig_arq
    canais_mod._estado_cache = orig_cache


def test_obter_canal_email():
    orig_arq = canais_mod._ARQUIVO_ESTADO
    orig_cache = canais_mod._estado_cache
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            canal = obter_canal("email")
            check(isinstance(canal, CanalEmail), "obter_canal('email') deve retornar CanalEmail")
            check(canal.nome == "email", "nome do canal deve ser 'email'")
        finally:
            _restore(orig_arq, orig_cache)
    print("OK: obter_canal_email")


def test_obter_canal_whatsapp():
    orig_arq = canais_mod._ARQUIVO_ESTADO
    orig_cache = canais_mod._estado_cache
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            canal = obter_canal("whatsapp")
            check(canal.nome == "whatsapp", "nome do canal deve ser 'whatsapp'")
        finally:
            _restore(orig_arq, orig_cache)
    print("OK: obter_canal_whatsapp")


def test_obter_canal_telefone():
    orig_arq = canais_mod._ARQUIVO_ESTADO
    orig_cache = canais_mod._estado_cache
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            canal = obter_canal("telefone")
            check(canal.nome == "telefone", "nome do canal deve ser 'telefone'")
        finally:
            _restore(orig_arq, orig_cache)
    print("OK: obter_canal_telefone")


def test_obter_canal_desconhecido():
    orig_arq = canais_mod._ARQUIVO_ESTADO
    orig_cache = canais_mod._estado_cache
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            canal = obter_canal("xyz_desconhecido")
            check(isinstance(canal, _CanalDryRunGenerico), "canal desconhecido deve retornar _CanalDryRunGenerico")
            check(canal.modo == "dry-run", "canal desconhecido deve estar em dry-run")
        finally:
            _restore(orig_arq, orig_cache)
    print("OK: obter_canal_desconhecido")


def test_canais_ativos_retorna_lista():
    orig_arq = canais_mod._ARQUIVO_ESTADO
    orig_cache = canais_mod._estado_cache
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            ativos = canais_ativos()
            check(isinstance(ativos, list), "canais_ativos() deve retornar lista")
        finally:
            _restore(orig_arq, orig_cache)
    print("OK: canais_ativos_retorna_lista")


def test_melhor_canal_com_email():
    orig_arq = canais_mod._ARQUIVO_ESTADO
    orig_cache = canais_mod._estado_cache
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            contato = {"email_principal": "x@empresa.com"}
            # canal_preferido nao definido, mas email disponivel na prioridade
            resultado = melhor_canal_para_contato(contato)
            check(isinstance(resultado, str), "melhor_canal deve retornar string")
            check(len(resultado) > 0, "melhor_canal nao deve ser string vazia")
        finally:
            _restore(orig_arq, orig_cache)
    print("OK: melhor_canal_com_email")


def test_preparar_envio_email():
    orig_arq = canais_mod._ARQUIVO_ESTADO
    orig_cache = canais_mod._estado_cache
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        # Forcar dry-run no estado de canais
        import json
        estado_file = Path(tmpdir) / "estado_canais.json"
        estado = {
            "email": {"modo": "dry-run", "configurado": True},
        }
        estado_file.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
        canais_mod._estado_cache = None  # resetar cache apos escrever arquivo
        try:
            payload = {
                "para": "teste@empresa.com",
                "assunto": "Teste",
                "roteiro_base": "Corpo do email de teste",
                "contato_destino": "teste@empresa.com",
            }
            resultado = preparar_envio("email", payload)
            check(isinstance(resultado, dict), "preparar_envio deve retornar dict")
            check("status" in resultado, "resultado deve ter campo 'status'")
        finally:
            _restore(orig_arq, orig_cache)
    print("OK: preparar_envio_email")


def test_preparar_envio_campos():
    orig_arq = canais_mod._ARQUIVO_ESTADO
    orig_cache = canais_mod._estado_cache
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        import json
        estado_file = Path(tmpdir) / "estado_canais.json"
        estado = {
            "email": {"modo": "dry-run", "configurado": True},
        }
        estado_file.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
        canais_mod._estado_cache = None
        try:
            payload = {
                "contato_destino": "contato@emp.com",
                "roteiro_base": "Ola, tudo bem?",
            }
            resultado = preparar_envio("email", payload)
            check("canal" in resultado, "resultado deve ter campo 'canal'")
            check("modo" in resultado, "resultado deve ter campo 'modo'")
            check("status" in resultado, "resultado deve ter campo 'status'")
        finally:
            _restore(orig_arq, orig_cache)
    print("OK: preparar_envio_campos")


if __name__ == "__main__":
    testes = [
        test_obter_canal_email,
        test_obter_canal_whatsapp,
        test_obter_canal_telefone,
        test_obter_canal_desconhecido,
        test_canais_ativos_retorna_lista,
        test_melhor_canal_com_email,
        test_preparar_envio_email,
        test_preparar_envio_campos,
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
