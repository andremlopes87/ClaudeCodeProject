"""
modulos/presenca_digital/enriquecedor_canais.py — Consolida canais digitais por empresa.

Para cada empresa, tenta identificar e confirmar os principais canais digitais
a partir de múltiplas fontes, em ordem de confiabilidade:

  1. Campos OSM diretos (website, telefone, email, instagram tag)
  2. Valores reais extraídos do HTML da homepage (pelo analisador_web)
  3. Subpágina /contato ou /contact (busca controlada, apenas se site acessível)

Cada canal gera três campos:
  - {canal}_confirmado : valor concreto (string) ou None
  - origem_{canal}     : de onde o dado veio
  - confianca_{canal}  : alta / media / baixa / nao_identificado

Canais tratados: website, instagram, facebook, whatsapp, email, telefone

Documentação completa: docs/presenca_digital/heuristicas.md
"""

import logging
import urllib.parse

from modulos.presenca_digital.analisador_web import _fetch, _extrair_sinais_html

logger = logging.getLogger(__name__)

_SUBPAGINAS_CONTATO = ["/contato", "/contact"]
_CANAIS = ["website", "instagram", "facebook", "whatsapp", "email", "telefone"]


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def enriquecer_canais(empresas: list) -> list:
    """
    Consolida canais digitais para todas as empresas da lista.

    Entrada: lista de empresas já processadas pelo analisador_web e diagnosticador_presenca
    Saída: mesma lista com campos {canal}_confirmado, origem_{canal}, confianca_{canal} adicionados
    """
    com_site_acessivel = sum(1 for e in empresas if e.get("site_acessivel"))
    logger.info(
        f"Enriquecimento de canais: {len(empresas)} empresas, "
        f"{com_site_acessivel} com site acessivel para busca de subpagina."
    )
    return [_enriquecer(e) for e in empresas]


# ---------------------------------------------------------------------------
# Enriquecimento por empresa
# ---------------------------------------------------------------------------

def _enriquecer(empresa: dict) -> dict:
    """Consolida todos os canais digitais de uma única empresa."""
    sinais_contato = _buscar_contato_subpagina(empresa)

    empresa.update(_canal_website(empresa))
    empresa.update(_canal_instagram(empresa, sinais_contato))
    empresa.update(_canal_facebook(empresa, sinais_contato))
    empresa.update(_canal_whatsapp(empresa, sinais_contato))
    empresa.update(_canal_email(empresa, sinais_contato))
    empresa.update(_canal_telefone(empresa, sinais_contato))

    return empresa


def _buscar_contato_subpagina(empresa: dict) -> dict:
    """
    Tenta buscar sinais em subpáginas de contato do site da empresa.

    Condição: site já confirmado como acessível pelo analisador_web.
    Tenta: /contato e /contact — primeiro que retornar 200 é usado.

    Retorna: dicionário de sinais extraídos (mesmo formato de _extrair_sinais_html)
             ou {} se nenhuma subpágina foi encontrada.
    """
    if not empresa.get("site_acessivel"):
        return {}

    website = (empresa.get("website") or "").strip()
    if not website:
        return {}

    base = _base_url(website)
    nome = empresa.get("nome", "(sem nome)")

    for subpagina in _SUBPAGINAS_CONTATO:
        url = base + subpagina
        try:
            status, html, acessivel = _fetch(url)
            if acessivel and html:
                sinais = _extrair_sinais_html(html)
                logger.debug(f"Subpagina encontrada: {url} para {nome}")
                return sinais
        except Exception as e:
            logger.debug(f"Erro ao buscar subpagina {url}: {type(e).__name__}")

    return {}


def _base_url(url: str) -> str:
    """Extrai scheme + host de uma URL. Ex: 'http://exemplo.com/path' → 'http://exemplo.com'"""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


# ---------------------------------------------------------------------------
# Consolidação por canal
# ---------------------------------------------------------------------------

def _canal_website(empresa: dict) -> dict:
    """
    Website próprio (exclui URLs do Instagram — essas pertencem ao canal instagram).

    Fontes:
    - OSM + site acessível → alta
    - OSM + site inacessível → media
    - OSM tem URL do Instagram → não conta como website
    """
    website = (empresa.get("website") or "").strip()
    eh_instagram = "instagram.com" in website.lower() if website else False

    if not website or eh_instagram:
        return _nao_identificado("website")

    if empresa.get("site_acessivel"):
        return {
            "website_confirmado": website,
            "origem_website": "osm_verificado",
            "confianca_website": "alta",
        }

    return {
        "website_confirmado": website,
        "origem_website": "osm",
        "confianca_website": "media",
    }


def _canal_instagram(empresa: dict, sinais_contato: dict) -> dict:
    """
    Instagram da empresa.

    Fontes (em ordem de prioridade):
    1. Tag OSM explícita (contact:instagram, instagram etc.) → alta
    2. Campo website OSM que É uma URL do Instagram → alta
    3. Link Instagram com URL real extraída do HTML da homepage → media
    4. Link Instagram com URL real extraída da subpágina de contato → media
    5. Sinal booleano apenas (link detectado, URL não capturada) → baixa
    """
    # Fonte 1: tag OSM explícita
    instagram_osm = empresa.get("instagram")
    if instagram_osm:
        return {
            "instagram_confirmado": instagram_osm,
            "origem_instagram": "osm",
            "confianca_instagram": "alta",
        }

    # Fonte 2: website OSM é instagram.com
    website = (empresa.get("website") or "")
    if "instagram.com" in website.lower():
        return {
            "instagram_confirmado": website,
            "origem_instagram": "website_osm",
            "confianca_instagram": "alta",
        }

    # Fonte 3: URL real extraída do HTML do site
    val_site = empresa.get("_val_instagram_site")
    if val_site:
        return {
            "instagram_confirmado": val_site,
            "origem_instagram": "html_website",
            "confianca_instagram": "media",
        }

    # Fonte 4: URL real extraída da subpágina de contato
    val_contato = sinais_contato.get("_val_instagram_site")
    if val_contato:
        return {
            "instagram_confirmado": val_contato,
            "origem_instagram": "html_contato",
            "confianca_instagram": "media",
        }

    # Fonte 5: sinal booleano sem URL capturada
    if empresa.get("tem_instagram_no_site") or sinais_contato.get("tem_instagram_no_site"):
        return {
            "instagram_confirmado": None,
            "origem_instagram": "html_sinal",
            "confianca_instagram": "baixa",
        }

    return _nao_identificado("instagram")


