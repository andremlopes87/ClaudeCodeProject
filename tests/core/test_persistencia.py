"""
tests/test_persistencia.py — Testa o módulo único de leitura e escrita de dados.

Roda com: python tests/test_persistencia.py
"""

import sys
import os
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.persistencia import salvar_resultados, carregar_resultados


def test_salvar_e_carregar_basico():
    """Salvar e carregar deve retornar os mesmos dados."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pasta = Path(tmpdir)
        dados = [
            {"nome": "Empresa A", "score_digitalizacao": 10},
            {"nome": "Empresa B", "score_digitalizacao": 50},
        ]
        caminho = salvar_resultados(dados, sufixo="teste", pasta=pasta)

        assert caminho.exists(), "Arquivo deveria ter sido criado"

        carregados = carregar_resultados(caminho)
        assert len(carregados) == 2, "Deveria ter 2 registros"
        assert carregados[0]["nome"] == "Empresa A"
        assert carregados[1]["score_digitalizacao"] == 50
    print("OK: salvar e carregar básico")


def test_arquivo_tem_nome_com_timestamp():
    """Nome do arquivo deve conter timestamp e sufixo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pasta = Path(tmpdir)
        caminho = salvar_resultados([{"x": 1}], sufixo="candidatas", pasta=pasta)
        assert "candidatas" in caminho.name
        assert "resultado_" in caminho.name
        assert caminho.suffix == ".json"
    print("OK: nome do arquivo com timestamp e sufixo")


def test_lista_vazia():
    """Deve salvar e carregar lista vazia sem erros."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pasta = Path(tmpdir)
        caminho = salvar_resultados([], sufixo="vazio", pasta=pasta)
        carregados = carregar_resultados(caminho)
        assert carregados == []
    print("OK: lista vazia")


def test_arquivo_nao_encontrado():
    """Deve lançar FileNotFoundError para arquivo inexistente."""
    try:
        carregar_resultados("arquivo_que_nao_existe.json")
        assert False, "Deveria ter lançado FileNotFoundError"
    except FileNotFoundError:
        pass
    print("OK: FileNotFoundError para arquivo inexistente")


def test_dados_com_caracteres_especiais():
    """Deve preservar caracteres especiais do português."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pasta = Path(tmpdir)
        dados = [{"nome": "Barbearia do João", "cidade": "São José do Rio Preto"}]
        caminho = salvar_resultados(dados, pasta=pasta)
        carregados = carregar_resultados(caminho)
        assert carregados[0]["nome"] == "Barbearia do João"
        assert carregados[0]["cidade"] == "São José do Rio Preto"
    print("OK: caracteres especiais preservados")


if __name__ == "__main__":
    test_salvar_e_carregar_basico()
    test_arquivo_tem_nome_com_timestamp()
    test_lista_vazia()
    test_arquivo_nao_encontrado()
    test_dados_com_caracteres_especiais()
    print("\nTodos os testes de persistência passaram.")
