"""
tests/presenca_digital/test_diagnosticador_presenca.py — Testa score, classificação e diagnóstico.

Roda com: python tests/presenca_digital/test_diagnosticador_presenca.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modulos.presenca_digital.diagnosticador_presenca import (
    diagnosticar_presenca,
    _calcular_score,
    _classificar,
    _oportunidade_marketing,
    _confianca,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empresa(
    tem_site=True,
    site_acessivel=True,
    status_http=200,
    usa_https=True,
    telefone=False,
    email=False,
    whatsapp=False,
    instagram=False,
    facebook=False,
    cta=False,
    website="https://exemplo.com.br",
):
    return {
        "nome": "Empresa Teste",
        "website": website,
        "tem_site": tem_site,
        "site_acessivel": site_acessivel,
        "status_http_site": status_http,
        "usa_https": usa_https,
        "tem_telefone_no_site": telefone,
        "tem_email_no_site": email,
        "tem_whatsapp_no_site": whatsapp,
        "tem_instagram_no_site": instagram,
        "tem_facebook_no_site": facebook,
        "tem_cta_clara": cta,
        "sinais": {"tem_website": tem_site},
    }


# ---------------------------------------------------------------------------
# Testes de score
# ---------------------------------------------------------------------------

def test_score_zero_sem_sinais():
    e = _empresa(site_acessivel=False, usa_https=False)
    assert _calcular_score(e) == 0
    print("OK: score 0 sem sinais")


def test_score_so_acessivel():
    e = _empresa(usa_https=False)
    assert _calcular_score(e) == 20  # apenas site_acessivel
    print("OK: score 20 só com site acessível")


def test_score_maximo():
    e = _empresa(
        usa_https=True, telefone=True, email=True,
        whatsapp=True, instagram=True, facebook=True, cta=True
    )
    assert _calcular_score(e) == 100
    print("OK: score 100 com todos os sinais")


def test_score_com_whatsapp_e_telefone():
    # site_acessivel=20, usa_https=10, telefone=20, whatsapp=15 = 65
    e = _empresa(usa_https=True, telefone=True, whatsapp=True)
    assert _calcular_score(e) == 65
    print("OK: score 65 com acessível + HTTPS + telefone + WhatsApp")


# ---------------------------------------------------------------------------
# Testes de classificação
# ---------------------------------------------------------------------------

def test_classificacao_dados_insuficientes_inacessivel():
    assert _classificar(0, False) == "dados_insuficientes"
    print("OK: dados_insuficientes quando inacessível")


def test_classificacao_presenca_fraca():
    assert _classificar(20, True) == "presenca_fraca"  # só site acessível
    assert _classificar(35, True) == "presenca_fraca"
    print("OK: presenca_fraca para score 20-35")


def test_classificacao_presenca_basica():
    assert _classificar(36, True) == "presenca_basica"
    assert _classificar(55, True) == "presenca_basica"
    print("OK: presenca_basica para score 36-55")


def test_classificacao_presenca_razoavel():
    assert _classificar(56, True) == "presenca_razoavel"
    assert _classificar(75, True) == "presenca_razoavel"
    print("OK: presenca_razoavel para score 56-75")


def test_classificacao_presenca_boa():
    assert _classificar(76, True) == "presenca_boa"
    assert _classificar(100, True) == "presenca_boa"
    print("OK: presenca_boa para score >= 76")


# ---------------------------------------------------------------------------
# Testes de oportunidade de marketing
# ---------------------------------------------------------------------------

def test_oportunidade_site_inacessivel():
    e = _empresa(site_acessivel=False)
    oport = _oportunidade_marketing(e)
    assert "disponibilidade" in oport.lower() or "não respondeu" in oport.lower()
    print("OK: oportunidade aponta problema de acessibilidade")


def test_oportunidade_sem_whatsapp_e_mais_urgente():
    """WhatsApp ausente deve ser a primeira oportunidade quando site está acessível."""
    e = _empresa(usa_https=True, telefone=True, email=True, instagram=True, cta=True)
    oport = _oportunidade_marketing(e)
    assert "whatsapp" in oport.lower()
    print("OK: WhatsApp ausente é oportunidade principal")


def test_oportunidade_sem_cta():
    e = _empresa(usa_https=True, telefone=True, whatsapp=True, email=True)
    oport = _oportunidade_marketing(e)
    assert "ação" in oport.lower() or "cta" in oport.lower() or "agendar" in oport.lower() or "orçamento" in oport.lower()
    print("OK: CTA ausente identificado como oportunidade")


def test_oportunidade_site_completo():
    e = _empresa(
        usa_https=True, telefone=True, email=True,
        whatsapp=True, instagram=True, facebook=True, cta=True
    )
    oport = _oportunidade_marketing(e)
    assert "seo" in oport.lower() or "bem estruturado" in oport.lower()
    print("OK: site completo — oportunidade de SEO")


# ---------------------------------------------------------------------------
# Testes de confiança
# ---------------------------------------------------------------------------

def test_confianca_sem_dados():
    e = _empresa(tem_site=False, site_acessivel=False)
    assert _confianca(e) == "sem_dados"
    print("OK: sem_dados quando empresa não tem site")


def test_confianca_alta_site_acessivel():
    e = _empresa()
    assert _confianca(e) == "alta"
    print("OK: alta confiança quando site acessível")


def test_confianca_baixa_inacessivel():
    e = _empresa(site_acessivel=False)
    # tem_site=True mas inacessível
    assert _confianca(e) == "baixa"
    print("OK: baixa confiança quando site inacessível")


# ---------------------------------------------------------------------------
# Testes do pipeline completo
# ---------------------------------------------------------------------------

def test_diagnosticar_presenca_adiciona_campos():
    empresas = [_empresa(telefone=True, whatsapp=True)]
    resultado = diagnosticar_presenca(empresas)
    e = resultado[0]
    assert "score_presenca_web" in e
    assert "classificacao_presenca_web" in e
    assert "diagnostico_presenca_digital" in e
    assert "oportunidade_marketing_principal" in e
    assert "confianca_diagnostico_presenca" in e
    assert "observacao_limite_dados_presenca" in e
    print("OK: todos os campos de diagnóstico adicionados")


def test_diagnosticar_lista_vazia():
    resultado = diagnosticar_presenca([])
    assert resultado == []
    print("OK: lista vazia retorna lista vazia")


def test_diagnostico_menciona_nome():
    empresas = [_empresa()]
    resultado = diagnosticar_presenca(empresas)
    diagnostico = resultado[0]["diagnostico_presenca_digital"]
    assert "Empresa Teste" in diagnostico
    print("OK: diagnóstico menciona nome da empresa")


def test_score_e_classificacao_consistentes():
    """Score alto deve corresponder a classificação boa."""
    e = _empresa(
        usa_https=True, telefone=True, email=True,
        whatsapp=True, instagram=True, facebook=True, cta=True
    )
    resultado = diagnosticar_presenca([e])[0]
    assert resultado["score_presenca_web"] == 100
    assert resultado["classificacao_presenca_web"] == "presenca_boa"
    print("OK: score 100 = presenca_boa")


def test_empresa_inacessivel_score_zero():
    e = _empresa(site_acessivel=False, usa_https=False)
    resultado = diagnosticar_presenca([e])[0]
    assert resultado["score_presenca_web"] == 0
    assert resultado["classificacao_presenca_web"] == "dados_insuficientes"
    print("OK: site inacessivel = score 0 + dados_insuficientes")


if __name__ == "__main__":
    test_score_zero_sem_sinais()
    test_score_so_acessivel()
    test_score_maximo()
    test_score_com_whatsapp_e_telefone()
    test_classificacao_dados_insuficientes_inacessivel()
    test_classificacao_presenca_fraca()
    test_classificacao_presenca_basica()
    test_classificacao_presenca_razoavel()
    test_classificacao_presenca_boa()
    test_oportunidade_site_inacessivel()
    test_oportunidade_sem_whatsapp_e_mais_urgente()
    test_oportunidade_sem_cta()
    test_oportunidade_site_completo()
    test_confianca_sem_dados()
    test_confianca_alta_site_acessivel()
    test_confianca_baixa_inacessivel()
    test_diagnosticar_presenca_adiciona_campos()
    test_diagnosticar_lista_vazia()
    test_diagnostico_menciona_nome()
    test_score_e_classificacao_consistentes()
    test_empresa_inacessivel_score_zero()
    print("\nTodos os testes do diagnosticador_presenca passaram.")
