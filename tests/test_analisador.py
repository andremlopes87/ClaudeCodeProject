"""
tests/test_analisador.py — Testa as heurísticas de análise de presença digital.

Roda com: python tests/test_analisador.py
"""

import sys
import os

# Garante que o diretório raiz do projeto está no path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.prospeccao.analisador import analisar_empresas, PESOS, SCORE_MAXIMO


def _empresa(website=None, telefone=None, horario=None, email=None):
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
        "endereco": None,
        "lat": -20.8,
        "lon": -49.4,
        "fonte_dados": "OpenStreetMap/Overpass",
    }


def test_score_zero_sem_dados():
    """Empresa sem nenhum dado deve ter score zero."""
    resultado = analisar_empresas([_empresa()])[0]
    assert resultado["score_digitalizacao"] == 0, "Score deveria ser 0"
    assert resultado["sinais"]["tem_website"] is False
    assert resultado["sinais"]["tem_telefone"] is False
    assert resultado["sinais"]["tem_horario"] is False
    assert resultado["sinais"]["tem_email"] is False
    print("OK: score zero sem dados")


def test_score_maximo_com_todos_dados():
    """Empresa com todos os campos deve ter score máximo."""
    empresa = _empresa(
        website="http://exemplo.com",
        telefone="+55 17 99999-9999",
        horario="Mo-Fr 09:00-18:00",
        email="contato@exemplo.com",
    )
    resultado = analisar_empresas([empresa])[0]
    assert resultado["score_digitalizacao"] == SCORE_MAXIMO, f"Score deveria ser {SCORE_MAXIMO}"
    assert resultado["sinais"]["tem_website"] is True
    assert resultado["sinais"]["tem_telefone"] is True
    assert resultado["sinais"]["tem_horario"] is True
    assert resultado["sinais"]["tem_email"] is True
    print(f"OK: score máximo ({SCORE_MAXIMO}) com todos os dados")


def test_score_so_website():
    """Empresa apenas com website deve ter score igual ao peso do website."""
    resultado = analisar_empresas([_empresa(website="http://exemplo.com")])[0]
    assert resultado["score_digitalizacao"] == PESOS["website"]
    assert resultado["sinais"]["tem_website"] is True
    assert resultado["sinais"]["tem_telefone"] is False
    print(f"OK: score {PESOS['website']} com apenas website")


def test_score_so_telefone():
    """Empresa apenas com telefone deve ter score igual ao peso do telefone."""
    resultado = analisar_empresas([_empresa(telefone="+55 17 3333-3333")])[0]
    assert resultado["score_digitalizacao"] == PESOS["telefone"]
    assert resultado["sinais"]["tem_telefone"] is True
    assert resultado["sinais"]["tem_website"] is False
    print(f"OK: score {PESOS['telefone']} com apenas telefone")


def test_confianca_baixa_sem_campos():
    """0 campos preenchidos no OSM → confiança baixa."""
    resultado = analisar_empresas([_empresa()])[0]
    assert resultado["confianca_diagnostico"] == "baixa"
    assert resultado["campos_osm_preenchidos"] == 0
    print("OK: confiança baixa com 0 campos")


def test_confianca_media_um_campo():
    """1 campo preenchido → confiança media."""
    resultado = analisar_empresas([_empresa(telefone="+55 17 3333-3333")])[0]
    assert resultado["confianca_diagnostico"] == "media"
    assert resultado["campos_osm_preenchidos"] == 1
    print("OK: confiança media com 1 campo")


def test_confianca_alta_tres_campos():
    """3+ campos preenchidos → confiança alta."""
    empresa = _empresa(
        website="http://exemplo.com",
        telefone="+55 17 99999-9999",
        horario="Mo-Fr 09:00-18:00",
    )
    resultado = analisar_empresas([empresa])[0]
    assert resultado["confianca_diagnostico"] == "alta"
    assert resultado["campos_osm_preenchidos"] == 3
    print("OK: confiança alta com 3 campos")


def test_lista_multiplas_empresas():
    """Deve processar lista com múltiplas empresas corretamente."""
    empresas = [
        _empresa(),
        _empresa(website="http://a.com", telefone="11 9999-9999"),
        _empresa(website="http://b.com", telefone="11 8888-8888", horario="9-18"),
    ]
    resultados = analisar_empresas(empresas)
    assert len(resultados) == 3
    assert resultados[0]["score_digitalizacao"] == 0
    assert resultados[1]["score_digitalizacao"] == PESOS["website"] + PESOS["telefone"]
    assert resultados[2]["score_digitalizacao"] == PESOS["website"] + PESOS["telefone"] + PESOS["horario"]
    print("OK: processamento de múltiplas empresas")


if __name__ == "__main__":
    test_score_zero_sem_dados()
    test_score_maximo_com_todos_dados()
    test_score_so_website()
    test_score_so_telefone()
    test_confianca_baixa_sem_campos()
    test_confianca_media_um_campo()
    test_confianca_alta_tres_campos()
    test_lista_multiplas_empresas()
    print("\nTodos os testes do analisador passaram.")
