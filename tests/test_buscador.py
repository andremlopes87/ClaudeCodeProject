"""
tests/test_buscador.py — Testa o módulo de busca e padronização de empresas.

Estes testes verificam a lógica de padronização e deduplicação
sem chamar a API externa (usa dados simulados).

Roda com: python tests/test_buscador.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.prospeccao.buscador import _padronizar


def _empresa_bruta(osm_id=123, nome="Empresa Teste", website=None, telefone=None):
    """Cria dado bruto simulado (como viria do conector)."""
    return {
        "osm_id": osm_id,
        "nome": nome,
        "website": website,
        "telefone": telefone,
        "horario": None,
        "email": None,
        "endereco": None,
        "lat": -20.8,
        "lon": -49.4,
        "fonte_dados": "OpenStreetMap/Overpass",
    }


def test_padronizar_campos_presentes():
    """Campos presentes devem ser preservados."""
    bruta = _empresa_bruta(
        osm_id=1,
        nome="Salão da Maria",
        telefone="+55 17 9999-9999",
    )
    resultado = _padronizar(bruta, "salao_de_beleza", "Salão de Beleza")

    assert resultado["nome"] == "Salão da Maria"
    assert resultado["categoria"] == "Salão de Beleza"
    assert resultado["categoria_id"] == "salao_de_beleza"
    assert resultado["telefone"] == "+55 17 9999-9999"
    assert resultado["website"] is None
    print("OK: campos presentes preservados")


def test_padronizar_sem_nome():
    """Empresa sem nome deve receber valor padrão, não None."""
    bruta = _empresa_bruta(osm_id=2, nome=None)
    resultado = _padronizar(bruta, "acougue", "Açougue")
    assert resultado["nome"] == "(sem nome registrado)"
    print("OK: nome ausente recebe valor padrão")


def test_padronizar_cidade_vem_do_config():
    """Cidade deve vir do config, não dos dados brutos."""
    import config
    bruta = _empresa_bruta(osm_id=3)
    resultado = _padronizar(bruta, "padaria", "Padaria")
    assert resultado["cidade"] == config.CIDADE
    print(f"OK: cidade correta do config: {config.CIDADE}")


def test_padronizar_preserva_osm_id():
    """OSM ID deve ser preservado intacto."""
    bruta = _empresa_bruta(osm_id=99999)
    resultado = _padronizar(bruta, "barbearia", "Barbearia")
    assert resultado["osm_id"] == 99999
    print("OK: OSM ID preservado")


def test_padronizar_todos_campos_existem():
    """Resultado deve conter todos os campos obrigatórios."""
    campos_obrigatorios = [
        "osm_id", "nome", "categoria", "categoria_id", "cidade",
        "website", "telefone", "horario", "email", "endereco",
        "lat", "lon", "fonte_dados",
    ]
    bruta = _empresa_bruta()
    resultado = _padronizar(bruta, "autopecas", "Autopeças")
    for campo in campos_obrigatorios:
        assert campo in resultado, f"Campo ausente: {campo}"
    print("OK: todos os campos obrigatórios presentes")


if __name__ == "__main__":
    test_padronizar_campos_presentes()
    test_padronizar_sem_nome()
    test_padronizar_cidade_vem_do_config()
    test_padronizar_preserva_osm_id()
    test_padronizar_todos_campos_existem()
    print("\nTodos os testes do buscador passaram.")
