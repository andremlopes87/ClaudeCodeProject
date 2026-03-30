"""
conectores/google_business.py — Google Business Profile API.

Cria e gerencia perfis no Google Meu Negócio programaticamente.
API gratuita — zero custo por chamada.

Modos:
  dry-run (padrão): zero chamadas externas, resposta simulada realista
  real: OAuth2 service account → Business Profile Management API v1

Autenticação (modo real):
  1. Criar service account no Google Cloud Console
  2. Habilitar APIs: My Business Business Information API, My Business Account Management API
  3. Baixar JSON de credenciais → salvar em credenciais/google_service_account.json
  4. Preencher GOOGLE_BUSINESS_ACCOUNT_ID em .env
  5. Alterar "modo" para "real" em dados/config_google_business.json

Dependência para modo real:
  pip install google-auth google-auth-httplib2 requests

Referência:
  https://developers.google.com/my-business/reference/businessinformation/rest
"""

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger(__name__)

# ─── Configuração ─────────────────────────────────────────────────────────────

_ARQ_CONFIG = config.PASTA_DADOS / "config_google_business.json"

_CONFIG_PADRAO = {
    "modo":             "dry-run",
    "credentials_path": None,
    "account_id":       None,
}

# Scopes necessários para a API
_GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/business.manage",
]

# Endpoints da API
_BASE_INFO    = "https://mybusinessbusinessinformation.googleapis.com/v1"
_BASE_ACCOUNT = "https://mybusiness.googleapis.com/v4"


# ─── Mapeamento de categorias ─────────────────────────────────────────────────

CATEGORIAS_GOOGLE: dict[str, str] = {
    # Beleza e saúde
    "barbearia":            "barber_shop",
    "salao_beleza":         "beauty_salon",
    "clinica_estetica":     "beauty_salon",
    "clinica_saude":        "medical_clinic",
    "academia":             "gym",
    "pet_shop":             "pet_store",
    "farmacia":             "pharmacy",
    # Alimentação
    "restaurante":          "restaurant",
    "lanchonete":           "fast_food_restaurant",
    "padaria":              "bakery",
    # Automotivo
    "oficina_mecanica":     "auto_repair_shop",
    "autopecas":            "auto_parts_store",
    "borracharia":          "tire_shop",
    # Varejo
    "supermercado":         "grocery_store",
    "loja_roupas":          "clothing_store",
    # Serviços
    "eletrica_hidraulica":  "electrician",
    "contabilidade":        "accounting",
    "advocacia":            "lawyer",
    "educacao":             "school",
    # Padrão
    "outro":                "local_business",
}


def _categoria_google(categoria_vetor: str) -> str:
    """Converte categoria Vetor para ID de categoria Google."""
    return CATEGORIAS_GOOGLE.get(categoria_vetor, "local_business")


# ─── I/O de configuração ──────────────────────────────────────────────────────

def _carregar_config() -> dict:
    cfg = dict(_CONFIG_PADRAO)
    if _ARQ_CONFIG.exists():
        try:
            cfg.update(json.loads(_ARQ_CONFIG.read_text(encoding="utf-8")))
        except Exception as _err:
            logger.warning("erro ignorado: %s", _err)
    # Variáveis de ambiente sobrescrevem o arquivo
    if os.environ.get("GOOGLE_BUSINESS_CREDENTIALS_PATH"):
        cfg["credentials_path"] = os.environ["GOOGLE_BUSINESS_CREDENTIALS_PATH"]
    if os.environ.get("GOOGLE_BUSINESS_ACCOUNT_ID"):
        cfg["account_id"] = os.environ["GOOGLE_BUSINESS_ACCOUNT_ID"]
    return cfg


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _id_fake() -> str:
    return f"dry-run-{uuid.uuid4().hex[:12]}"


# ─── Autenticação OAuth2 ──────────────────────────────────────────────────────

def _obter_access_token(credentials_path: str) -> str:
    """
    Obtém access token via OAuth2 service account.
    Requer google-auth: pip install google-auth google-auth-httplib2
    """
    try:
        from google.oauth2.service_account import Credentials
        from google.auth.transport.requests import Request as GoogleRequest

        creds = Credentials.from_service_account_file(credentials_path, scopes=_GOOGLE_SCOPES)
        creds.refresh(GoogleRequest())
        return creds.token

    except ImportError:
        raise RuntimeError(
            "Dependência ausente para modo real. "
            "Execute: pip install google-auth google-auth-httplib2"
        )
    except Exception as e:
        raise RuntimeError(f"Falha ao obter token OAuth2: {e}")


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/json",
    }


