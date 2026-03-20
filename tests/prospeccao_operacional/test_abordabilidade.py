"""
tests/test_abordabilidade.py — Testa a camada de abordabilidade.

Roda com: python tests/test_abordabilidade.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modulos.prospeccao_operacional.abordabilidade import calcular_abordabilidade


def _empresa(telefone=None, email=None, website=None):
    """Cria empresa de teste com sinais já calculados."""
    return {
        "nome": "Empresa Teste",
        "telefone": telefone,
        "email": email,
        "website": website,
        "sinais": {
            "tem_website": bool(website) and "instagram.com" not in (website or ""),
            "tem_telefone": bool(telefone),
            "tem_horario": False,
            "tem_email": bool(email),
        },
    }


def test_com_telefone_e_abordavel():
    """Empresa com telefone deve ser abordavel_agora = True."""
    e = _empresa(telefone="+55 17 9999-9999")
    resultado = calcular_abordabilidade([e])[0]
    assert resultado["abordavel_agora"] is True
    assert resultado["canal_abordagem_sugerido"] == "telefone"
    assert resultado["contato_principal"] == "+55 17 9999-9999"
    assert resultado["tipo_contato_principal"] == "telefone"
    assert resultado["motivo_nao_abordavel"] is None
    assert resultado["tem_telefone_util"] is True
    print("OK: telefone -> abordavel, canal=telefone")


def test_com_email_e_abordavel():
    """Empresa com e-mail mas sem telefone deve ser abordavel_agora = True."""
    e = _empresa(email="contato@empresa.com")
    resultado = calcular_abordabilidade([e])[0]
    assert resultado["abordavel_agora"] is True
    assert resultado["canal_abordagem_sugerido"] == "email"
    assert resultado["contato_principal"] == "contato@empresa.com"
    assert resultado["tipo_contato_principal"] == "email"
    print("OK: email (sem telefone) -> abordavel, canal=email")


def test_telefone_tem_prioridade_sobre_email():
    """Quando tem ambos, telefone deve ser o canal principal."""
    e = _empresa(telefone="+55 17 9999-9999", email="c@empresa.com")
    resultado = calcular_abordabilidade([e])[0]
    assert resultado["canal_abordagem_sugerido"] == "telefone"
    assert resultado["tipo_contato_principal"] == "telefone"
    print("OK: telefone tem prioridade sobre email")


def test_so_website_nao_e_abordavel():
    """Website sem telefone/email não deve ser considerado abordável imediato."""
    e = _empresa(website="http://empresa.com")
    resultado = calcular_abordabilidade([e])[0]
    assert resultado["abordavel_agora"] is False
    assert resultado["canal_abordagem_sugerido"] == "website_contato_indireto"
    assert resultado["tipo_contato_principal"] == "website"
    assert resultado["motivo_nao_abordavel"] is not None
    assert resultado["tem_site_util"] is True
    print("OK: so website -> nao abordavel, canal=website_contato_indireto")


def test_sem_dados_nao_e_abordavel():
    """Empresa sem nenhum contato deve ser não-abordável."""
    e = _empresa()
    resultado = calcular_abordabilidade([e])[0]
    assert resultado["abordavel_agora"] is False
    assert resultado["canal_abordagem_sugerido"] == "sem_canal_identificado"
    assert resultado["contato_principal"] is None
    assert resultado["tipo_contato_principal"] is None
    assert resultado["motivo_nao_abordavel"] is not None
    assert resultado["tem_telefone_util"] is False
    assert resultado["tem_email_util"] is False
    assert resultado["tem_site_util"] is False
    print("OK: sem dados -> nao abordavel, sem_canal_identificado")


def test_campos_utilidade_corretos():
    """Campos tem_X_util devem refletir os sinais independente de abordabilidade."""
    e = _empresa(telefone="+55 17 9999-9999", website="http://meusite.com")
    resultado = calcular_abordabilidade([e])[0]
    assert resultado["tem_telefone_util"] is True
    assert resultado["tem_site_util"] is True
    assert resultado["tem_email_util"] is False
    print("OK: campos de utilidade calculados corretamente")


def test_multiplas_empresas():
    """Deve processar lista com varias empresas."""
    empresas = [
        _empresa(telefone="+55 17 9999-9999"),
        _empresa(email="a@b.com"),
        _empresa(website="http://site.com"),
        _empresa(),
    ]
    resultados = calcular_abordabilidade(empresas)
    assert resultados[0]["abordavel_agora"] is True
    assert resultados[1]["abordavel_agora"] is True
    assert resultados[2]["abordavel_agora"] is False
    assert resultados[3]["abordavel_agora"] is False
    print("OK: multiplas empresas processadas corretamente")


if __name__ == "__main__":
    test_com_telefone_e_abordavel()
    test_com_email_e_abordavel()
    test_telefone_tem_prioridade_sobre_email()
    test_so_website_nao_e_abordavel()
    test_sem_dados_nao_e_abordavel()
    test_campos_utilidade_corretos()
    test_multiplas_empresas()
    print("\nTodos os testes de abordabilidade passaram.")
