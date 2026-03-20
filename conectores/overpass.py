"""
conectores/overpass.py — Conector com OpenStreetMap via Overpass API.

Este é o único arquivo que faz chamadas externas ao OpenStreetMap.
Para trocar a fonte de dados no futuro (ex: Google Maps API), basta criar
outro conector com a mesma função pública: buscar_por_tag(cidade, tag_chave, tag_valor).
O restante do sistema não precisa mudar.

Fontes usadas:
- Nominatim (OpenStreetMap): geocodificação da cidade → gratuito, sem chave de API
- Overpass API (OpenStreetMap): busca de estabelecimentos → gratuito, sem chave de API
"""

import time
import logging
import requests
from typing import Optional

import config

logger = logging.getLogger(__name__)

FONTE_DADOS = "OpenStreetMap/Overpass"

# Cache de sessão: evita consultar o Nominatim mais de uma vez por cidade
_cache_area_id: dict = {}


def _obter_area_id(cidade: str, pais: str) -> Optional[int]:
    """
    Obtém o OSM area ID da cidade via Nominatim.
    Necessário para fazer queries de área na Overpass API.
    Resultado é cacheado na sessão para evitar chamadas repetidas.
    """
    chave = f"{cidade}|{pais}"
    if chave in _cache_area_id:
        return _cache_area_id[chave]

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": f"{cidade}, {pais}",
        "format": "json",
        "limit": 5,
        "addressdetails": 0,
    }
    # Nominatim exige User-Agent identificado
    headers = {"User-Agent": "PlataformaAgentes/0.1 (uso educacional/pesquisa)"}

    try:
        logger.info(f"Geocodificando '{cidade}' via Nominatim...")
        resp = requests.get(url, params=params, timeout=10, headers=headers)
        resp.raise_for_status()
        resultados = resp.json()

        for r in resultados:
            if r.get("osm_type") == "relation":
                # Fórmula padrão OSM: relation_id + 3.600.000.000 = area_id
                area_id = int(r["osm_id"]) + 3_600_000_000
                logger.info(f"Área encontrada: '{cidade}' → OSM area ID {area_id}")
                _cache_area_id[chave] = area_id
                time.sleep(1)  # respeitar rate limit do Nominatim (1 req/s)
                return area_id

        logger.warning(f"Nenhuma relation OSM encontrada para '{cidade}'. Usando fallback por nome.")

    except requests.exceptions.Timeout:
        logger.warning("Timeout ao consultar Nominatim. Usando fallback por nome.")
    except requests.exceptions.ConnectionError:
        logger.warning("Sem conexão com Nominatim. Usando fallback por nome.")
    except Exception as e:
        logger.warning(f"Erro ao consultar Nominatim: {e}. Usando fallback por nome.")

    _cache_area_id[chave] = None
    return None


def _construir_query(area_id: Optional[int], cidade: str, tag_chave: str, tag_valor: str) -> str:
    """Constrói a query Overpass QL para buscar estabelecimentos."""
    timeout = config.TIMEOUT_REQUISICAO

    if area_id:
        # Método preferido: busca por ID de área (mais preciso)
        return f"""
[out:json][timeout:{timeout}];
area(id:{area_id})->.searchArea;
(
  node["{tag_chave}"="{tag_valor}"](area.searchArea);
  way["{tag_chave}"="{tag_valor}"](area.searchArea);
);
out body center;
"""
    else:
        # Fallback: busca por nome da área (funciona para cidades bem mapeadas no OSM)
        return f"""
[out:json][timeout:{timeout}];
area["name"="{cidade}"]["boundary"="administrative"]->.searchArea;
(
  node["{tag_chave}"="{tag_valor}"](area.searchArea);
  way["{tag_chave}"="{tag_valor}"](area.searchArea);
);
out body center;
"""


def _extrair_endereco(tags: dict) -> Optional[str]:
    """Monta endereço legível a partir das tags OSM, se disponíveis."""
    partes = []
    if tags.get("addr:street"):
        partes.append(tags["addr:street"])
    if tags.get("addr:housenumber"):
        partes.append(tags["addr:housenumber"])
    if tags.get("addr:suburb"):
        partes.append(tags["addr:suburb"])
    return ", ".join(partes) if partes else None


def _extrair_campos(elemento: dict) -> dict:
    """Transforma um elemento bruto da Overpass API em dicionário padronizado."""
    tags = elemento.get("tags", {})

    # Ways têm coordenadas no campo "center"; nodes têm lat/lon direto
    if elemento.get("type") == "way" and "center" in elemento:
        lat = elemento["center"].get("lat")
        lon = elemento["center"].get("lon")
    else:
        lat = elemento.get("lat")
        lon = elemento.get("lon")

    return {
        "osm_id": elemento.get("id"),
        "nome": tags.get("name"),
        "website": (
            tags.get("website")
            or tags.get("url")
            or tags.get("contact:website")
        ),
        "telefone": tags.get("phone") or tags.get("contact:phone"),
        "horario": tags.get("opening_hours"),
        "email": tags.get("email") or tags.get("contact:email"),
        "endereco": _extrair_endereco(tags),
        "lat": lat,
        "lon": lon,
        "fonte_dados": FONTE_DADOS,
    }


def buscar_por_tag(cidade: str, tag_chave: str, tag_valor: str) -> list:
    """
    Busca estabelecimentos no OpenStreetMap por cidade e tag OSM.

    Parâmetros:
        cidade: nome da cidade (ex: "São José do Rio Preto")
        tag_chave: chave da tag OSM (ex: "shop")
        tag_valor: valor da tag OSM (ex: "barber")

    Retorna:
        lista de dicionários com campos padronizados.
        Retorna lista vazia em caso de falha (não lança exceção).

    Nota de arquitetura:
        Esta é a função de integração com OpenStreetMap.
        Para trocar a fonte de dados no futuro, crie outro conector com
        esta mesma assinatura e atualize o buscador.py para usá-lo.
    """
    area_id = _obter_area_id(cidade, config.PAIS)
    query = _construir_query(area_id, cidade, tag_chave, tag_valor)

    for tentativa in range(1, config.MAX_TENTATIVAS + 1):
        try:
            logger.info(
                f"Overpass: {tag_chave}={tag_valor} em '{cidade}' "
                f"(tentativa {tentativa}/{config.MAX_TENTATIVAS})"
            )
            response = requests.post(
                config.OVERPASS_URL,
                data={"data": query},
                timeout=config.TIMEOUT_REQUISICAO,
            )
            response.raise_for_status()
            elementos = response.json().get("elements", [])
            logger.info(f"Retornados {len(elementos)} elementos para {tag_chave}={tag_valor}")

            resultados = [_extrair_campos(e) for e in elementos]
            time.sleep(config.PAUSA_ENTRE_REQUISICOES)
            return resultados

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout na tentativa {tentativa}")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Erro de conexão na tentativa {tentativa}")
        except requests.exceptions.HTTPError as e:
            logger.warning(f"Erro HTTP {e.response.status_code} na tentativa {tentativa}")
        except ValueError as e:
            logger.error(f"Resposta inválida da API: {e}")
            break
        except Exception as e:
            logger.error(f"Erro inesperado: {e}")
            break

        if tentativa < config.MAX_TENTATIVAS:
            pausa = config.PAUSA_ENTRE_REQUISICOES * tentativa
            logger.info(f"Aguardando {pausa}s antes da próxima tentativa...")
            time.sleep(pausa)

    logger.error(
        f"Falha ao buscar {tag_chave}={tag_valor} após {config.MAX_TENTATIVAS} tentativas. "
        f"Retornando lista vazia."
    )
    return []
