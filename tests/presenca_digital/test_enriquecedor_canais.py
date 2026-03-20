"""
tests/presenca_digital/test_enriquecedor_canais.py — Testa consolidação de canais digitais.

Não faz requisições HTTP reais — testa a lógica de consolidação diretamente.

Roda com: python tests/presenca_digital/test_enriquecedor_canais.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modulos.presenca_digital.enriquecedor_canais import (
    _canal_website,
    _canal_instagram,
    _canal_facebook,
    _canal_whatsapp,
    _canal_email,
    _canal_telefone,
    _nao_identificado,
    tem_canal_identificado,
    enriquecer_canais,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empresa_base(**kwargs):
    base = {
        "nome": "Empresa Teste",
        "website": None,
        "telefone": None,
        "email": None,
        "instagram": None,
        "tem_site": False,
        "site_acessivel": False,
        "tem_telefone_no_site": False,
        "tem_email_no_site": False,
        "tem_whatsapp_no_site": False,
        "tem_instagram_no_site": False,
        "tem_facebook_no_site": False,
        "_val_tel_site": None,
        "_val_email_site": None,
        "_val_whatsapp_site": None,
        "_val_instagram_site": None,
        "_val_facebook_site": None,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Testes do canal website
# ---------------------------------------------------------------------------

def test_website_osm_acessivel_e_alta():
    e = _empresa_base(website="https://exemplo.com.br", site_acessivel=True)
    r = _canal_website(e)
    assert r["website_confirmado"] == "https://exemplo.com.br"
    assert r["origem_website"] == "osm_verificado"
    assert r["confianca_website"] == "alta"
    print("OK: website OSM + acessivel = confianca alta")


def test_website_osm_inacessivel_e_media():
    e = _empresa_base(website="https://exemplo.com.br", site_acessivel=False)
    r = _canal_website(e)
    assert r["website_confirmado"] == "https://exemplo.com.br"
    assert r["origem_website"] == "osm"
    assert r["confianca_website"] == "media"
    print("OK: website OSM + inacessivel = confianca media")


def test_website_sem_website_nao_identificado():
    e = _empresa_base(website=None)
    r = _canal_website(e)
    assert r["website_confirmado"] is None
    assert r["confianca_website"] == "nao_identificado"
    print("OK: sem website = nao_identificado")


def test_website_instagram_url_nao_conta():
    e = _empresa_base(website="https://instagram.com/empresa_teste", site_acessivel=True)
    r = _canal_website(e)
    assert r["website_confirmado"] is None
    assert r["confianca_website"] == "nao_identificado"
    print("OK: URL do Instagram no campo website nao conta como website")


# ---------------------------------------------------------------------------
# Testes do canal instagram
# ---------------------------------------------------------------------------

def test_instagram_osm_tag_e_alta():
    e = _empresa_base(instagram="https://instagram.com/empresa_osm")
    r = _canal_instagram(e, {})
    assert r["instagram_confirmado"] == "https://instagram.com/empresa_osm"
    assert r["origem_instagram"] == "osm"
    assert r["confianca_instagram"] == "alta"
    print("OK: instagram via tag OSM = confianca alta")


def test_instagram_website_url_e_alta():
    e = _empresa_base(website="https://instagram.com/empresa_url")
    r = _canal_instagram(e, {})
    assert r["instagram_confirmado"] == "https://instagram.com/empresa_url"
    assert r["origem_instagram"] == "website_osm"
    assert r["confianca_instagram"] == "alta"
    print("OK: instagram via website URL = confianca alta")


def test_instagram_html_valor_e_media():
    e = _empresa_base(
        tem_instagram_no_site=True,
        _val_instagram_site="https://instagram.com/empresa_html",
    )
    r = _canal_instagram(e, {})
    assert r["instagram_confirmado"] == "https://instagram.com/empresa_html"
    assert r["origem_instagram"] == "html_website"
    assert r["confianca_instagram"] == "media"
    print("OK: instagram via HTML com URL = confianca media")


def test_instagram_contato_subpagina_e_media():
    e = _empresa_base(tem_instagram_no_site=False)
    sinais_contato = {
        "tem_instagram_no_site": True,
        "_val_instagram_site": "https://instagram.com/empresa_contato",
    }
    r = _canal_instagram(e, sinais_contato)
    assert r["instagram_confirmado"] == "https://instagram.com/empresa_contato"
    assert r["origem_instagram"] == "html_contato"
    assert r["confianca_instagram"] == "media"
    print("OK: instagram via subpagina contato = confianca media")


def test_instagram_sinal_booleano_e_baixa():
    e = _empresa_base(tem_instagram_no_site=True, _val_instagram_site=None)
    r = _canal_instagram(e, {})
    assert r["instagram_confirmado"] is None
    assert r["origem_instagram"] == "html_sinal"
    assert r["confianca_instagram"] == "baixa"
    print("OK: instagram via sinal booleano sem URL = confianca baixa")


def test_instagram_prioridade_osm_sobre_html():
    """OSM tag deve ter prioridade sobre valor HTML."""
    e = _empresa_base(
        instagram="https://instagram.com/osm_version",
        tem_instagram_no_site=True,
        _val_instagram_site="https://instagram.com/html_version",
    )
    r = _canal_instagram(e, {})
    assert r["instagram_confirmado"] == "https://instagram.com/osm_version"
    assert r["confianca_instagram"] == "alta"
    print("OK: OSM tem prioridade sobre HTML para instagram")


# ---------------------------------------------------------------------------
# Testes do canal facebook
# ---------------------------------------------------------------------------

def test_facebook_html_valor_e_media():
    e = _empresa_base(_val_facebook_site="https://facebook.com/empresa_teste")
    r = _canal_facebook(e, {})
    assert r["facebook_confirmado"] == "https://facebook.com/empresa_teste"
    assert r["origem_facebook"] == "html_website"
    assert r["confianca_facebook"] == "media"
    print("OK: facebook via HTML com URL = confianca media")


def test_facebook_sinal_booleano_e_baixa():
    e = _empresa_base(tem_facebook_no_site=True)
    r = _canal_facebook(e, {})
    assert r["facebook_confirmado"] is None
    assert r["confianca_facebook"] == "baixa"
    print("OK: facebook via sinal booleano = confianca baixa")


def test_facebook_nao_identificado():
    e = _empresa_base()
    r = _canal_facebook(e, {})
    assert r["confianca_facebook"] == "nao_identificado"
    print("OK: facebook sem dado = nao_identificado")


# ---------------------------------------------------------------------------
# Testes do canal whatsapp
# ---------------------------------------------------------------------------

def test_whatsapp_html_valor_e_media():
    e = _empresa_base(_val_whatsapp_site="https://wa.me/5517999991111")
    r = _canal_whatsapp(e, {})
    assert r["whatsapp_confirmado"] == "https://wa.me/5517999991111"
    assert r["origem_whatsapp"] == "html_website"
    assert r["confianca_whatsapp"] == "media"
    print("OK: whatsapp via HTML com URL = confianca media")


def test_whatsapp_sinal_booleano_e_baixa():
    e = _empresa_base(tem_whatsapp_no_site=True)
    r = _canal_whatsapp(e, {})
    assert r["whatsapp_confirmado"] is None
    assert r["confianca_whatsapp"] == "baixa"
    print("OK: whatsapp via sinal booleano = confianca baixa")


# ---------------------------------------------------------------------------
# Testes do canal email
# ---------------------------------------------------------------------------

def test_email_osm_e_alta():
    e = _empresa_base(email="contato@empresa.com.br")
    r = _canal_email(e, {})
    assert r["email_confirmado"] == "contato@empresa.com.br"
    assert r["origem_email"] == "osm"
    assert r["confianca_email"] == "alta"
    print("OK: email OSM = confianca alta")


def test_email_html_mailto_e_media():
    e = _empresa_base(_val_email_site="info@empresa.com.br")
    r = _canal_email(e, {})
    assert r["email_confirmado"] == "info@empresa.com.br"
    assert r["origem_email"] == "html_website"
    assert r["confianca_email"] == "media"
    print("OK: email via HTML mailto = confianca media")


def test_email_html_sinal_e_baixa():
    e = _empresa_base(tem_email_no_site=True)
    r = _canal_email(e, {})
    assert r["email_confirmado"] is None
    assert r["confianca_email"] == "baixa"
    print("OK: email via sinal booleano = confianca baixa")


# ---------------------------------------------------------------------------
# Testes do canal telefone
# ---------------------------------------------------------------------------

def test_telefone_osm_e_alta():
    e = _empresa_base(telefone="+55 17 3333-4444")
    r = _canal_telefone(e, {})
    assert r["telefone_confirmado"] == "+55 17 3333-4444"
    assert r["origem_telefone"] == "osm"
    assert r["confianca_telefone"] == "alta"
    print("OK: telefone OSM = confianca alta")


def test_telefone_html_tel_href_e_media():
    e = _empresa_base(_val_tel_site="+5517999991111")
    r = _canal_telefone(e, {})
    assert r["telefone_confirmado"] == "+5517999991111"
    assert r["origem_telefone"] == "html_website"
    assert r["confianca_telefone"] == "media"
    print("OK: telefone via HTML tel: href = confianca media")


def test_telefone_sinal_booleano_e_baixa():
    e = _empresa_base(tem_telefone_no_site=True)
    r = _canal_telefone(e, {})
    assert r["telefone_confirmado"] is None
    assert r["confianca_telefone"] == "baixa"
    print("OK: telefone via sinal booleano = confianca baixa")


def test_telefone_nao_identificado():
    e = _empresa_base()
    r = _canal_telefone(e, {})
    assert r["confianca_telefone"] == "nao_identificado"
    print("OK: telefone sem dado = nao_identificado")


# ---------------------------------------------------------------------------
# Testes do pipeline completo
# ---------------------------------------------------------------------------

def test_empresa_sem_dados_todos_nao_identificados():
    """Empresa sem nenhum dado deve ter todos os canais como nao_identificado."""
    e = _empresa_base()
    resultado = enriquecer_canais([e])[0]
    for canal in ["website", "instagram", "facebook", "whatsapp", "email", "telefone"]:
        assert resultado[f"confianca_{canal}"] == "nao_identificado", (
            f"Canal {canal} deveria ser nao_identificado"
        )
    print("OK: empresa sem dados = todos os canais nao_identificado")


def test_empresa_com_osm_completo():
    """Empresa com todos os campos OSM deve ter alta confiança nos canais OSM."""
    e = _empresa_base(
        website="https://exemplo.com.br",
        telefone="+55 17 3333-4444",
        email="contato@exemplo.com.br",
        instagram="https://instagram.com/exemplo",
        site_acessivel=True,
    )
    resultado = enriquecer_canais([e])[0]
    assert resultado["confianca_website"] == "alta"
    assert resultado["confianca_telefone"] == "alta"
    assert resultado["confianca_email"] == "alta"
    assert resultado["confianca_instagram"] == "alta"
    print("OK: empresa com OSM completo tem canais com confianca alta")


def test_tem_canal_identificado_verdadeiro():
    e = _empresa_base(telefone="+55 17 3333-4444")
    resultado = enriquecer_canais([e])[0]
    assert tem_canal_identificado(resultado) is True
    print("OK: tem_canal_identificado retorna True quando ha canal")


def test_tem_canal_identificado_falso():
    e = _empresa_base()
    resultado = enriquecer_canais([e])[0]
    assert tem_canal_identificado(resultado) is False
    print("OK: tem_canal_identificado retorna False quando nao ha canal")


def test_lista_vazia():
    assert enriquecer_canais([]) == []
    print("OK: lista vazia retorna lista vazia")


def test_todos_campos_presentes():
    """Pipeline deve adicionar todos os campos esperados."""
    e = _empresa_base()
    resultado = enriquecer_canais([e])[0]
    canais = ["website", "instagram", "facebook", "whatsapp", "email", "telefone"]
    for canal in canais:
        assert f"{canal}_confirmado" in resultado, f"{canal}_confirmado ausente"
        assert f"origem_{canal}" in resultado, f"origem_{canal} ausente"
        assert f"confianca_{canal}" in resultado, f"confianca_{canal} ausente"
    print("OK: todos os campos de canal presentes no resultado")


if __name__ == "__main__":
    test_website_osm_acessivel_e_alta()
    test_website_osm_inacessivel_e_media()
    test_website_sem_website_nao_identificado()
    test_website_instagram_url_nao_conta()
    test_instagram_osm_tag_e_alta()
    test_instagram_website_url_e_alta()
    test_instagram_html_valor_e_media()
    test_instagram_contato_subpagina_e_media()
    test_instagram_sinal_booleano_e_baixa()
    test_instagram_prioridade_osm_sobre_html()
    test_facebook_html_valor_e_media()
    test_facebook_sinal_booleano_e_baixa()
    test_facebook_nao_identificado()
    test_whatsapp_html_valor_e_media()
    test_whatsapp_sinal_booleano_e_baixa()
    test_email_osm_e_alta()
    test_email_html_mailto_e_media()
    test_email_html_sinal_e_baixa()
    test_telefone_osm_e_alta()
    test_telefone_html_tel_href_e_media()
    test_telefone_sinal_booleano_e_baixa()
    test_telefone_nao_identificado()
    test_empresa_sem_dados_todos_nao_identificados()
    test_empresa_com_osm_completo()
    test_tem_canal_identificado_verdadeiro()
    test_tem_canal_identificado_falso()
    test_lista_vazia()
    test_todos_campos_presentes()
    print("\nTodos os testes do enriquecedor_canais passaram.")