# ─── Classe principal ─────────────────────────────────────────────────────────

class GoogleBusinessConnector:
    """
    Conector com Google Business Profile API.

    Uso:
        gb = GoogleBusinessConnector()          # dry-run
        gb = GoogleBusinessConnector("real")    # real (exige credenciais)

    Em dry-run, todos os métodos retornam dados simulados realistas sem
    nenhuma chamada externa. Útil para desenvolvimento e testes.
    """

    def __init__(self, modo: str | None = None):
        cfg = _carregar_config()

        # Resolver modo efetivo
        modo_cfg = cfg.get("modo", "dry-run")
        modo_req = modo if modo is not None else modo_cfg

        # Guardar: se real pedido mas credenciais ausentes → dry-run com aviso
        if modo_req == "real":
            creds_path = cfg.get("credentials_path")
            account_id = cfg.get("account_id")
            if not creds_path or not Path(creds_path).exists():
                logger.warning(
                    "[GoogleBusiness] credentials_path ausente ou arquivo não encontrado. "
                    "Operando em dry-run."
                )
                modo_req = "dry-run"
            elif not account_id:
                logger.warning(
                    "[GoogleBusiness] account_id não configurado. Operando em dry-run."
                )
                modo_req = "dry-run"

        self.modo          = modo_req
        self._cfg          = cfg
        self._credentials  = cfg.get("credentials_path")
        self._account_id   = cfg.get("account_id")
        self._token_cache: Optional[str] = None

        logger.info("[GoogleBusiness] Modo: %s", self.modo)

    def _token(self) -> str:
        """Obtém token OAuth2 (com cache de sessão)."""
        if self._token_cache:
            return self._token_cache
        self._token_cache = _obter_access_token(self._credentials)
        return self._token_cache

    def _invalida_cache_token(self) -> None:
        self._token_cache = None

    # ── buscar_perfil ─────────────────────────────────────────────────────────

    def buscar_perfil(self, nome_empresa: str, endereco: str) -> dict | None:
        """
        Busca se o negócio já tem perfil ativo no Google.

        Em dry-run: retorna None (simula que não existe perfil ainda).
        Em real: pesquisa via googleLocations:search.

        Retorna dict com dados do perfil ou None se não encontrado.
        """
        if self.modo == "dry-run":
            logger.info(
                "[GoogleBusiness] dry-run buscar_perfil: '%s' — simulando nao encontrado",
                nome_empresa,
            )
            return None

        try:
            import requests as req

            token = self._token()
            url   = f"{_BASE_ACCOUNT}/googleLocations:search"
            body  = {
                "query":     f"{nome_empresa} {endereco}",
                "pageSize":  5,
            }
            resp = req.post(url, json=body, headers=_headers(token), timeout=15)
            resp.raise_for_status()

            data = resp.json()
            locais = data.get("googleLocations", [])
            if not locais:
                return None

            # Pegar o mais relevante (primeiro resultado)
            local = locais[0]
            location = local.get("location", {})
            return {
                "perfil_id":   local.get("name", ""),
                "nome":        location.get("locationName", nome_empresa),
                "endereco":    location.get("address", {}).get("addressLines", []),
                "categoria":   location.get("primaryCategory", {}).get("displayName", ""),
                "verificado":  local.get("requestAdminRightsUri") is None,
                "fonte":       "google_business_api",
            }

        except Exception as e:
            logger.error("[GoogleBusiness] Erro em buscar_perfil: %s", e)
            self._invalida_cache_token()
            return None

    # ── criar_perfil ──────────────────────────────────────────────────────────

    def criar_perfil(self, dados: dict) -> dict:
        """
        Cria perfil no Google Meu Negócio.

        dados esperados (vêm do formulário de presença digital):
          nome_negocio, endereco_rua, endereco_numero, endereco_bairro,
          endereco_cidade, endereco_cep, telefone_principal,
          categoria (string Vetor), horario_funcionamento, descricao_curta

        Retorna dict com perfil_id, status e todos os dados enviados.
        """
        self._validar_dados_minimos(dados)

        if self.modo == "dry-run":
            perfil_id = f"locations/{_id_fake()}"
            logger.info(
                "[GoogleBusiness] dry-run criar_perfil: '%s' → %s",
                dados.get("nome_negocio"), perfil_id,
            )
            return {
                "perfil_id":      perfil_id,
                "nome":           dados.get("nome_negocio", ""),
                "status":         "criado",
                "modo":           "dry-run",
                "categoria_google": _categoria_google(dados.get("categoria", "outro")),
                "endereco":       self._montar_endereco(dados),
                "telefone":       dados.get("telefone_principal", ""),
                "horarios":       dados.get("horario_funcionamento", {}),
                "descricao":      dados.get("descricao_curta", ""),
                "criado_em":      _agora(),
                "verificacao_pendente": False,
                "url_perfil":     f"https://maps.google.com/?cid=DRY-RUN-{uuid.uuid4().hex[:8]}",
            }

        try:
            import requests as req

            token      = self._token()
            url        = f"{_BASE_INFO}/{self._account_id}/locations"
            categoria  = _categoria_google(dados.get("categoria", "outro"))
            body       = self._montar_body_perfil(dados, categoria)
            params     = {"requestId": uuid.uuid4().hex}

            resp = req.post(url, json=body, headers=_headers(token), params=params, timeout=20)
            resp.raise_for_status()

            criado = resp.json()
            perfil_id = criado.get("name", "")
            logger.info("[GoogleBusiness] Perfil criado: %s", perfil_id)

            return {
                "perfil_id":      perfil_id,
                "nome":           criado.get("title", dados.get("nome_negocio")),
                "status":         "criado",
                "modo":           "real",
                "categoria_google": categoria,
                "endereco":       self._montar_endereco(dados),
                "telefone":       dados.get("telefone_principal", ""),
                "criado_em":      _agora(),
                "verificacao_pendente": True,
                "url_perfil":     criado.get("metadata", {}).get("mapsUri", ""),
            }

        except Exception as e:
            logger.error("[GoogleBusiness] Erro em criar_perfil: %s", e)
            self._invalida_cache_token()
            raise

    # ── atualizar_perfil ──────────────────────────────────────────────────────

    def atualizar_perfil(self, perfil_id: str, dados: dict) -> dict:
        """
        Atualiza campos específicos de um perfil existente.

        dados: dict com campos a atualizar (nome, telefone, horario, descricao, etc.)
        Apenas campos presentes em dados serão atualizados.
        """
        if self.modo == "dry-run":
            logger.info("[GoogleBusiness] dry-run atualizar_perfil: %s", perfil_id)
            return {
                "perfil_id":   perfil_id,
                "status":      "atualizado",
                "modo":        "dry-run",
                "campos":      list(dados.keys()),
                "atualizado_em": _agora(),
            }

        try:
            import requests as req

            token = self._token()
            url   = f"{_BASE_INFO}/{perfil_id}"

            # Construir update_mask com os campos alterados
            fields, body = self._montar_update(dados)
            params = {"updateMask": ",".join(fields)}

            resp = req.patch(url, json=body, headers=_headers(token), params=params, timeout=15)
            resp.raise_for_status()

            logger.info("[GoogleBusiness] Perfil %s atualizado — campos: %s", perfil_id, fields)
            return {
                "perfil_id":     perfil_id,
                "status":        "atualizado",
                "modo":          "real",
                "campos":        fields,
                "atualizado_em": _agora(),
            }

        except Exception as e:
            logger.error("[GoogleBusiness] Erro em atualizar_perfil: %s", e)
            self._invalida_cache_token()
            raise

    # ── upload_fotos ──────────────────────────────────────────────────────────

    def upload_fotos(self, perfil_id: str, fotos: list) -> list:
        """
        Faz upload de fotos para o perfil.

        fotos: lista de caminhos absolutos ou relativos a PASTA_DADOS/uploads/
        Retorna lista de dicts com {foto, url, status}.
        """
        if not fotos:
            return []

        if self.modo == "dry-run":
            logger.info(
                "[GoogleBusiness] dry-run upload_fotos: %d foto(s) para %s",
                len(fotos), perfil_id,
            )
            return [
                {
                    "foto":   f if isinstance(f, str) else str(f),
                    "url":    f"https://lh3.googleusercontent.com/dry-run/{uuid.uuid4().hex[:16]}",
                    "status": "dry-run",
                    "tipo":   "EXTERIOR" if i == 0 else "INTERIOR",
                }
                for i, f in enumerate(fotos)
            ]

        resultados = []
        try:
            import requests as req

            token = self._token()
            url   = f"{_BASE_ACCOUNT}/{perfil_id}/media"

            for i, foto_path in enumerate(fotos):
                try:
                    caminho = Path(foto_path)
                    if not caminho.is_absolute():
                        caminho = config.PASTA_DADOS / "uploads" / foto_path

                    if not caminho.exists():
                        logger.warning("[GoogleBusiness] Foto não encontrada: %s", foto_path)
                        resultados.append({"foto": str(foto_path), "status": "nao_encontrada"})
                        continue

                    # Tipo de foto: primeira é EXTERIOR, as demais INTERIOR
                    category = "EXTERIOR" if i == 0 else "INTERIOR"
                    body = {
                        "mediaFormat":   "PHOTO",
                        "locationAssociation": {"category": category},
                        "sourceUrl":     "",   # não usado com upload direto
                    }

                    # Upload multipart
                    import mimetypes
                    mime, _ = mimetypes.guess_type(str(caminho))
                    files = {"file": (caminho.name, caminho.read_bytes(), mime or "image/jpeg")}
                    headers_up = {"Authorization": f"Bearer {token}"}
                    resp = req.post(url, json=body, files=files, headers=headers_up, timeout=30)
                    resp.raise_for_status()

                    media = resp.json()
                    resultados.append({
                        "foto":   str(foto_path),
                        "url":    media.get("googleUrl", ""),
                        "status": "enviada",
                        "tipo":   category,
                    })
                    logger.info("[GoogleBusiness] Foto enviada: %s", caminho.name)

                except Exception as e:
                    logger.error("[GoogleBusiness] Erro ao enviar foto %s: %s", foto_path, e)
                    resultados.append({"foto": str(foto_path), "status": f"erro: {e}"})

        except Exception as e:
            logger.error("[GoogleBusiness] Erro em upload_fotos: %s", e)
            self._invalida_cache_token()

        return resultados

    # ── adicionar_link_whatsapp ───────────────────────────────────────────────

    def adicionar_link_whatsapp(self, perfil_id: str, numero: str) -> bool:
        """
        Adiciona link de WhatsApp ao perfil via atributo de URL adicional.
        Número deve estar no formato internacional: 5511912345678 (sem + ou espaços).
        """
        numero_limpo = "".join(c for c in numero if c.isdigit())
        if not numero_limpo:
            return False

        if self.modo == "dry-run":
            logger.info(
                "[GoogleBusiness] dry-run adicionar_link_whatsapp: %s → %s",
                perfil_id, numero_limpo,
            )
            return True

        try:
            import requests as req

            token    = self._token()
            url_wa   = f"https://wa.me/{numero_limpo}"
            dados    = {"website": url_wa}
            resultado = self.atualizar_perfil(perfil_id, dados)
            return resultado.get("status") == "atualizado"

        except Exception as e:
            logger.error("[GoogleBusiness] Erro em adicionar_link_whatsapp: %s", e)
            return False

    # ── verificar_perfil ─────────────────────────────────────────────────────

    def verificar_perfil(self, perfil_id: str) -> dict:
        """
        Verifica status do perfil e quais campos estão preenchidos.

        Retorna:
          status: "ativo" | "suspenso" | "pendente_verificacao" | "nao_encontrado" | "dry-run"
          campos_ok: lista de campos preenchidos
          campos_faltando: lista de campos importantes não preenchidos
          score_completude: 0-100
        """
        if self.modo == "dry-run":
            logger.info("[GoogleBusiness] dry-run verificar_perfil: %s", perfil_id)
            return {
                "perfil_id":         perfil_id,
                "status":            "dry-run",
                "modo":              "dry-run",
                "campos_ok":         ["nome", "endereco", "categoria", "telefone", "horarios"],
                "campos_faltando":   ["fotos", "descricao", "site"],
                "score_completude":  60,
                "verificado":        False,
                "verificado_em":     None,
                "checado_em":        _agora(),
            }

        try:
            import requests as req

            token = self._token()
            url   = f"{_BASE_INFO}/{perfil_id}"
            resp  = req.get(url, headers=_headers(token), timeout=15)

            if resp.status_code == 404:
                return {"perfil_id": perfil_id, "status": "nao_encontrado", "score_completude": 0}

            resp.raise_for_status()
            local = resp.json()

            campos_ok      = []
            campos_faltando = []

            checks = [
                (local.get("title"),                      "nome"),
                (local.get("storefrontAddress"),          "endereco"),
                (local.get("primaryCategory"),            "categoria"),
                (local.get("phoneNumbers"),               "telefone"),
                (local.get("regularHours"),               "horarios"),
                (local.get("profile", {}).get("description"), "descricao"),
                (local.get("websiteUri"),                 "site"),
                (local.get("metadata", {}).get("mapsUri"), "link_maps"),
            ]
            for valor, campo in checks:
                (campos_ok if valor else campos_faltando).append(campo)

            score = int(100 * len(campos_ok) / len(checks)) if checks else 0
            meta  = local.get("metadata", {})

            return {
                "perfil_id":        perfil_id,
                "status":           "ativo" if meta.get("mapsUri") else "pendente_verificacao",
                "modo":             "real",
                "campos_ok":        campos_ok,
                "campos_faltando":  campos_faltando,
                "score_completude": score,
                "verificado":       meta.get("hasGoogleUpdated", False),
                "url_perfil":       meta.get("mapsUri", ""),
                "checado_em":       _agora(),
            }

        except Exception as e:
            logger.error("[GoogleBusiness] Erro em verificar_perfil: %s", e)
            self._invalida_cache_token()
            return {"perfil_id": perfil_id, "status": "erro", "detalhe": str(e), "score_completude": 0}

    # ── obter_metricas ────────────────────────────────────────────────────────

    def obter_metricas(self, perfil_id: str) -> dict:
        """
        Obtém métricas do perfil para relatório mensal.

        Retorna:
          visualizacoes_busca: impressões na busca Google
          visualizacoes_maps: impressões no Google Maps
          cliques_site: cliques para o site
          ligacoes: cliques no botão de ligar
          rotas: solicitações de rota
          periodo: últimos 30 dias
        """
        if self.modo == "dry-run":
            logger.info("[GoogleBusiness] dry-run obter_metricas: %s", perfil_id)
            import random
            r = random.Random(perfil_id)  # seed determinístico pelo ID
            return {
                "perfil_id":             perfil_id,
                "modo":                  "dry-run",
                "periodo_dias":          30,
                "visualizacoes_busca":   r.randint(120, 800),
                "visualizacoes_maps":    r.randint(60,  400),
                "cliques_site":          r.randint(8,   80),
                "ligacoes":              r.randint(5,   60),
                "rotas":                 r.randint(10,  100),
                "fotos_visualizadas":    r.randint(50,  300),
                "consultas_top": [
                    "barbearia perto de mim",
                    "barbearia aberta agora",
                    "corte de cabelo masculino",
                ],
                "coletado_em": _agora(),
            }

        try:
            import requests as req

            token = self._token()
            # Business Profile Performance API
            url   = f"https://businessprofileperformance.googleapis.com/v1/{perfil_id}:fetchMultiDailyMetricsTimeSeries"
            body  = {
                "dailyMetrics": [
                    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
                    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
                    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
                    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
                    "CALL_CLICKS",
                    "WEBSITE_CLICKS",
                    "BUSINESS_DIRECTION_REQUESTS",
                    "BUSINESS_BOOKINGS",
                ],
                "dailyRange": {
                    "startDate": {"year": datetime.now().year,
                                  "month": datetime.now().month - 1 or 12,
                                  "day": 1},
                    "endDate":   {"year": datetime.now().year,
                                  "month": datetime.now().month,
                                  "day": datetime.now().day},
                },
            }

            resp = req.post(url, json=body, headers=_headers(token), timeout=20)
            resp.raise_for_status()
            raw = resp.json()

            # Agregar séries temporais por métrica
            agregado: dict[str, int] = {}
            for serie in raw.get("multiDailyMetricTimeSeries", []):
                for ts in serie.get("dailyMetricTimeSeries", []):
                    metrica = ts.get("dailyMetric", "")
                    total   = sum(
                        int(p.get("value", 0))
                        for p in ts.get("timeSeries", {}).get("datedValues", [])
                    )
                    agregado[metrica] = agregado.get(metrica, 0) + total

            return {
                "perfil_id":           perfil_id,
                "modo":                "real",
                "periodo_dias":        30,
                "visualizacoes_busca": (
                    agregado.get("BUSINESS_IMPRESSIONS_DESKTOP_SEARCH", 0)
                    + agregado.get("BUSINESS_IMPRESSIONS_MOBILE_SEARCH", 0)
                ),
                "visualizacoes_maps":  (
                    agregado.get("BUSINESS_IMPRESSIONS_DESKTOP_MAPS", 0)
                    + agregado.get("BUSINESS_IMPRESSIONS_MOBILE_MAPS", 0)
                ),
                "cliques_site":        agregado.get("WEBSITE_CLICKS", 0),
                "ligacoes":            agregado.get("CALL_CLICKS", 0),
                "rotas":               agregado.get("BUSINESS_DIRECTION_REQUESTS", 0),
                "agendamentos":        agregado.get("BUSINESS_BOOKINGS", 0),
                "coletado_em":         _agora(),
            }

        except Exception as e:
            logger.error("[GoogleBusiness] Erro em obter_metricas: %s", e)
            self._invalida_cache_token()
            return {"perfil_id": perfil_id, "status": "erro", "detalhe": str(e)}

    # ── Helpers internos ──────────────────────────────────────────────────────

    @staticmethod
    def _validar_dados_minimos(dados: dict) -> None:
        """Garante campos obrigatórios antes de criar perfil."""
        obrigatorios = ["nome_negocio", "endereco_cidade"]
        faltando = [c for c in obrigatorios if not dados.get(c)]
        if faltando:
            raise ValueError(f"Dados incompletos para criar perfil. Faltando: {faltando}")

    @staticmethod
    def _montar_endereco(dados: dict) -> str:
        """Monta string de endereço legível."""
        partes = []
        if dados.get("endereco_rua"):
            partes.append(dados["endereco_rua"])
            if dados.get("endereco_numero"):
                partes[-1] += f", {dados['endereco_numero']}"
        if dados.get("endereco_bairro"):
            partes.append(dados["endereco_bairro"])
        if dados.get("endereco_cidade"):
            partes.append(dados["endereco_cidade"])
        return " — ".join(partes)

    @staticmethod
    def _montar_body_perfil(dados: dict, categoria: str) -> dict:
        """Monta body JSON para criar/atualizar perfil na API."""
        body: dict = {
            "title":           dados.get("nome_negocio", ""),
            "primaryCategory": {"categoryId": categoria},
            "storefrontAddress": {
                "addressLines": [
                    f"{dados.get('endereco_rua', '')} {dados.get('endereco_numero', '')}".strip(),
                    dados.get("endereco_bairro", ""),
                ],
                "locality":    dados.get("endereco_cidade", ""),
                "postalCode":  dados.get("endereco_cep", ""),
                "regionCode":  "BR",
            },
        }

        if dados.get("telefone_principal"):
            body["phoneNumbers"] = {
                "primaryPhone": dados["telefone_principal"],
            }

        if dados.get("descricao_curta"):
            body["profile"] = {"description": dados["descricao_curta"]}

        if dados.get("horario_funcionamento"):
            body["regularHours"] = {"periods": _converter_horarios(dados["horario_funcionamento"])}

        return body

    @staticmethod
    def _montar_update(dados: dict) -> tuple[list, dict]:
        """Retorna (update_mask_fields, body) para PATCH parcial."""
        fields = []
        body: dict = {}

        mapeamento = {
            "nome":      ("title",       "title"),
            "telefone":  ("phoneNumbers.primaryPhone", "phoneNumbers.primaryPhone"),
            "website":   ("websiteUri",  "websiteUri"),
            "descricao": ("profile.description", "profile.description"),
        }

        for campo_vetor, (field_api, _) in mapeamento.items():
            valor = dados.get(campo_vetor) or dados.get(
                {"nome": "nome_negocio", "telefone": "telefone_principal"}.get(campo_vetor, campo_vetor)
            )
            if valor:
                fields.append(field_api)
                # Montar body aninhado
                parts = field_api.split(".")
                ref = body
                for p in parts[:-1]:
                    ref = ref.setdefault(p, {})
                ref[parts[-1]] = valor

        if dados.get("horario_funcionamento"):
            fields.append("regularHours")
            body["regularHours"] = {"periods": _converter_horarios(dados["horario_funcionamento"])}

        return fields, body


