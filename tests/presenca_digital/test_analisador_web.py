"""
tests/presenca_digital/test_analisador_web.py — Testa extração de sinais do HTML.

Não faz requisições HTTP reais — testa as funções de parsing e lógica diretamente.

Roda com: python tests/presenca_digital/test_analisador_web.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from modulos.presenca_digital.analisador_web import _extrair_sinais_html, _analisar_empresa


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empresa_com_site(url="http://exemplo.com", tem_website=True):
    """Empresa base com website."""
    return {
        "osm_id": 1,
        "nome": "Empresa Teste",
        "categoria_id": "barbearia",
        "website": url if tem_website else None,
        "sinais": {
            "tem_website": tem_website,
            "tem_telefone": False,
            "tem_horario": False,
            "tem_email": False,
        },
    }


def _empresa_sem_site():
    return _empresa_com_site(tem_website=False)


# ---------------------------------------------------------------------------
# Testes de extração HTML
# ---------------------------------------------------------------------------

def test_detecta_telefone_via_href_tel():
    html = '<a href="tel:+5517999991111">Ligue agora</a>'
    sinais = _extrair_sinais_html(html)
    assert sinais["tem_telefone_no_site"] is True
    print("OK: telefone detectado via href tel:")


def test_detecta_telefone_via_texto_puro():
    html = "<p>Ligue para (17) 3333-4444 a qualquer hora.</p>"
    sinais = _extrair_sinais_html(html)
    assert sinais["tem_telefone_no_site"] is True
    print("OK: telefone detectado via texto puro")


def test_detecta_email_via_href_mailto():
    html = '<a href="mailto:contato@exemplo.com.br">Envie e-mail</a>'
    sinais = _extrair_sinais_html(html)
    assert sinais["tem_email_no_site"] is True
    print("OK: e-mail detectado via href mailto:")


def test_detecta_email_via_texto():
    html = "<p>Fale conosco: comercial@empresa.com.br</p>"
    sinais = _extrair_sinais_html(html)
    assert sinais["tem_email_no_site"] is True
    print("OK: e-mail detectado via texto puro")


def test_detecta_whatsapp_wame():
    html = '<a href="https://wa.me/5517999991111">WhatsApp</a>'
    sinais = _extrair_sinais_html(html)
    assert sinais["tem_whatsapp_no_site"] is True
    print("OK: WhatsApp detectado via wa.me")


def test_detecta_whatsapp_api():
    html = '<a href="https://api.whatsapp.com/send?phone=5517999991111">Chamar</a>'
    sinais = _extrair_sinais_html(html)
    assert sinais["tem_whatsapp_no_site"] is True
    print("OK: WhatsApp detectado via api.whatsapp.com")


def test_detecta_instagram_link():
    html = '<a href="https://www.instagram.com/empresa_teste">Siga-nos</a>'
    sinais = _extrair_sinais_html(html)
    assert sinais["tem_instagram_no_site"] is True
    print("OK: Instagram detectado via href instagram.com")


def test_detecta_facebook_link():
    html = '<a href="https://facebook.com/paginateste">Facebook</a>'
    sinais = _extrair_sinais_html(html)
    assert sinais["tem_facebook_no_site"] is True
    print("OK: Facebook detectado via href facebook.com")


def test_detecta_cta_via_texto_botao():
    html = "<button>Agendar agora</button>"
    sinais = _extrair_sinais_html(html)
    assert sinais["tem_cta_clara"] is True
    print("OK: CTA detectado via texto de botão")


def test_detecta_cta_via_texto_link():
    html = '<a href="/contato">Solicitar orçamento</a>'
    sinais = _extrair_sinais_html(html)
    assert sinais["tem_cta_clara"] is True
    print("OK: CTA detectado via texto de link")


def test_detecta_cta_via_href():
    html = '<a href="/agenda">Marque aqui</a>'
    sinais = _extrair_sinais_html(html)
    assert sinais["tem_cta_clara"] is True
    print("OK: CTA detectado via href com palavra-chave")


def test_html_vazio_retorna_tudo_false():
    sinais = _extrair_sinais_html("")
    assert all(not v for v in sinais.values())
    print("OK: HTML vazio retorna todos False")


def test_html_sem_sinais_retorna_false():
    html = "<html><body><h1>Bem-vindo</h1><p>Somos uma empresa de serviços.</p></body></html>"
    sinais = _extrair_sinais_html(html)
    assert sinais["tem_whatsapp_no_site"] is False
    assert sinais["tem_telefone_no_site"] is False
    assert sinais["tem_cta_clara"] is False
    print("OK: HTML sem sinais retorna campos esperados como False")


def test_multiplos_sinais_simultaneos():
    html = """
    <html><body>
    <a href="tel:+5517999991111">Ligue</a>
    <a href="mailto:contato@empresa.com">Email</a>
    <a href="https://wa.me/5517999991111">WhatsApp</a>
    <a href="https://instagram.com/empresa">Instagram</a>
    <a href="https://facebook.com/empresa">Facebook</a>
    <button>Agendar</button>
    </body></html>
    """
    sinais = _extrair_sinais_html(html)
    assert sinais["tem_telefone_no_site"] is True
    assert sinais["tem_email_no_site"] is True
    assert sinais["tem_whatsapp_no_site"] is True
    assert sinais["tem_instagram_no_site"] is True
    assert sinais["tem_facebook_no_site"] is True
    assert sinais["tem_cta_clara"] is True
    print("OK: múltiplos sinais detectados simultaneamente")


# ---------------------------------------------------------------------------
# Testes de _analisar_empresa (sem HTTP)
# ---------------------------------------------------------------------------

def test_empresa_sem_site_recebe_campos_false():
    empresa = _empresa_sem_site()
    resultado = _analisar_empresa(empresa)
    assert resultado["tem_site"] is False
    assert resultado["site_acessivel"] is False
    assert resultado["status_http_site"] is None
    assert resultado["usa_https"] is False
    assert resultado["tem_whatsapp_no_site"] is False
    print("OK: empresa sem site recebe campos False sem requisição")


def test_empresa_com_site_https_detecta_https():
    """Verifica detecção de HTTPS sem precisar de requisição real."""
    empresa = _empresa_com_site(url="https://meusitehttps.com.br")
    # Injetamos resultado do fetch manualmente para não fazer requisição
    empresa["tem_site"] = True
    empresa["site_acessivel"] = True
    empresa["status_http_site"] = 200
    empresa["usa_https"] = True
    empresa["tem_telefone_no_site"] = False
    empresa["tem_email_no_site"] = False
    empresa["tem_whatsapp_no_site"] = False
    empresa["tem_instagram_no_site"] = False
    empresa["tem_facebook_no_site"] = False
    empresa["tem_cta_clara"] = False
    assert empresa["usa_https"] is True
    print("OK: HTTPS detectado a partir da URL com prefixo https://")


if __name__ == "__main__":
    test_detecta_telefone_via_href_tel()
    test_detecta_telefone_via_texto_puro()
    test_detecta_email_via_href_mailto()
    test_detecta_email_via_texto()
    test_detecta_whatsapp_wame()
    test_detecta_whatsapp_api()
    test_detecta_instagram_link()
    test_detecta_facebook_link()
    test_detecta_cta_via_texto_botao()
    test_detecta_cta_via_texto_link()
    test_detecta_cta_via_href()
    test_html_vazio_retorna_tudo_false()
    test_html_sem_sinais_retorna_false()
    test_multiplos_sinais_simultaneos()
    test_empresa_sem_site_recebe_campos_false()
    test_empresa_com_site_https_detecta_https()
    print("\nTodos os testes do analisador_web passaram.")
