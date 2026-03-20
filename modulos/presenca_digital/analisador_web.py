"""
modulos/presenca_digital/analisador_web.py — Analisa a presença digital básica via website.

Responsabilidades:
- Verificar se o website registrado nos dados OSM responde
- Extrair sinais do HTML público: telefone, e-mail, WhatsApp, Instagram, Facebook, CTA
- Registrar status HTTP, HTTPS e acessibilidade

Escopo desta versão:
- Apenas websites registrados no OSM (campo sinais["tem_website"] = True)
- Sem análise de anúncios
- Sem JavaScript — apenas HTML estático retornado pelo servidor
- Sem APIs pagas

Estratégia de requisição:
1. Tentar HEAD (timeout curto) para verificar acessibilidade
2. Se HEAD retornar 2xx/3xx, fazer GET para extração de sinais do HTML
3. Se HEAD falhar, tentar GET diretamente
4. Falhar de forma silenciosa e controlada — registrar motivo no log

Documentação completa: docs/presenca_digital/heuristicas.md
"""

import logging
import re
from html.parser import HTMLParser

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

_TIMEOUT_HEAD = 6    # segundos — verificação rápida de acessibilidade
_TIMEOUT_GET = 10    # segundos — extração de conteúdo

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PlataformaAgentes/0.6; "
        "+https://github.com/andremlopes87/ClaudeCodeProject)"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

# Regex de suporte para extração em texto puro
_RE_TELEFONE = re.compile(
    r'(?:\+?55\s?)?'                    # DDI Brasil opcional
    r'(?:\(?\d{2}\)?[\s\-]?)?'         # DDD opcional
    r'(?:9\d{4}|\d{4})[\s\-]?\d{4}'   # número (celular ou fixo)
)
_RE_EMAIL = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'
)
_CTA_TEXTO_CHAVES = {
    "agendar", "agendamento", "agende", "orçamento", "orcamento",
    "reservar", "reserva", "marcar", "solicitar", "pedir",
    "fale conosco", "entre em contato", "contate", "ligar",
    "chamar", "contratar", "comprar", "clique aqui",
}
_CTA_HREF_CHAVES = {
    "agenda", "orcamento", "orçamento", "contato", "wa.me",
    "whatsapp", "reserva", "solicitar",
}


# ---------------------------------------------------------------------------
# Parser de HTML
# ---------------------------------------------------------------------------

class _SiteParser(HTMLParser):
    """
    Parser leve baseado em html.parser da stdlib.

    Extrai sinais de presença digital a partir do HTML estático da página.
    Não executa JavaScript. Não faz requisições adicionais.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tem_telefone = False
        self.tem_email = False
        self.tem_whatsapp = False
        self.tem_instagram = False
        self.tem_facebook = False
        self.tem_cta = False
        self._in_link_or_button = False
        self._accumulated_text: list = []
        # Valores reais extraídos (primeiro encontrado de cada tipo)
        self.valor_tel = None
        self.valor_email = None
        self.valor_whatsapp = None
        self.valor_instagram = None
        self.valor_facebook = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        attrs_dict = dict(attrs)
        href_original = (attrs_dict.get("href") or "").strip()
        href = href_original.lower()

        if tag == "a":
            self._in_link_or_button = True
            # Sinais em href + captura de valores reais
            if href.startswith("tel:"):
                self.tem_telefone = True
                if not self.valor_tel:
                    self.valor_tel = href_original[4:].strip()
            if href.startswith("mailto:"):
                self.tem_email = True
                if not self.valor_email:
                    self.valor_email = href_original[7:].split("?")[0].strip()
            if "wa.me" in href or "api.whatsapp.com" in href or (
                "whatsapp.com" in href and "send" in href
            ):
                self.tem_whatsapp = True
                if not self.valor_whatsapp:
                    self.valor_whatsapp = href_original
            if "instagram.com" in href:
                self.tem_instagram = True
                if not self.valor_instagram:
                    self.valor_instagram = href_original
            if "facebook.com" in href:
                self.tem_facebook = True
                if not self.valor_facebook:
                    self.valor_facebook = href_original
            # CTA via href
            if any(kw in href for kw in _CTA_HREF_CHAVES):
                self.tem_cta = True

        if tag == "button":
            self._in_link_or_button = True

    def handle_data(self, data: str) -> None:
        self._accumulated_text.append(data)
        if self._in_link_or_button:
            data_lower = data.lower().strip()
            if any(kw in data_lower for kw in _CTA_TEXTO_CHAVES):
                self.tem_cta = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("a", "button"):
            self._in_link_or_button = False

    def analisar_texto_completo(self) -> None:
        """
        Aplica regex no texto acumulado para capturar telefone/e-mail
        que aparecem como texto puro (não em href).
        """
        texto = " ".join(self._accumulated_text)
        if not self.tem_telefone and _RE_TELEFONE.search(texto):
            self.tem_telefone = True
        if not self.tem_email and _RE_EMAIL.search(texto):
            self.tem_email = True


# ---------------------------------------------------------------------------
# Fetching HTTP
# ---------------------------------------------------------------------------

def _normalizar_url(url: str) -> str:
    """Garante que a URL tem schema. Adiciona https:// se ausente."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _fetch(url: str) -> tuple:
    """
    Tenta obter o conteúdo do site com estratégia HEAD → GET.

    Retorna: (status_http: int|None, html: str|None, acessivel: bool)
    """
    url_norm = _normalizar_url(url)

    # --- ETAPA 1: HEAD — verificação rápida de acessibilidade ---
    status_head = None
    try:
        r_head = requests.head(
            url_norm,
            timeout=_TIMEOUT_HEAD,
            allow_redirects=True,
            headers=_HEADERS,
        )
        status_head = r_head.status_code
        if status_head >= 400:
            logger.debug(f"HEAD retornou {status_head} para {url_norm}")
            return status_head, None, False
        # Site respondeu — prosseguir para GET
    except requests.exceptions.Timeout:
        logger.debug(f"HEAD timeout em {url_norm} — tentando GET")
    except requests.exceptions.ConnectionError:
        logger.debug(f"HEAD falhou (conexão) em {url_norm} — tentando GET")
    except Exception as e:
        logger.debug(f"HEAD falhou ({type(e).__name__}) em {url_norm} — tentando GET")

    # --- ETAPA 2: GET — extração de conteúdo ---
    try:
        r_get = requests.get(
            url_norm,
            timeout=_TIMEOUT_GET,
            allow_redirects=True,
            headers=_HEADERS,
        )
        status = r_get.status_code
        if status >= 400:
            logger.debug(f"GET retornou {status} para {url_norm}")
            return status, None, False
        html = r_get.text
        return status, html, True
    except requests.exceptions.Timeout:
        logger.info(f"Timeout ao acessar site: {url_norm}")
        return None, None, False
    except requests.exceptions.ConnectionError as e:
        logger.info(f"Falha de conexão: {url_norm} — {type(e).__name__}")
        return None, None, False
    except Exception as e:
        logger.info(f"Erro inesperado ao acessar {url_norm}: {type(e).__name__}: {e}")
        return None, None, False