# ─── Conversores internos ──────────────────────────────────────────────────────

_DIA_GOOGLE = {
    "seg": "MONDAY", "ter": "TUESDAY", "qua": "WEDNESDAY",
    "qui": "THURSDAY", "sex": "FRIDAY", "sab": "SATURDAY", "dom": "SUNDAY",
}


def _converter_horarios(horarios: dict) -> list:
    """Converte horário_funcionamento (formato formulário) para periods da API."""
    periods = []
    for dia, h in horarios.items():
        if h.get("fechado"):
            continue
        abertura   = h.get("abertura",   "08:00")
        fechamento = h.get("fechamento", "18:00")
        try:
            ah, am = abertura.split(":")
            fh, fm = fechamento.split(":")
        except (ValueError, AttributeError):
            continue
        periods.append({
            "openDay":   _DIA_GOOGLE.get(dia, "MONDAY"),
            "closeDay":  _DIA_GOOGLE.get(dia, "MONDAY"),
            "openTime":  {"hours": int(ah), "minutes": int(am)},
            "closeTime": {"hours": int(fh), "minutes": int(fm)},
        })
    return periods


# ─── Factory function ─────────────────────────────────────────────────────────

def obter_conector(modo: str | None = None) -> GoogleBusinessConnector:
    """Retorna instância configurada do conector."""
    return GoogleBusinessConnector(modo)


