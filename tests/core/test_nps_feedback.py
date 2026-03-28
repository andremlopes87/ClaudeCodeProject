"""
tests/core/test_nps_feedback.py -- NPS e feedback de clientes

Roda com: python tests/core/test_nps_feedback.py
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
import core.nps_feedback as mod
from core.nps_feedback import (
    programar_nps,
    verificar_nps_devidos,
    registrar_resposta_nps,
    calcular_nps_empresa,
)
import core.llm_log as llm_log_mod


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _patch(tmpdir: str):
    mod._ARQ_PENDENTES = Path(tmpdir) / "nps_pendentes.json"
    mod._ARQ_RESPOSTAS = Path(tmpdir) / "nps_respostas.json"
    mod._ARQ_HISTORICO = Path(tmpdir) / "historico_nps.json"
    mod._ARQ_CONTAS = Path(tmpdir) / "contas_clientes.json"
    mod._ARQ_CONTATOS = Path(tmpdir) / "contatos_contas.json"
    mod._ARQ_ENTREGA = Path(tmpdir) / "pipeline_entrega.json"
    mod._ARQ_ACOES_CS = Path(tmpdir) / "acoes_customer_success.json"
    mod._ARQ_EXPANSAO = Path(tmpdir) / "oportunidades_expansao.json"
    mod._ARQ_ACOMPS = Path(tmpdir) / "acompanhamentos_contas.json"
    llm_log_mod._ARQ_LOG = Path(tmpdir) / "log_llm.json"
    llm_log_mod._ARQ_INCIDENTES = Path(tmpdir) / "log_llm_incidentes.json"


def _restore(orig_p, orig_r, orig_h, orig_c, orig_ct, orig_e, orig_a, orig_x, orig_ac, orig_ll, orig_li):
    mod._ARQ_PENDENTES = orig_p
    mod._ARQ_RESPOSTAS = orig_r
    mod._ARQ_HISTORICO = orig_h
    mod._ARQ_CONTAS = orig_c
    mod._ARQ_CONTATOS = orig_ct
    mod._ARQ_ENTREGA = orig_e
    mod._ARQ_ACOES_CS = orig_a
    mod._ARQ_EXPANSAO = orig_x
    mod._ARQ_ACOMPS = orig_ac
    llm_log_mod._ARQ_LOG = orig_ll
    llm_log_mod._ARQ_INCIDENTES = orig_li


def _get_originals():
    return (
        mod._ARQ_PENDENTES, mod._ARQ_RESPOSTAS, mod._ARQ_HISTORICO,
        mod._ARQ_CONTAS, mod._ARQ_CONTATOS, mod._ARQ_ENTREGA,
        mod._ARQ_ACOES_CS, mod._ARQ_EXPANSAO, mod._ARQ_ACOMPS,
        llm_log_mod._ARQ_LOG, llm_log_mod._ARQ_INCIDENTES,
    )


def test_programar_nps_retorna_dict():
    originals = _get_originals()
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            resultado = programar_nps("conta_001", "pos_entrega")
            check(resultado is not None, "programar_nps deve retornar dict (nao None) na primeira chamada")
            check(isinstance(resultado, dict), "deve retornar dict")
            check("nps_id" in resultado, "resultado deve ter campo 'nps_id'")
        finally:
            _restore(*originals)
    print("OK: programar_nps_retorna_dict")


def test_programar_nps_cria_pendente():
    originals = _get_originals()
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            resultado = programar_nps("conta_002", "pos_entrega")
            check(resultado is not None, "deve criar NPS pendente")
            pendentes_raw = Path(tmpdir) / "nps_pendentes.json"
            check(pendentes_raw.exists(), "arquivo nps_pendentes.json deve existir")
            pendentes = json.loads(pendentes_raw.read_text(encoding="utf-8"))
            check(len(pendentes) == 1, f"deve ter 1 pendente (got {len(pendentes)})")
            check(pendentes[0]["conta_id"] == "conta_002", "conta_id deve corresponder")
        finally:
            _restore(*originals)
    print("OK: programar_nps_cria_pendente")


def test_programar_nps_sem_duplicar():
    originals = _get_originals()
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            programar_nps("conta_003", "primeiro_mes")
            resultado2 = programar_nps("conta_003", "primeiro_mes")
            check(resultado2 is None, "segunda programacao do mesmo gatilho deve retornar None (dedup)")
            pendentes_raw = Path(tmpdir) / "nps_pendentes.json"
            pendentes = json.loads(pendentes_raw.read_text(encoding="utf-8"))
            count = sum(1 for p in pendentes if p["conta_id"] == "conta_003")
            check(count == 1, f"deve ter apenas 1 pendente para conta_003 (got {count})")
        finally:
            _restore(*originals)
    print("OK: programar_nps_sem_duplicar")


def test_registrar_resposta_promotor():
    originals = _get_originals()
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            nps = programar_nps("conta_004", "pos_entrega")
            nps_id = nps["nps_id"]
            resposta = registrar_resposta_nps(nps_id, 10, "Excelente servico")
            check(isinstance(resposta, dict), "deve retornar dict")
            check(resposta.get("tipo_respondente") == "promotor", f"score=10 deve ser promotor (got {resposta.get('tipo_respondente')})")
        finally:
            _restore(*originals)
    print("OK: registrar_resposta_promotor")


def test_registrar_resposta_detrator():
    originals = _get_originals()
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            nps = programar_nps("conta_005", "pos_entrega")
            nps_id = nps["nps_id"]
            resposta = registrar_resposta_nps(nps_id, 5, "Nao gostei")
            check(resposta.get("tipo_respondente") == "detrator", f"score=5 deve ser detrator (got {resposta.get('tipo_respondente')})")
        finally:
            _restore(*originals)
    print("OK: registrar_resposta_detrator")


def test_registrar_resposta_neutro():
    originals = _get_originals()
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            nps = programar_nps("conta_006", "pos_entrega")
            nps_id = nps["nps_id"]
            resposta = registrar_resposta_nps(nps_id, 7)
            check(resposta.get("tipo_respondente") == "neutro", f"score=7 deve ser neutro (got {resposta.get('tipo_respondente')})")
        finally:
            _restore(*originals)
    print("OK: registrar_resposta_neutro")


def test_calcular_nps_sem_respostas():
    originals = _get_originals()
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            resultado = calcular_nps_empresa()
            check(isinstance(resultado, dict), "deve retornar dict")
            check(resultado.get("total") == 0, f"total deve ser 0 sem respostas (got {resultado.get('total')})")
        finally:
            _restore(*originals)
    print("OK: calcular_nps_sem_respostas")


def test_calcular_nps_com_promotores():
    originals = _get_originals()
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch(tmpdir)
        try:
            # Programar e responder 2 NPS como promotores (score 10)
            nps1 = programar_nps("conta_007", "pos_entrega")
            resposta1 = registrar_resposta_nps(nps1["nps_id"], 10)

            # Segundo NPS para outra conta (janela minima nao impede conta diferente)
            nps2 = programar_nps("conta_008", "pos_entrega")
            resposta2 = registrar_resposta_nps(nps2["nps_id"], 10)

            resultado = calcular_nps_empresa()
            check(resultado.get("total") >= 2, f"total deve ser >= 2 (got {resultado.get('total')})")
            check(resultado.get("promotores") >= 2, f"promotores deve ser >= 2 (got {resultado.get('promotores')})")
            # NPS puro com apenas promotores deve ser positivo (100.0)
            check(resultado.get("score_nps") is not None, "score_nps deve existir com respostas")
        finally:
            _restore(*originals)
    print("OK: calcular_nps_com_promotores")


if __name__ == "__main__":
    testes = [
        test_programar_nps_retorna_dict,
        test_programar_nps_cria_pendente,
        test_programar_nps_sem_duplicar,
        test_registrar_resposta_promotor,
        test_registrar_resposta_detrator,
        test_registrar_resposta_neutro,
        test_calcular_nps_sem_respostas,
        test_calcular_nps_com_promotores,
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
