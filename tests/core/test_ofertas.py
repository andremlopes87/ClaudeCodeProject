"""
tests/core/test_ofertas.py -- Catalogo de ofertas e regras comerciais

Roda com: python tests/core/test_ofertas.py
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
import core.ofertas_empresa as mod
from core.ofertas_empresa import (
    carregar_catalogo,
    sugerir_oferta,
    detalhar_oferta,
    obter_checklist_por_oferta_e_pacote,
    verificar_gatilho_deliberacao_oferta,
    verificar_criterios_pronto_entrega,
)


def check(cond: bool, msg: str):
    status = "OK" if cond else "FALHOU"
    print(f"  [{status}] {msg}")
    if not cond:
        raise AssertionError(msg)


def _patch_historico(tmpdir: str):
    mod._ARQ_HISTORICO = Path(tmpdir) / "historico_ofertas_empresa.json"


def _restore_historico(orig):
    mod._ARQ_HISTORICO = orig


def test_carregar_catalogo_tem_ofertas():
    orig_h = mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_historico(tmpdir)
        # Usar catalogo real ou defaults embutidos
        orig_cat = mod._ARQ_CATALOGO
        mod._ARQ_CATALOGO = config.PASTA_DADOS / "catalogo_ofertas.json"
        try:
            catalogo = carregar_catalogo()
            check(isinstance(catalogo, dict), "catalogo deve ser dict")
            check("ofertas" in catalogo, "catalogo deve ter chave 'ofertas'")
            check(len(catalogo.get("ofertas", [])) > 0, "catalogo deve ter pelo menos 1 oferta")
        finally:
            mod._ARQ_CATALOGO = orig_cat
            _restore_historico(orig_h)
    print("OK: carregar_catalogo_tem_ofertas")


def test_carregar_catalogo_tem_4_ofertas():
    orig_h = mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_historico(tmpdir)
        orig_cat = mod._ARQ_CATALOGO
        mod._ARQ_CATALOGO = config.PASTA_DADOS / "catalogo_ofertas.json"
        try:
            catalogo = carregar_catalogo()
            n = len(catalogo.get("ofertas", []))
            check(n == 4, f"catalogo deve ter 4 ofertas (got {n})")
        finally:
            mod._ARQ_CATALOGO = orig_cat
            _restore_historico(orig_h)
    print("OK: carregar_catalogo_tem_4_ofertas")


def test_sugerir_oferta_sem_presenca():
    orig_h = mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_historico(tmpdir)
        orig_cat = mod._ARQ_CATALOGO
        mod._ARQ_CATALOGO = config.PASTA_DADOS / "catalogo_ofertas.json"
        try:
            empresa = {
                "categoria_id": "oficina_mecanica",
                "sinais": {
                    "tem_website": False,
                    "tem_google_business": False,
                    "tem_whatsapp": False,
                },
                "score_presenca_digital": 0,
            }
            sugestao = sugerir_oferta(empresa)
            check(isinstance(sugestao, dict), "sugestao deve ser dict")
            check("oferta_id" in sugestao, "sugestao deve ter campo 'oferta_id'")
            check(
                sugestao.get("oferta_id") in (
                    "presenca_digital_basica", "atendimento_whatsapp", "agendamento_digital"
                ),
                f"oferta sugerida deve ser relevante (got {sugestao.get('oferta_id')})"
            )
        finally:
            mod._ARQ_CATALOGO = orig_cat
            _restore_historico(orig_h)
    print("OK: sugerir_oferta_sem_presenca")


def test_detalhar_oferta_existente():
    orig_h = mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_historico(tmpdir)
        orig_cat = mod._ARQ_CATALOGO
        mod._ARQ_CATALOGO = config.PASTA_DADOS / "catalogo_ofertas.json"
        try:
            oferta = detalhar_oferta("agendamento_digital")
            check(isinstance(oferta, dict), "detalhar oferta existente deve retornar dict")
            check(oferta.get("id") == "agendamento_digital", "id da oferta deve corresponder")
        finally:
            mod._ARQ_CATALOGO = orig_cat
            _restore_historico(orig_h)
    print("OK: detalhar_oferta_existente")


def test_detalhar_oferta_inexistente():
    orig_h = mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_historico(tmpdir)
        orig_cat = mod._ARQ_CATALOGO
        mod._ARQ_CATALOGO = config.PASTA_DADOS / "catalogo_ofertas.json"
        try:
            oferta = detalhar_oferta("oferta_que_nao_existe")
            check(isinstance(oferta, dict), "oferta inexistente deve retornar dict (vazio ou com erro)")
            check(oferta.get("id") is None or len(oferta) == 0 or "erro" in oferta,
                  "oferta inexistente deve retornar dict vazio ou com campo erro")
        finally:
            mod._ARQ_CATALOGO = orig_cat
            _restore_historico(orig_h)
    print("OK: detalhar_oferta_inexistente")


def test_obter_checklist():
    orig_h = mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_historico(tmpdir)
        orig_cat = mod._ARQ_CATALOGO
        mod._ARQ_CATALOGO = config.PASTA_DADOS / "catalogo_ofertas.json"
        try:
            checklist = obter_checklist_por_oferta_e_pacote("agendamento_digital")
            check(isinstance(checklist, list), "checklist deve ser lista")
        finally:
            mod._ARQ_CATALOGO = orig_cat
            _restore_historico(orig_h)
    print("OK: obter_checklist")


def test_verificar_gatilho_sem_oferta_id():
    orig_h = mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_historico(tmpdir)
        try:
            opp = {"conta_id": "c_001", "status": "prospectando"}
            resultado = verificar_gatilho_deliberacao_oferta(opp)
            check(isinstance(resultado, tuple), "deve retornar tuple")
            check(len(resultado) == 2, "tuple deve ter 2 elementos")
            check(isinstance(resultado[0], bool), "primeiro elemento deve ser bool")
            check(isinstance(resultado[1], str), "segundo elemento deve ser str")
        finally:
            _restore_historico(orig_h)
    print("OK: verificar_gatilho_sem_oferta_id")


def test_verificar_criterios_pronto_entrega():
    orig_h = mod._ARQ_HISTORICO
    with tempfile.TemporaryDirectory() as tmpdir:
        _patch_historico(tmpdir)
        try:
            opp = {
                "oferta_id": "agendamento_digital",
                "conta_id": "c_002",
                "status": "ganho",
                "contrato_id": "cont_001",
            }
            resultado = verificar_criterios_pronto_entrega(opp)
            check(isinstance(resultado, tuple), "deve retornar tuple")
            check(len(resultado) == 2, "tuple deve ter 2 elementos")
            check(isinstance(resultado[0], bool), "primeiro elemento deve ser bool")
            check(isinstance(resultado[1], list), "segundo elemento deve ser lista")
        finally:
            _restore_historico(orig_h)
    print("OK: verificar_criterios_pronto_entrega")


if __name__ == "__main__":
    testes = [
        test_carregar_catalogo_tem_ofertas,
        test_carregar_catalogo_tem_4_ofertas,
        test_sugerir_oferta_sem_presenca,
        test_detalhar_oferta_existente,
        test_detalhar_oferta_inexistente,
        test_obter_checklist,
        test_verificar_gatilho_sem_oferta_id,
        test_verificar_criterios_pronto_entrega,
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
