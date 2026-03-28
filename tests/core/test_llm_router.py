"""
tests/core/test_llm_router.py -- LLMRouter dry-run behavior

Roda com: python tests/core/test_llm_router.py
"""

import sys
import io
import os
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
import core.llm_log as llm_log_mod


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _patch_llm_log(tmpdir: str):
    llm_log_mod._ARQ_LOG = Path(tmpdir) / "log_llm.json"
    llm_log_mod._ARQ_INCIDENTES = Path(tmpdir) / "log_llm_incidentes.json"


def _restore_llm_log():
    llm_log_mod._ARQ_LOG = config.PASTA_DADOS / "log_llm.json"
    llm_log_mod._ARQ_INCIDENTES = config.PASTA_DADOS / "log_llm_incidentes.json"


def test_instanciar_dry_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        config.LLM_MODO = "dry-run"
        _patch_llm_log(tmpdir)
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            check(router._modo == "dry-run", "modo deve ser dry-run por padrao")
        finally:
            config.LLM_MODO = orig_modo
            _restore_llm_log()
    print("OK: instanciar_dry_run")


def test_modo_real_sem_api_key_vira_dry_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        orig_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        config.LLM_MODO = "real"
        _patch_llm_log(tmpdir)
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            check(router._modo == "dry-run", "modo real sem api_key deve virar dry-run")
        finally:
            config.LLM_MODO = orig_modo
            if orig_key is not None:
                os.environ["ANTHROPIC_API_KEY"] = orig_key
            _restore_llm_log()
    print("OK: modo_real_sem_api_key_vira_dry_run")


def test_classificar_dry_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        config.LLM_MODO = "dry-run"
        _patch_llm_log(tmpdir)
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            resp = router.classificar({
                "agente": "agente_prospeccao",
                "tarefa": "classificar_empresa",
                "dados": {"nome": "Barbearia Central"},
            })
            check(isinstance(resp, dict), "deve retornar dict")
            check(resp.get("sucesso") is True, "sucesso deve ser True")
            check(resp.get("modo") == "dry-run", "modo deve ser dry-run")
            check(resp.get("custo_estimado_usd") == 0.0, "custo deve ser 0.0")
        finally:
            config.LLM_MODO = orig_modo
            _restore_llm_log()
    print("OK: classificar_dry_run")


def test_redigir_dry_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        config.LLM_MODO = "dry-run"
        _patch_llm_log(tmpdir)
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            resp = router.redigir({
                "agente": "agente_marketing",
                "tarefa": "redigir_email",
                "dados": {"empresa": "Padaria X"},
            })
            check(resp.get("sucesso") is True, "sucesso deve ser True")
            check(resp.get("modo") == "dry-run", "modo deve ser dry-run")
        finally:
            config.LLM_MODO = orig_modo
            _restore_llm_log()
    print("OK: redigir_dry_run")


def test_decidir_dry_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        config.LLM_MODO = "dry-run"
        _patch_llm_log(tmpdir)
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            resp = router.decidir({
                "agente": "agente_secretario",
                "tarefa": "decidir_escalamento",
                "dados": {"opp_id": "opp_001"},
            })
            check(isinstance(resp.get("resultado"), dict), "resultado deve ser dict")
            check("decisao" in resp.get("resultado", {}), "resultado deve ter chave decisao")
        finally:
            config.LLM_MODO = orig_modo
            _restore_llm_log()
    print("OK: decidir_dry_run")


def test_analisar_dry_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        config.LLM_MODO = "dry-run"
        _patch_llm_log(tmpdir)
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            resp = router.analisar({
                "agente": "agente_financeiro",
                "tarefa": "analisar_risco_caixa",
                "dados": {"saldo": 1200.0},
            })
            check(isinstance(resp.get("resultado"), dict), "resultado deve ser dict")
            check("analise" in resp.get("resultado", {}), "resultado deve ter chave analise")
        finally:
            config.LLM_MODO = orig_modo
            _restore_llm_log()
    print("OK: analisar_dry_run")


def test_resumir_dry_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        config.LLM_MODO = "dry-run"
        _patch_llm_log(tmpdir)
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            resp = router.resumir({
                "agente": "agente_secretario",
                "tarefa": "resumir_ciclo",
                "dados": {"ciclo": 1, "agentes": 5},
            })
            check(isinstance(resp.get("resultado"), dict), "resultado deve ser dict")
            check("resumo" in resp.get("resultado", {}), "resultado deve ter chave resumo")
        finally:
            config.LLM_MODO = orig_modo
            _restore_llm_log()
    print("OK: resumir_dry_run")


def test_custo_zero_dry_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        config.LLM_MODO = "dry-run"
        _patch_llm_log(tmpdir)
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            resp = router.classificar({
                "agente": "agente_prospeccao",
                "tarefa": "classificar_empresa",
                "dados": {"nome": "Oficina Velha"},
            })
            check(resp.get("custo_estimado_usd") == 0.0, "custo_estimado_usd deve ser 0.0 em dry-run")
        finally:
            config.LLM_MODO = orig_modo
            _restore_llm_log()
    print("OK: custo_zero_dry_run")


def test_fallback_false_dry_run():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        config.LLM_MODO = "dry-run"
        _patch_llm_log(tmpdir)
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            resp = router.classificar({
                "agente": "agente_prospeccao",
                "tarefa": "classificar_empresa",
                "dados": {},
            })
            check(resp.get("fallback_usado") is False, "fallback_usado deve ser False em dry-run normal")
        finally:
            config.LLM_MODO = orig_modo
            _restore_llm_log()
    print("OK: fallback_false_dry_run")