# ---------------------------------------------------------------------------
# Extração de sinais do HTML
# ---------------------------------------------------------------------------

def _extrair_sinais_html(html: str) -> dict:
    """
    Extrai sinais de presença digital do HTML retornado pelo site.

    Retorna dict com os campos booleanos identificados.
    """
    parser = _SiteParser()
    try:
        parser.feed(html)
        parser.analisar_texto_completo()
    except Exception as e:
        logger.debug(f"Erro ao fazer parse do HTML: {e}")

    return {
        "tem_telefone_no_site": parser.tem_telefone,
        "tem_email_no_site": parser.tem_email,
        "tem_whatsapp_no_site": parser.tem_whatsapp,
        "tem_instagram_no_site": parser.tem_instagram,
        "tem_facebook_no_site": parser.tem_facebook,
        "tem_cta_clara": parser.tem_cta,
        # Valores reais extraídos — usados pelo enriquecedor_canais
        "_val_tel_site": parser.valor_tel,
        "_val_email_site": parser.valor_email,
        "_val_whatsapp_site": parser.valor_whatsapp,
        "_val_instagram_site": parser.valor_instagram,
        "_val_facebook_site": parser.valor_facebook,
    }


# ---------------------------------------------------------------------------
# Análise por empresa
# ---------------------------------------------------------------------------

def _campos_vazios() -> dict:
    """Retorna campos padrão para empresas sem website ou site inacessível."""
    return {
        "tem_telefone_no_site": False,
        "tem_email_no_site": False,
        "tem_whatsapp_no_site": False,
        "tem_instagram_no_site": False,
        "tem_facebook_no_site": False,
        "tem_cta_clara": False,
    }


def _analisar_empresa(empresa: dict) -> dict:
    """
    Analisa a presença digital de uma única empresa via seu website.

    Adiciona todos os campos de análise web à empresa.
    Empresas sem website recebem campos padrão (False) e classificação dados_insuficientes.
    """
    sinais_osm = empresa.get("sinais", {})
    tem_site = bool(sinais_osm.get("tem_website", False))
    url = empresa.get("website", "") or ""

    empresa["tem_site"] = tem_site

    if not tem_site or not url:
        empresa["site_acessivel"] = False
        empresa["status_http_site"] = None
        empresa["usa_https"] = False
        empresa.update(_campos_vazios())
        return empresa

    # Verificar HTTPS antes de normalizar (URL pode já ter schema)
    usa_https = url.strip().lower().startswith("https://") or (
        not url.startswith("http://") and not url.startswith("//")
    )

    status_http, html, acessivel = _fetch(url)

    empresa["site_acessivel"] = acessivel
    empresa["status_http_site"] = status_http
    empresa["usa_https"] = usa_https if acessivel else False

    if acessivel and html:
        sinais_web = _extrair_sinais_html(html)
    else:
        sinais_web = _campos_vazios()

    empresa.update(sinais_web)
    return empresa


# ---------------------------------------------------------------------------
# Ponto de entrada do módulo
# ---------------------------------------------------------------------------

def analisar_presenca_web(empresas: list) -> list:
    """
    Analisa presença digital via website para todas as empresas.

    Empresas com website registrado no OSM: passa por verificação HTTP e parsing.
    Empresas sem website: recebem campos padrão (False) sem requisição.

    Entrada: lista de empresas com sinais calculados (saída do analisador OSM)
    Saída: mesma lista com campos de presença web adicionados
    """
    com_site = sum(1 for e in empresas if e.get("sinais", {}).get("tem_website"))
    logger.info(f"Análise web: {com_site} empresas com website registrado de {len(empresas)} total.")

    resultado = []
    for i, empresa in enumerate(empresas, 1):
        tem_site = empresa.get("sinais", {}).get("tem_website", False)
        nome = empresa.get("nome", "(sem nome)")
        if tem_site:
            url = empresa.get("website", "")
            logger.debug(f"[{i}/{len(empresas)}] Analisando site de {nome}: {url}")
        empresa = _analisar_empresa(empresa)
        resultado.append(empresa)

    analisadas = sum(1 for e in resultado if e.get("site_acessivel"))
    logger.info(f"Análise web concluída: {analisadas} sites acessíveis de {com_site} com website.")
    return resultado
