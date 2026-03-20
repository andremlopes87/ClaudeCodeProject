"""
tests/test_priorizador.py — Testa a lógica de priorização comercial.

Roda com: python tests/test_priorizador.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modulos.prospeccao_operacional.priorizador import priorizar_empresas, ordenar_por_prioridade


def _empresa_analisada(
    nome="Empresa Teste",
    score_presenca=0,
    campos=0,
    tem_website=False,
    tem_telefone=False,
    tem_horario=False,
    tem_email=False,
    tem_instagram=False,
):
    """Cria empresa já analisada (como saída do analisador)."""
    return {
        "osm_id": 1,
        "nome": nome,
        "categoria": "Barbearia",
        "cidade": "São José do Rio Preto",
        "score_presenca_digital": score_presenca,
        "campos_osm_preenchidos": campos,
        "tem_instagram": tem_instagram,
        "origem_instagram": "tag_osm" if tem_instagram else None,
        "sinais": {
            "tem_website": tem_website,
            "tem_telefone": tem_telefone,
            "tem_horario": tem_horario,
            "tem_email": tem_email,
        },
        "confianca_diagnostico": "baixa" if campos == 0 else "media",
    }


# --- Testes de classificação ---

def test_sem_nome_e_pouco_util():
    """Empresa sem nome deve ser pouco_util."""
    e = _empresa_analisada(nome="(sem nome registrado)")
    resultado = priorizar_empresas([e])[0]
    assert resultado["classificacao_comercial"] == "pouco_util"
    assert resultado["prioridade_abordagem"] == "nula"
    assert resultado["score_prontidao_ia"] == 0
    print("OK: sem nome -> pouco_util")


def test_semi_digital_com_nome_e_telefone():
    """Nome + telefone = score_prontidao 45 -> semi_digital_prioritaria."""
    e = _empresa_analisada(
        nome="Oficina do Carlos",
        score_presenca=30,
        campos=1,
        tem_telefone=True,
    )
    resultado = priorizar_empresas([e])[0]
    assert resultado["classificacao_comercial"] == "semi_digital_prioritaria"
    assert resultado["prioridade_abordagem"] == "alta"
    assert resultado["score_prontidao_ia"] == 45  # 25 (nome) + 20 (tel)
    print("OK: nome + telefone -> semi_digital_prioritaria (score 45)")


def test_analogica_so_nome():
    """Apenas nome identificado (sem campos OSM) -> analogica."""
    e = _empresa_analisada(nome="Padaria Central", score_presenca=0, campos=0)
    resultado = priorizar_empresas([e])[0]
    assert resultado["classificacao_comercial"] == "analogica"
    assert resultado["prioridade_abordagem"] == "media"
    assert resultado["score_prontidao_ia"] == 25  # apenas nome
    print("OK: só nome -> analogica (score 25)")


def test_digital_basica_muito_organizada():
    """Empresa com score_presenca >= 65 -> digital_basica."""
    e = _empresa_analisada(
        nome="Empresa Organizada",
        score_presenca=70,
        campos=3,
        tem_website=True,
        tem_telefone=True,
        tem_horario=True,
    )
    resultado = priorizar_empresas([e])[0]
    assert resultado["classificacao_comercial"] == "digital_basica"
    assert resultado["prioridade_abordagem"] == "baixa"
    print("OK: presença >= 65 -> digital_basica")


def test_penalidade_presenca_alta():
    """Score de presença alto deve reduzir score_prontidao_ia."""
    e_baixa = _empresa_analisada(
        nome="Empresa A", score_presenca=30, campos=1, tem_telefone=True
    )
    e_alta = _empresa_analisada(
        nome="Empresa B", score_presenca=70, campos=3,
        tem_website=True, tem_telefone=True, tem_horario=True
    )
    r_baixa = priorizar_empresas([e_baixa])[0]
    r_alta = priorizar_empresas([e_alta])[0]
    # Empresa com presença muito alta recebe penalidade
    # r_alta tem score bruto = 25+20+15+10 = 70, depois -20 = 50
    # mas classificacao = digital_basica por score_presenca >= 65
    assert r_alta["classificacao_comercial"] == "digital_basica"
    print("OK: penalidade aplicada em empresa com presença alta")


def test_instagram_e_bonus():
    """Instagram deve adicionar 5 pontos ao score_prontidao_ia."""
    sem_ig = _empresa_analisada(nome="Empresa", score_presenca=30, campos=1, tem_telefone=True)
    com_ig = _empresa_analisada(nome="Empresa", score_presenca=30, campos=1, tem_telefone=True, tem_instagram=True)
    r_sem = priorizar_empresas([sem_ig])[0]
    r_com = priorizar_empresas([com_ig])[0]
    assert r_com["score_prontidao_ia"] == r_sem["score_prontidao_ia"] + 5
    print("OK: Instagram adiciona 5 pontos de bônus")


def test_ordenacao_prioridade():
    """Candidatas priorizadas devem estar ordenadas corretamente."""
    empresas = [
        {**_empresa_analisada(nome="Analogica", score_presenca=0, campos=0),
         "score_prontidao_ia": 25, "classificacao_comercial": "analogica",
         "prioridade_abordagem": "media", "campos_osm_preenchidos": 0},
        {**_empresa_analisada(nome="Semi Digital", score_presenca=30, campos=1, tem_telefone=True),
         "score_prontidao_ia": 45, "classificacao_comercial": "semi_digital_prioritaria",
         "prioridade_abordagem": "alta", "campos_osm_preenchidos": 1},
    ]
    ordenadas = ordenar_por_prioridade(empresas)
    assert ordenadas[0]["prioridade_abordagem"] == "alta"
    assert ordenadas[1]["prioridade_abordagem"] == "media"
    print("OK: ordenação coloca 'alta' antes de 'media'")


def test_motivo_gerado():
    """Motivo deve ser uma string não vazia."""
    e = _empresa_analisada(nome="Empresa X", score_presenca=30, campos=1, tem_telefone=True)
    resultado = priorizar_empresas([e])[0]
    assert isinstance(resultado["motivo_prioridade"], str)
    assert len(resultado["motivo_prioridade"]) > 10
    print("OK: motivo_prioridade gerado com conteúdo")


if __name__ == "__main__":
    test_sem_nome_e_pouco_util()
    test_semi_digital_com_nome_e_telefone()
    test_analogica_so_nome()
    test_digital_basica_muito_organizada()
    test_penalidade_presenca_alta()
    test_instagram_e_bonus()
    test_ordenacao_prioridade()
    test_motivo_gerado()
    print("\nTodos os testes do priorizador passaram.")