def test_redigir_agente_comercial_injeta_guia():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        config.LLM_MODO = "dry-run"
        _patch_llm_log(tmpdir)
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            ctx = {
                "agente": "agente_comercial",
                "tarefa": "redigir_email",
                "dados": {"empresa": "Barbearia Y"},
            }
            resp = router.redigir(ctx)
            check(resp.get("sucesso") is True, "deve retornar sucesso mesmo sem guia_tom no tmpdir")
            check(isinstance(resp, dict), "deve retornar dict")
        finally:
            config.LLM_MODO = orig_modo
            _restore_llm_log()
    print("OK: redigir_agente_comercial_injeta_guia")


def test_empresa_id_carrega_memoria():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        config.LLM_MODO = "dry-run"
        _patch_llm_log(tmpdir)
        orig_pasta = config.PASTA_DADOS
        config.PASTA_DADOS = Path(tmpdir)
        try:
            import json
            import core.llm_memoria as mem_mod
            orig_arq = mem_mod._ARQ_MEMORIA
            mem_mod._ARQ_MEMORIA = Path(tmpdir) / "memoria_agentes.json"
            mem_data = {
                "por_conta": {
                    "empresa_abc": {
                        "resumo": "Barbearia do Joao",
                        "interacoes": 2,
                        "contexto_comercial": "em negociacao",
                        "canais_tentados": ["email"],
                        "notas": [],
                        "ultima_atualizacao": "2026-01-01T10:00:00",
                    }
                },
                "por_agente": {}
            }
            mem_mod._ARQ_MEMORIA.write_text(
                json.dumps(mem_data, ensure_ascii=False), encoding="utf-8"
            )
            from core.llm_router import LLMRouter
            router = LLMRouter()
            resp = router.classificar({
                "agente": "agente_prospeccao",
                "tarefa": "classificar_empresa",
                "dados": {"nome": "Barbearia do Joao"},
            }, empresa_id="empresa_abc")
            check(resp.get("sucesso") is True, "deve retornar sucesso ao carregar memoria")
        finally:
            config.LLM_MODO = orig_modo
            config.PASTA_DADOS = orig_pasta
            _restore_llm_log()
            mem_mod._ARQ_MEMORIA = orig_arq
    print("OK: empresa_id_carrega_memoria")


def test_campos_obrigatorios_resposta():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        config.LLM_MODO = "dry-run"
        _patch_llm_log(tmpdir)
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            resp = router.classificar({
                "agente": "agente_prospeccao",
                "tarefa": "classificar_empresa",
                "dados": {},
            })
            campos = ["sucesso", "resultado", "modelo_usado", "tokens_entrada",
                      "tokens_saida", "custo_estimado_usd", "fallback_usado", "modo", "erro"]
            for campo in campos:
                check(campo in resp, f"campo '{campo}' deve estar na resposta")
        finally:
            config.LLM_MODO = orig_modo
            _restore_llm_log()
    print("OK: campos_obrigatorios_resposta")


def test_contexto_minimo():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        config.LLM_MODO = "dry-run"
        _patch_llm_log(tmpdir)
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            resp = router.classificar({
                "agente": "x",
                "tarefa": "y",
                "dados": {},
            })
            check(resp.get("sucesso") is True, "contexto minimo deve retornar sucesso")
        finally:
            config.LLM_MODO = orig_modo
            _restore_llm_log()
    print("OK: contexto_minimo")


def test_log_escrito():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        config.LLM_MODO = "dry-run"
        _patch_llm_log(tmpdir)
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            router.classificar({
                "agente": "agente_prospeccao",
                "tarefa": "classificar_empresa",
                "dados": {"nome": "Padaria Teste"},
            })
            log_file = Path(tmpdir) / "log_llm.json"
            check(log_file.exists(), "log_llm.json deve ser criado apos chamada")
        finally:
            config.LLM_MODO = orig_modo
            _restore_llm_log()
    print("OK: log_escrito")


def test_metodo_resumir_com_dados():
    with tempfile.TemporaryDirectory() as tmpdir:
        orig_modo = getattr(config, "LLM_MODO", "dry-run")
        config.LLM_MODO = "dry-run"
        _patch_llm_log(tmpdir)
        try:
            from core.llm_router import LLMRouter
            router = LLMRouter()
            resp = router.resumir({
                "agente": "agente_secretario",
                "tarefa": "resumir_ciclo",
                "dados": {
                    "ciclo": 5,
                    "agentes": 11,
                    "propostas": 3,
                    "clientes": 2,
                    "receita": 1200.0,
                },
            })
            check(resp.get("sucesso") is True, "resumir com dados multiplos deve retornar sucesso")
            check(isinstance(resp.get("resultado"), dict), "resultado deve ser dict")
        finally:
            config.LLM_MODO = orig_modo
            _restore_llm_log()
    print("OK: metodo_resumir_com_dados")


if __name__ == "__main__":
    testes = [
        test_instanciar_dry_run,
        test_modo_real_sem_api_key_vira_dry_run,
        test_classificar_dry_run,
        test_redigir_dry_run,
        test_decidir_dry_run,
        test_analisar_dry_run,
        test_resumir_dry_run,
        test_custo_zero_dry_run,
        test_fallback_false_dry_run,
        test_redigir_agente_comercial_injeta_guia,
        test_empresa_id_carrega_memoria,
        test_campos_obrigatorios_resposta,
        test_contexto_minimo,
        test_log_escrito,
        test_metodo_resumir_com_dados,
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
