"""
agents/prospeccao/buscador.py — Orquestra a busca de empresas em todas as categorias.

Responsabilidades:
- Iterar sobre todas as categorias configuradas
- Chamar o conector (overpass.py) para cada tag OSM
- Eliminar duplicatas (mesma empresa pode aparecer em tags diferentes)
- Padronizar a estrutura de dados de saída

Entrada: nenhuma (lê configuração de config.py)
Saída: lista de empresas com campos padronizados
"""

import logging
from conectores.overpass import buscar_por_tag
import config

logger = logging.getLogger(__name__)


def buscar_empresas() -> list:
    """
    Busca empresas em todas as categorias configuradas em config.CATEGORIAS.
    Remove duplicatas por OSM ID e padroniza a estrutura de cada empresa.

    Retorna:
        lista de dicionários com campos padronizados
    """
    todas = []
    ids_vistos = set()

    for categoria_id, lista_tags in config.CATEGORIAS.items():
        nome_categoria = config.NOMES_CATEGORIAS.get(categoria_id, categoria_id)
        logger.info(f"Buscando: {nome_categoria}")

        for tags_dict in lista_tags:
            for tag_chave, tag_valor in tags_dict.items():
                resultados = buscar_por_tag(config.CIDADE, tag_chave, tag_valor)

                for empresa in resultados:
                    osm_id = empresa.get("osm_id")

                    # Remove duplicatas: mesmo estabelecimento pode aparecer
                    # em múltiplas tags (ex: hairdresser e beauty)
                    if osm_id is not None:
                        if osm_id in ids_vistos:
                            continue
                        ids_vistos.add(osm_id)

                    todas.append(_padronizar(empresa, categoria_id, nome_categoria))

    logger.info(f"Total de empresas únicas encontradas: {len(todas)}")
    return todas


def buscar_por_grupo(grupo_id: str, cidade: str = None) -> list:
    """
    Busca empresas de um grupo específico de GRUPOS_CATEGORIAS.

    Útil para prospecção segmentada por segmento de mercado.
    Se cidade não for fornecida, usa config.CIDADE.

    Retorna:
        lista de dicionários com campos padronizados
    """
    cidade_alvo = cidade or config.CIDADE
    grupo_dados = config.GRUPOS_CATEGORIAS.get(grupo_id)
    if not grupo_dados:
        logger.warning(f"Grupo '{grupo_id}' não encontrado em GRUPOS_CATEGORIAS.")
        return []

    nome_grupo = grupo_dados["nome_grupo"]
    lista_tags = grupo_dados["tags_osm"]

    todas = []
    ids_vistos = set()

    logger.info(f"Buscando grupo: {nome_grupo} em {cidade_alvo}")

    for tags_dict in lista_tags:
        for tag_chave, tag_valor in tags_dict.items():
            categoria_id = tag_valor.replace(" ", "_")
            nome_categoria = config.NOMES_CATEGORIAS.get(categoria_id, nome_grupo)
            resultados = buscar_por_tag(cidade_alvo, tag_chave, tag_valor)

            for empresa in resultados:
                osm_id = empresa.get("osm_id")
                if osm_id is not None:
                    if osm_id in ids_vistos:
                        continue
                    ids_vistos.add(osm_id)

                todas.append(_padronizar(empresa, categoria_id, nome_categoria))

    logger.info(f"  {nome_grupo}: {len(todas)} empresas únicas encontradas.")
    return todas


def _padronizar(empresa: dict, categoria_id: str, nome_categoria: str) -> dict:
    """
    Garante que todos os campos necessários existam no dicionário,
    independente do que o conector retornou.
    Campos ausentes ficam como None — nunca como KeyError.
    """
    return {
        "osm_id": empresa.get("osm_id"),
        "nome": empresa.get("nome") or "(sem nome registrado)",
        "categoria": nome_categoria,
        "categoria_id": categoria_id,
        "cidade": config.CIDADE,
        "website": empresa.get("website"),
        "telefone": empresa.get("telefone"),
        "horario": empresa.get("horario"),
        "email": empresa.get("email"),
        "instagram": empresa.get("instagram"),
        "endereco": empresa.get("endereco"),
        "lat": empresa.get("lat"),
        "lon": empresa.get("lon"),
        "fonte_dados": empresa.get("fonte_dados", "OpenStreetMap/Overpass"),
    }