# ─── Execução direta (diagnóstico) ────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    modo = sys.argv[1] if len(sys.argv) > 1 else "dry-run"
    print(f"\nGoogle Business Profile — diagnostico modo={modo}\n{'='*50}")

    gb = GoogleBusinessConnector(modo)
    print(f"Modo efetivo: {gb.modo}")

    # buscar_perfil
    print("\n[1] buscar_perfil...")
    r = gb.buscar_perfil("Barbearia do Carlos", "Rua das Flores, 123, Sao Paulo")
    print(f"    Resultado: {r}")

    # criar_perfil
    print("\n[2] criar_perfil...")
    dados_teste = {
        "nome_negocio":       "Barbearia do Carlos",
        "categoria":          "barbearia",
        "endereco_rua":       "Rua das Flores",
        "endereco_numero":    "123",
        "endereco_bairro":    "Centro",
        "endereco_cidade":    "Sao Paulo",
        "endereco_cep":       "01000-000",
        "telefone_principal": "(11) 91234-5678",
        "descricao_curta":    "Barbearia no centro com atendimento de qualidade.",
        "horario_funcionamento": {
            "seg": {"fechado": False, "abertura": "08:00", "fechamento": "18:00"},
            "ter": {"fechado": False, "abertura": "08:00", "fechamento": "18:00"},
            "qua": {"fechado": False, "abertura": "08:00", "fechamento": "18:00"},
            "qui": {"fechado": False, "abertura": "08:00", "fechamento": "18:00"},
            "sex": {"fechado": False, "abertura": "08:00", "fechamento": "18:00"},
            "sab": {"fechado": False, "abertura": "08:00", "fechamento": "14:00"},
            "dom": {"fechado": True,  "abertura": "",       "fechamento": ""},
        },
    }
    perfil = gb.criar_perfil(dados_teste)
    perfil_id = perfil["perfil_id"]
    print(f"    perfil_id: {perfil_id}")
    print(f"    status: {perfil['status']}")

    # upload_fotos
    print("\n[3] upload_fotos...")
    fotos = gb.upload_fotos(perfil_id, ["foto_fachada.jpg", "foto_interior.jpg"])
    print(f"    {len(fotos)} foto(s): {[f['status'] for f in fotos]}")

    # adicionar_link_whatsapp
    print("\n[4] adicionar_link_whatsapp...")
    ok = gb.adicionar_link_whatsapp(perfil_id, "(11) 91234-5678")
    print(f"    ok={ok}")

    # verificar_perfil
    print("\n[5] verificar_perfil...")
    status = gb.verificar_perfil(perfil_id)
    print(f"    status={status['status']} score={status['score_completude']}%")
    print(f"    campos_ok: {status['campos_ok']}")
    print(f"    campos_faltando: {status['campos_faltando']}")

    # obter_metricas
    print("\n[6] obter_metricas...")
    m = gb.obter_metricas(perfil_id)
    print(f"    buscas={m.get('visualizacoes_busca')} maps={m.get('visualizacoes_maps')}")
    print(f"    ligacoes={m.get('ligacoes')} rotas={m.get('rotas')}")

    print(f"\n{'='*50}")
    print("Diagnostico concluido. Todos os metodos responderam.")
