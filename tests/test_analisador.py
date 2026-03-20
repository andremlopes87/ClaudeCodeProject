"""
tests/test_analisador.py — Testa análise de presença digital e detecção de Instagram.

Roda com: python tests/test_analisador.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.prospeccao.analisador import analisar_empresas, PESOS, SCORE_MAXIMO


def _empresa(website=None, telefone=None, horario=None, email=None, instagram=None):
    """Cria empresa de teste com campos configuráveis."""
    return {
        "osm_id": 1,
        "nome": "Empresa Teste",
        "categoria": "Barbearia",
        "categoria_id": "barbearia",
        "cidade": "São José do Rio Preto",
        "website": website,
        "telefone": telefone,
        "horario": horario,
        "email": email,
        "instagram": instagram,
        "endereco": None,
        "lat": -20.8,
        "lon": -49.4,
        "fonte_dados": "OpenStreetMap/Overpass",
    }


# --- Testes de score_presenca_digital ---

def test_score_zero_sem_dados():
    resultado = analisar_empresas([_empresa()])[0]
    assert resultado["score_presenca_digital"] == 0
    assert resultado["sinais"]["tem_website"] is False
    assert resultado["sinais"]["tem_telefone"] is False
    print("OK: score_presenca_digital zero sem dados")


def test_score_maximo_com_todos_dados():
    e = _empresa(
        website="http://exemplo.com",
        telefone="+55 17 99999-9999",
        horario="Mo-Fr 09:00-18:00",
        email="contato@exemplo.com",
    )
    resultado = analisar_empresas([e])[0]
    assert resultado["score_presenca_digital"] == SCORE_MAXIMO
    assert resultado["sinais"]["tem_website"] is True
    print(f"OK: score_presenca_digital máximo ({SCORE_MAXIMO})")


def test_score_so_telefone():
    resultado = analisar_empresas([_empresa(telefone="+55 17 3333-3333")])[0]
    assert resultado["score_presenca_digital"] == PESOS["telefone"]
    assert resultado["sinais"]["tem_telefone"] is True
    assert resultado["sinais"]["tem_website"] is False
    print(f"OK: score_presenca_digital {PESOS['telefone']} com apenas telefone")


# --- Testes de detecção de Instagram ---

def test_instagram_via_tag_osm():
    """Tag OSM explícita deve ser detectada como Instagram."""
    e = _empresa(instagram="https://instagram.com/empresateste")
    resultado = analisar_empresas([e])[0]
    assert resultado["tem_instagram"] is True
    assert resultado["origem_instagram"] == "tag_osm"
    print("OK: Instagram detectado via tag OSM")


def test_instagram_via_website_url():
    """Website apontando para instagram.com deve ser detectado."""
    e = _empresa(website="https://www.instagram.com/barbearia_joao")
    resultado = analisar_empresas([e])[0]
    assert resultado["tem_instagram"] is True
    assert resultado["origem_instagram"] == "website_url"
    print("OK: Instagram detectado via website_url")


def test_website_instagram_nao_conta_como_site():
    """Se o website for Instagram, não deve contar como site próprio."""
    e = _empresa(website="https://www.instagram.com/barbearia_joao")
    resultado = analisar_empresas([e])[0]
    assert resultado["sinais"]["tem_website"] is False, "Instagram não deve contar como site próprio"
    assert resultado["tem_instagram"] is True
    assert resultado["score_presenca_digital"] == 0, "Score deve ser 0 (sem site real)"
    print("OK: Instagram como website não conta como site próprio")


def test_sem_instagram():
    """Empresa sem nenhum dado de Instagram deve retornar False."""
    e = _empresa(website="http://exemplo.com")
    resultado = analisar_empresas([e])[0]
    assert resultado["tem_instagram"] is False
    assert resultado["origem_instagram"] is None
    print("OK: sem Instagram quando não há dados")


def test_instagram_e_site_separados():
    """Empresa com site próprio E tag de Instagram deve ter ambos."""
    e = _empresa(
        website="http://meusite.com",
        instagram="https://instagram.com/minha_empresa",
    )
    resultado = analisar_empresas([e])[0]
    assert resultado["sinais"]["tem_website"] is True, "Site próprio deve contar"
    assert resultado["tem_instagram"] is True
    assert resultado["score_presenca_digital"] == PESOS["website"]
    print("OK: site próprio e Instagram detectados separadamente")


# --- Testes de confiança ---

def test_confianca_baixa_sem_campos():
    resultado = analisar_empresas([_empresa()])[0]
    assert resultado["confianca_diagnostico"] == "baixa"
    assert resultado["campos_osm_preenchidos"] == 0
    print("OK: confiança baixa com 0 campos")


def test_confianca_media_um_campo():
    resultado = analisar_empresas([_empresa(telefone="+55 17 3333-3333")])[0]
    assert resultado["confianca_diagnostico"] == "media"
    assert resultado["campos_osm_preenchidos"] == 1
    print("OK: confiança media com 1 campo")


def test_confianca_alta_tres_campos():
    e = _empresa(
        website="http://exemplo.com",
        telefone="+55 17 99999-9999",
        horario="Mo-Fr 09:00-18:00",
    )
    resultado = analisar_empresas([e])[0]
    assert resultado["confianca_diagnostico"] == "alta"
    assert resultado["campos_osm_preenchidos"] == 3
    print("OK: confiança alta com 3 campos")


if __name__ == "__main__":
    test_score_zero_sem_dados()
    test_score_maximo_com_todos_dados()
    test_score_so_telefone()
    test_instagram_via_tag_osm()
    test_instagram_via_website_url()
    test_website_instagram_nao_conta_como_site()
    test_sem_instagram()
    test_instagram_e_site_separados()
    test_confianca_baixa_sem_campos()
    test_confianca_media_um_campo()
    test_confianca_alta_tres_campos()
    print("\nTodos os testes do analisador passaram.")
