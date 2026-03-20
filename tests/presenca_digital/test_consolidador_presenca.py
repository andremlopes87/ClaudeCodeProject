"""
tests/presenca_digital/test_consolidador_presenca.py — Testa consolidação comercial.

Roda com: python tests/presenca_digital/test_consolidador_presenca.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modulos.presenca_digital.consolidador_presenca import (
    consolidar_presenca,
    gerar_fila_marketing,
    _calcular_score_consolidado,
    _detectar_gap,
    _classificar_comercialmente,
    _pronta_para_oferta,
    _solucao_recomendada,
    _prioridade_oferta,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empresa_base(**kwargs):
    base = {
        "nome": "Empresa Teste",
        "categoria_id": "barbearia",
        "classificacao_comercial": "analogica",
        "score_prontidao_ia": 45,
        "classificacao_presenca_web": "dados_insuficientes",
        "score_presenca_web": 0,
        "tem_site": False,
        "site_acessivel": False,
        "usa_https": False,
        "tem_cta_clara": False,
        "contato_principal": None,
        "website_confirmado": None,
        "origem_website": "nao_identificado",
        "confianca_website": "nao_identificado",
        "instagram_confirmado": None,
        "origem_instagram": "nao_identificado",
        "confianca_instagram": "nao_identificado",
        "facebook_confirmado": None,
        "origem_facebook": "nao_identificado",
        "confianca_facebook": "nao_identificado",
        "whatsapp_confirmado": None,
        "origem_whatsapp": "nao_identificado",
        "confianca_whatsapp": "nao_identificado",
        "email_confirmado": None,
        "origem_email": "nao_identificado",
        "confianca_email": "nao_identificado",
        "telefone_confirmado": None,
        "origem_telefone": "nao_identificado",
        "confianca_telefone": "nao_identificado",
    }
    base.update(kwargs)
    return base


def _empresa_com_telefone(**kwargs):
    base = _empresa_base(
        telefone_confirmado="+55 17 3333-4444",
        origem_telefone="osm",
        confianca_telefone="alta",
    )
    base.update(kwargs)
    return base


def _empresa_com_website_completo(**kwargs):
    """Empresa com website acessível e vários canais."""
    base = _empresa_base(
        classificacao_comercial="digital_basica",
        classificacao_presenca_web="presenca_boa",
        score_presenca_web=85,
        tem_site=True,
        site_acessivel=True,
        usa_https=True,
        tem_cta_clara=True,
        website_confirmado="https://empresa.com.br",
        origem_website="osm_verificado",
        confianca_website="alta",
        telefone_confirmado="+55 17 3333-4444",
        origem_telefone="osm",
        confianca_telefone="alta",
        whatsapp_confirmado="https://wa.me/5517999991111",
        origem_whatsapp="html_website",
        confianca_whatsapp="media",
        instagram_confirmado="https://instagram.com/empresa",
        origem_instagram="html_website",
        confianca_instagram="media",
        facebook_confirmado="https://facebook.com/empresa",
        origem_facebook="html_website",
        confianca_facebook="media",
        email_confirmado="contato@empresa.com.br",
        origem_email="osm",
        confianca_email="alta",
    )
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Testes de score
# ---------------------------------------------------------------------------

def test_score_zero_pouco_util():
    e = _empresa_base(classificacao_comercial="pouco_util")
    assert _calcular_score_consolidado(e) == 0
    print("OK: score 0 para pouco_util sem canais")


def test_score_so_nome():
    """Empresa identificável mas sem canais."""
    e = _empresa_base()
    assert _calcular_score_consolidado(e) == 15
    print("OK: score 15 para empresa identificavel sem canais")


def test_score_nome_mais_telefone_alta():
    """15 (nome) + 12 (telefone alta) = 27."""
    e = _empresa_com_telefone()
    assert _calcular_score_consolidado(e) == 27
    print("OK: score 27 para empresa com nome + telefone alta")


def test_score_maximo_possivel():
    """Empresa com todos os canais confirmados em alta + presença boa."""
    e = _empresa_com_website_completo()
    score = _calcular_score_consolidado(e)
    # 15 + 15 + 12 + round(12*0.7) + 10 + round(8*0.7) + round(5*0.7) + 8 + round(85/100*15)
    # = 15 + 15 + 12 + 8 + 10 + 6 + 4 + 8 + 13 = 91
    assert score >= 85
    print(f"OK: score alto ({score}) para empresa com presenca completa")


def test_score_telefone_media_vale_menos_que_alta():
    e_alta = _empresa_com_telefone()
    e_media = _empresa_com_telefone(
        confianca_telefone="media",
        origem_telefone="html_website",
    )
    assert _calcular_score_consolidado(e_alta) > _calcular_score_consolidado(e_media)
    print("OK: telefone alta vale mais que media no score")


# ---------------------------------------------------------------------------
# Testes de detecção de gap
# ---------------------------------------------------------------------------

def test_gap_dados_insuficientes_para_pouco_util():
    e = _empresa_base(classificacao_comercial="pouco_util")
    assert _detectar_gap(e) == "dados_insuficientes"
    print("OK: gap dados_insuficientes para pouco_util")


def test_gap_sem_canais():
    e = _empresa_base()  # sem nenhum canal
    assert _detectar_gap(e) == "sem_canais"
    print("OK: gap sem_canais quando nenhum canal identificado")


def test_gap_sem_website_com_telefone():
    e = _empresa_com_telefone()  # tem telefone mas sem website
    assert _detectar_gap(e) == "sem_website"
    print("OK: gap sem_website quando tem telefone mas sem website")


def test_gap_site_inacessivel():
    e = _empresa_base(
        website_confirmado="https://exemplo.com.br",
        confianca_website="media",
        tem_site=True,
        site_acessivel=False,
        confianca_telefone="alta",
        telefone_confirmado="+55 17 99999-0000",
    )
    assert _detectar_gap(e) == "site_inacessivel"
    print("OK: gap site_inacessivel quando site nao responde")


def test_gap_sem_whatsapp_com_website():
    e = _empresa_base(
        website_confirmado="https://exemplo.com.br",
        confianca_website="alta",
        tem_site=True,
        site_acessivel=True,
        confianca_telefone="alta",
    )
    assert _detectar_gap(e) == "sem_whatsapp"
    print("OK: gap sem_whatsapp quando tem website mas sem WhatsApp")


def test_gap_presenca_estruturada():
    """Empresa com todos os sinais = presenca_estruturada."""
    e = _empresa_com_website_completo(tem_cta_clara=True, usa_https=True)
    assert _detectar_gap(e) == "presenca_estruturada"
    print("OK: gap presenca_estruturada quando tudo presente")


# ---------------------------------------------------------------------------
# Testes de classificação comercial
# ---------------------------------------------------------------------------

def test_classificacao_pouca_utilidade_pouco_util():
    e = _empresa_base(classificacao_comercial="pouco_util")
    score = _calcular_score_consolidado(e)
    gap = _detectar_gap(e)
    assert _classificar_comercialmente(e, score, gap) == "pouca_utilidade_presenca"
    print("OK: pouca_utilidade_presenca para pouco_util")


def test_classificacao_pouca_utilidade_sem_canais():
    e = _empresa_base()  # identificável mas sem canais
    score = _calcular_score_consolidado(e)  # = 15
    gap = _detectar_gap(e)  # = "sem_canais"
    assert _classificar_comercialmente(e, score, gap) == "pouca_utilidade_presenca"
    print("OK: pouca_utilidade_presenca para empresa sem canais")


def test_classificacao_alta_com_telefone_sem_website():
    """Empresa com telefone OSM mas sem website = oportunidade_alta."""
    e = _empresa_com_telefone()
    score = _calcular_score_consolidado(e)  # 27
    gap = _detectar_gap(e)  # sem_website
    assert score >= 25
    assert _classificar_comercialmente(e, score, gap) == "oportunidade_alta_presenca"
    print("OK: oportunidade_alta_presenca para empresa com telefone sem website")


def test_classificacao_baixa_com_presenca_boa():
    """Empresa com presença já boa = oportunidade_baixa."""
    e = _empresa_com_website_completo()
    score = _calcular_score_consolidado(e)
    gap = _detectar_gap(e)
    cls = _classificar_comercialmente(e, score, gap)
    # Presença boa → não é alta (não tem lacuna). Score alto, tem canais → media ou baixa.
    assert cls in ("oportunidade_media_presenca", "oportunidade_baixa_presenca")
    print(f"OK: classificacao {cls} para empresa com presenca boa")


# ---------------------------------------------------------------------------
# Testes de solução recomendada
# ---------------------------------------------------------------------------

def test_solucao_sem_website_barbearia():
    e = _empresa_com_telefone(categoria_id="barbearia")
    s = _solucao_recomendada(e, "sem_website")
    assert "agendamento" in s.lower() or "whatsapp" in s.lower()
    print("OK: solucao sem_website para barbearia menciona agendamento/whatsapp")


def test_solucao_sem_website_oficina():
    e = _empresa_com_telefone(categoria_id="oficina_mecanica")
    s = _solucao_recomendada(e, "sem_website")
    assert "orçamento" in s.lower() or "orcamento" in s.lower()
    print("OK: solucao sem_website para oficina menciona orcamento")


def test_solucao_sem_website_default():
    e = _empresa_com_telefone(categoria_id="categoria_desconhecida")
    s = _solucao_recomendada(e, "sem_website")
    assert len(s) > 10
    print("OK: solucao default definida para categoria desconhecida")


def test_solucao_sem_whatsapp():
    e = _empresa_base()
    s = _solucao_recomendada(e, "sem_whatsapp")
    assert "whatsapp" in s.lower()
    print("OK: solucao sem_whatsapp menciona WhatsApp")


# ---------------------------------------------------------------------------
# Testes de pronta_para_oferta
# ---------------------------------------------------------------------------

def test_pronta_para_oferta_alta_com_telefone():
    e = _empresa_com_telefone()
    assert _pronta_para_oferta(e, "oportunidade_alta_presenca") is True
    print("OK: pronta_para_oferta True com telefone alta e classificacao alta")


def test_pronta_para_oferta_falso_pouca_utilidade():
    e = _empresa_com_telefone()
    assert _pronta_para_oferta(e, "pouca_utilidade_presenca") is False
    print("OK: pronta_para_oferta False para pouca_utilidade_presenca")


def test_pronta_para_oferta_falso_sem_canais():
    e = _empresa_base()
    assert _pronta_para_oferta(e, "oportunidade_alta_presenca") is False
    print("OK: pronta_para_oferta False sem canais de contato")


# ---------------------------------------------------------------------------
# Testes de prioridade
# ---------------------------------------------------------------------------

def test_prioridade_alta():
    assert _prioridade_oferta("oportunidade_alta_presenca") == "alta"
    print("OK: prioridade alta para oportunidade_alta")


def test_prioridade_nula():
    assert _prioridade_oferta("pouca_utilidade_presenca") == "nula"
    print("OK: prioridade nula para pouca_utilidade")


# ---------------------------------------------------------------------------
# Testes do pipeline completo
# ---------------------------------------------------------------------------

def test_pipeline_adiciona_todos_campos():
    e = _empresa_com_telefone()
    resultado = consolidar_presenca([e])[0]
    campos = [
        "score_presenca_consolidado",
        "classificacao_presenca_comercial",
        "pronta_para_oferta_presenca",
        "principal_gargalo_presenca",
        "oportunidade_presenca_principal",
        "solucao_recomendada_presenca",
        "prioridade_oferta_presenca",
        "motivo_prioridade_presenca",
    ]
    for campo in campos:
        assert campo in resultado, f"{campo} ausente"
    print("OK: todos os campos de consolidacao presentes")


def test_pipeline_lista_vazia():
    assert consolidar_presenca([]) == []
    print("OK: lista vazia retorna lista vazia")


def test_fila_marketing_inclui_alta_e_media():
    empresas = [
        _empresa_com_telefone(),  # oportunidade_alta
        _empresa_base(),           # pouca_utilidade
    ]
    resultado = consolidar_presenca(empresas)
    fila = gerar_fila_marketing(resultado)
    assert len(fila) >= 1
    assert all(
        e["classificacao_presenca_comercial"] in (
            "oportunidade_alta_presenca", "oportunidade_media_presenca"
        )
        for e in fila
    )
    print("OK: fila_marketing inclui apenas alta e media")


def test_fila_marketing_ordenada_por_prioridade():
    """Alta deve aparecer antes de media na fila."""
    empresa_alta = _empresa_com_telefone(score_prontidao_ia=60)
    empresa_media = _empresa_base(
        score_prontidao_ia=40,
        confianca_telefone="baixa",
        telefone_confirmado=None,
        score_presenca_web=60,
        classificacao_presenca_web="presenca_razoavel",
    )
    resultado = consolidar_presenca([empresa_media, empresa_alta])
    fila = gerar_fila_marketing(resultado)
    if len(fila) >= 2:
        prioridades = [e["prioridade_oferta_presenca"] for e in fila]
        _ORDEM = {"alta": 0, "media": 1, "baixa": 2, "nula": 3}
        valores = [_ORDEM[p] for p in prioridades]
        assert valores == sorted(valores), "Fila nao ordenada por prioridade"
    print("OK: fila_marketing ordenada por prioridade")


def test_motivo_prioridade_nao_vazio():
    e = _empresa_com_telefone()
    resultado = consolidar_presenca([e])[0]
    assert len(resultado["motivo_prioridade_presenca"]) > 20
    print("OK: motivo_prioridade nao vazio")


if __name__ == "__main__":
    test_score_zero_pouco_util()
    test_score_so_nome()
    test_score_nome_mais_telefone_alta()
    test_score_maximo_possivel()
    test_score_telefone_media_vale_menos_que_alta()
    test_gap_dados_insuficientes_para_pouco_util()
    test_gap_sem_canais()
    test_gap_sem_website_com_telefone()
    test_gap_site_inacessivel()
    test_gap_sem_whatsapp_com_website()
    test_gap_presenca_estruturada()
    test_classificacao_pouca_utilidade_pouco_util()
    test_classificacao_pouca_utilidade_sem_canais()
    test_classificacao_alta_com_telefone_sem_website()
    test_classificacao_baixa_com_presenca_boa()
    test_solucao_sem_website_barbearia()
    test_solucao_sem_website_oficina()
    test_solucao_sem_website_default()
    test_solucao_sem_whatsapp()
    test_pronta_para_oferta_alta_com_telefone()
    test_pronta_para_oferta_falso_pouca_utilidade()
    test_pronta_para_oferta_falso_sem_canais()
    test_prioridade_alta()
    test_prioridade_nula()
    test_pipeline_adiciona_todos_campos()
    test_pipeline_lista_vazia()
    test_fila_marketing_inclui_alta_e_media()
    test_fila_marketing_ordenada_por_prioridade()
    test_motivo_prioridade_nao_vazio()
    print("\nTodos os testes do consolidador_presenca passaram.")
