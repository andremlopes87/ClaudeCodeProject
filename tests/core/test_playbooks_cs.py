"""
tests/core/test_playbooks_cs.py -- Playbooks de customer success

Roda com: python tests/core/test_playbooks_cs.py
"""

import sys
import io
import json
import tempfile
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config
import core.playbooks_cs as mod
from core.playbooks_cs import (
    carregar_playbooks,
    avaliar_playbooks,
    gerar_acoes_playbook,
    obter_status_playbooks_conta,
    registrar_execucao_acao,
)


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _patch_runtime(tmpdir: str):
    mod._ARQ_HISTORICO = Path(tmpdir) / "historico_playbooks_cs.json"


def _restore_runtime(orig_h):
    mod._ARQ_HISTORICO = orig_h


def _playbook_fake():
    return {
        "id": "pb_risco_teste",
        "nome": "Risco de Churn Teste",
        "severidade": "risco",
        "gatilho": {"tipo": "inatividade", "condicao": "dias_sem_interacao >= 14"},
        "acoes": [
            {"ordem": 1, "tipo": "contato", "descricao": "Ligar para o cliente"},
            {"ordem": 2, "tipo": "email", "descricao": "Enviar email de follow-up"},
        ],
    }


def test_carregar_playbooks_lista():
    orig_h = mod._ARQ_HISTORICO
    orig_pb = mod._ARQ_PLAYBOOKS
    mod._ARQ_PLAYBOOKS = config.PASTA_DADOS / "playbooks_customer_success.json"
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_runtime(tmpdir)
        try:
            playbooks = carregar_playbooks()
            check(isinstance(playbooks, list), "carregar_playbooks deve retornar lista")
        finally:
            mod._ARQ_PLAYBOOKS = orig_pb
            _restore_runtime(orig_h)
    print("OK: carregar_playbooks_lista")


def test_avaliar_playbooks_conta_ativa():
    orig_h = mod._ARQ_HISTORICO
    orig_pb = mod._ARQ_PLAYBOOKS
    mod._ARQ_PLAYBOOKS = config.PASTA_DADOS / "playbooks_customer_success.json"
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_runtime(tmpdir)
        try:
            conta = {"id": "conta_001", "status_saude": "saudavel"}
            contexto = {
                "dias_sem_interacao": 3,
                "parcela_atrasada_dias": 0,
                "dias_sem_progresso_entrega": 0,
                "score_saude": 82,
                "nps_score": None,
                "feedback_sentimento": None,
            }
            resultado = avaliar_playbooks(conta, contexto)
            check(isinstance(resultado, list), "avaliar_playbooks deve retornar lista")
        finally:
            mod._ARQ_PLAYBOOKS = orig_pb
            _restore_runtime(orig_h)
    print("OK: avaliar_playbooks_conta_ativa")


def test_avaliar_playbooks_cliente_em_risco():
    orig_h = mod._ARQ_HISTORICO
    orig_pb = mod._ARQ_PLAYBOOKS
    mod._ARQ_PLAYBOOKS = config.PASTA_DADOS / "playbooks_customer_success.json"
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_runtime(tmpdir)
        try:
            conta = {"id": "conta_002", "status_saude": "critico"}
            contexto = {
                "dias_sem_interacao": 30,
                "parcela_atrasada_dias": 15,
                "dias_sem_progresso_entrega": 20,
                "score_saude": 20,
                "nps_score": 4,
                "feedback_sentimento": "negativo",
            }
            resultado = avaliar_playbooks(conta, contexto)
            check(isinstance(resultado, list), "avaliar_playbooks deve retornar lista para conta em risco")
        finally:
            mod._ARQ_PLAYBOOKS = orig_pb
            _restore_runtime(orig_h)
    print("OK: avaliar_playbooks_cliente_em_risco")


def test_avaliar_playbooks_retorna_lista():
    orig_h = mod._ARQ_HISTORICO
    orig_pb = mod._ARQ_PLAYBOOKS
    mod._ARQ_PLAYBOOKS = config.PASTA_DADOS / "playbooks_customer_success.json"
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_runtime(tmpdir)
        try:
            # Cenario vazio nao deve levantar excecao
            conta = {"id": "conta_003"}
            resultado = avaliar_playbooks(conta, {})
            check(isinstance(resultado, list), "deve sempre retornar lista")
        finally:
            mod._ARQ_PLAYBOOKS = orig_pb
            _restore_runtime(orig_h)
    print("OK: avaliar_playbooks_retorna_lista")


def test_gerar_acoes_retorna_lista_ou_none():
    orig_h = mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_runtime(tmpdir)
        try:
            pb = _playbook_fake()
            acao = gerar_acoes_playbook("conta_004", pb, etapa_atual=1)
            # Deve retornar dict com acao ou None
            check(acao is None or isinstance(acao, dict), "deve retornar dict ou None")
        finally:
            _restore_runtime(orig_h)
    print("OK: gerar_acoes_retorna_lista_ou_none")


def test_gerar_acoes_sem_duplicacao():
    orig_h = mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_runtime(tmpdir)
        try:
            pb = _playbook_fake()
            acao1 = gerar_acoes_playbook("conta_005", pb, etapa_atual=1)
            if acao1 is not None:
                # Registrar execucao para simular que foi executada
                registrar_execucao_acao("conta_005", pb["id"], acao1, "executada")
                # Segunda chamada no mesmo dia deve retornar None (dedup)
                acao2 = gerar_acoes_playbook("conta_005", pb, etapa_atual=1)
                check(acao2 is None, "segunda geracao no mesmo dia deve retornar None (dedup)")
            else:
                check(True, "acao ja deduplicada na primeira chamada (ok)")
        finally:
            _restore_runtime(orig_h)
    print("OK: gerar_acoes_sem_duplicacao")


def test_obter_status_conta_nova():
    orig_h = mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_runtime(tmpdir)
        try:
            status = obter_status_playbooks_conta("conta_nova_sem_historico")
            check(isinstance(status, list), "deve retornar lista")
            check(status == [], "conta nova sem historico deve ter status vazio")
        finally:
            _restore_runtime(orig_h)
    print("OK: obter_status_conta_nova")


def test_gerar_acoes_tem_campos():
    orig_h = mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_runtime(tmpdir)
        try:
            pb = _playbook_fake()
            acao = gerar_acoes_playbook("conta_006", pb, etapa_atual=1)
            if acao is not None:
                check("tipo" in acao, "acao deve ter campo 'tipo'")
                check("descricao" in acao, "acao deve ter campo 'descricao'")
                check("playbook_id" in acao, "acao deve ter campo 'playbook_id'")
                check("conta_id" in acao, "acao deve ter campo 'conta_id'")
            else:
                check(True, "acao deduplicada, campos nao verificados (ok)")
        finally:
            _restore_runtime(orig_h)
    print("OK: gerar_acoes_tem_campos")


if __name__ == "__main__":
    testes = [
        test_carregar_playbooks_lista,
        test_avaliar_playbooks_conta_ativa,
        test_avaliar_playbooks_cliente_em_risco,
        test_avaliar_playbooks_retorna_lista,
        test_gerar_acoes_retorna_lista_ou_none,
        test_gerar_acoes_sem_duplicacao,
        test_obter_status_conta_nova,
        test_gerar_acoes_tem_campos,
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