def _canal_facebook(empresa: dict, sinais_contato: dict) -> dict:
    """
    Facebook da empresa.

    Fontes:
    1. URL real extraída do HTML da homepage → media
    2. URL real extraída da subpágina de contato → media
    3. Sinal booleano sem URL → baixa
    """
    val_site = empresa.get("_val_facebook_site")
    if val_site:
        return {
            "facebook_confirmado": val_site,
            "origem_facebook": "html_website",
            "confianca_facebook": "media",
        }

    val_contato = sinais_contato.get("_val_facebook_site")
    if val_contato:
        return {
            "facebook_confirmado": val_contato,
            "origem_facebook": "html_contato",
            "confianca_facebook": "media",
        }

    if empresa.get("tem_facebook_no_site") or sinais_contato.get("tem_facebook_no_site"):
        return {
            "facebook_confirmado": None,
            "origem_facebook": "html_sinal",
            "confianca_facebook": "baixa",
        }

    return _nao_identificado("facebook")


def _canal_whatsapp(empresa: dict, sinais_contato: dict) -> dict:
    """
    WhatsApp da empresa.

    Fontes:
    1. URL wa.me ou api.whatsapp.com extraída do HTML → media
    2. URL extraída da subpágina de contato → media
    3. Sinal booleano sem URL → baixa
    """
    val_site = empresa.get("_val_whatsapp_site")
    if val_site:
        return {
            "whatsapp_confirmado": val_site,
            "origem_whatsapp": "html_website",
            "confianca_whatsapp": "media",
        }

    val_contato = sinais_contato.get("_val_whatsapp_site")
    if val_contato:
        return {
            "whatsapp_confirmado": val_contato,
            "origem_whatsapp": "html_contato",
            "confianca_whatsapp": "media",
        }

    if empresa.get("tem_whatsapp_no_site") or sinais_contato.get("tem_whatsapp_no_site"):
        return {
            "whatsapp_confirmado": None,
            "origem_whatsapp": "html_sinal",
            "confianca_whatsapp": "baixa",
        }

    return _nao_identificado("whatsapp")


def _canal_email(empresa: dict, sinais_contato: dict) -> dict:
    """
    E-mail de contato da empresa.

    Fontes:
    1. Campo OSM email → alta
    2. Valor real extraído de href mailto: no HTML → media
    3. Valor real extraído de mailto: na subpágina de contato → media
    4. Sinal booleano (regex detectou endereço sem href) → baixa
    """
    email_osm = empresa.get("email")
    if email_osm:
        return {
            "email_confirmado": email_osm,
            "origem_email": "osm",
            "confianca_email": "alta",
        }

    val_site = empresa.get("_val_email_site")
    if val_site:
        return {
            "email_confirmado": val_site,
            "origem_email": "html_website",
            "confianca_email": "media",
        }

    val_contato = sinais_contato.get("_val_email_site")
    if val_contato:
        return {
            "email_confirmado": val_contato,
            "origem_email": "html_contato",
            "confianca_email": "media",
        }

    if empresa.get("tem_email_no_site") or sinais_contato.get("tem_email_no_site"):
        return {
            "email_confirmado": None,
            "origem_email": "html_sinal",
            "confianca_email": "baixa",
        }

    return _nao_identificado("email")


def _canal_telefone(empresa: dict, sinais_contato: dict) -> dict:
    """
    Telefone de contato da empresa.

    Fontes:
    1. Campo OSM telefone → alta
    2. Valor real extraído de href tel: no HTML → media
    3. Valor real extraído de tel: na subpágina de contato → media
    4. Sinal booleano (regex detectou número sem href tel:) → baixa
    """
    tel_osm = empresa.get("telefone")
    if tel_osm:
        return {
            "telefone_confirmado": tel_osm,
            "origem_telefone": "osm",
            "confianca_telefone": "alta",
        }

    val_site = empresa.get("_val_tel_site")
    if val_site:
        return {
            "telefone_confirmado": val_site,
            "origem_telefone": "html_website",
            "confianca_telefone": "media",
        }

    val_contato = sinais_contato.get("_val_tel_site")
    if val_contato:
        return {
            "telefone_confirmado": val_contato,
            "origem_telefone": "html_contato",
            "confianca_telefone": "media",
        }

    if empresa.get("tem_telefone_no_site") or sinais_contato.get("tem_telefone_no_site"):
        return {
            "telefone_confirmado": None,
            "origem_telefone": "html_sinal",
            "confianca_telefone": "baixa",
        }

    return _nao_identificado("telefone")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nao_identificado(canal: str) -> dict:
    return {
        f"{canal}_confirmado": None,
        f"origem_{canal}": "nao_identificado",
        f"confianca_{canal}": "nao_identificado",
    }


def tem_canal_identificado(empresa: dict) -> bool:
    """Retorna True se a empresa tem ao menos um canal com confiança definida."""
    return any(
        empresa.get(f"confianca_{c}", "nao_identificado") != "nao_identificado"
        for c in _CANAIS
    )
