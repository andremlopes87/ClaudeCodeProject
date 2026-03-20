"""
agents/prospeccao/analisador.py — Analisa sinais de presença digital de cada empresa.

Responsabilidades:
- Detectar Instagram nos dados disponíveis (tags OSM ou URL do website)
- Calcular score_presenca_digital com base nos 4 sinais principais
- Calcular confiança do diagnóstico com base em quantos campos existiam
- NÃO faz scraping, NÃO chama APIs externas

Regra sobre Instagram:
- Verificado APENAS em duas fontes já disponíveis: tags OSM e campo website
- Se website for uma URL do Instagram, conta como Instagram e NÃO como website próprio
- Ausência de Instagram no resultado NÃO significa que a empresa não tem perfil

Documentação completa das heurísticas: docs/prospeccao_operacional/heuristicas.md
"""

import logging

logger = logging.getLogger(__name__)

# Pontuação por sinal digital (quanto mais alto, mais presença digital identificada)
# Instagram não entra aqui — entra no score_prontidao_ia como bônus
PESOS = {
    "website": 40,
    "telefone": 30,
    "horario": 20,
    "email": 10,
}

SCORE_MAXIMO = sum(PESOS.values())  # 100


def analisar_empresas(empresas: list) -> list:
    """
    Aplica análise de presença digital em cada empresa.

    Entrada: lista de empresas padronizadas (saída do buscador)
    Saída: mesma lista com campos de análise adicionados
    """
    return [_analisar(e) for e in empresas]


def _analisar(empresa: dict) -> dict:
    """Analisa sinais digitais de uma única empresa."""
    instagram_val, instagram_origem = _detectar_instagram(empresa)
    tem_instagram = bool(instagram_val)

    sinais = _calcular_sinais(empresa, instagram_val)
    score = _calcular_score(sinais)
    campos_preenchidos = sum(1 for v in sinais.values() if v)

    empresa["tem_instagram"] = tem_instagram
    empresa["origem_instagram"] = instagram_origem
    empresa["sinais"] = sinais
    empresa["score_presenca_digital"] = score
    empresa["campos_osm_preenchidos"] = campos_preenchidos
    empresa["confianca_diagnostico"] = _calcular_confianca(campos_preenchidos)

    return empresa


def _detectar_instagram(empresa: dict) -> tuple:
    """
    Verifica Instagram usando apenas dados já disponíveis.
    Não faz nenhuma requisição externa.

    Fontes verificadas:
    1. Tags OSM diretas: contact:instagram, instagram, social:instagram
    2. Campo website quando a URL aponta para instagram.com

    Retorna: (valor_encontrado, origem) ou (None, None)
    """
    # Fonte 1: tag OSM explícita (já extraída pelo conector)
    instagram_tag = empresa.get("instagram")
    if instagram_tag:
        return instagram_tag, "tag_osm"

    # Fonte 2: website que É uma URL do Instagram
    website = (empresa.get("website") or "").lower()
    if "instagram.com" in website:
        return empresa.get("website"), "website_url"

    return None, None


def _calcular_sinais(empresa: dict, instagram_detectado) -> dict:
    """
    Calcula sinais de presença digital.

    Regra especial: se o campo 'website' for uma URL do Instagram,
    ele NÃO é contado como website próprio (já está capturado em tem_instagram).
    Isso evita que uma página de Instagram seja contada como site próprio.
    """
    website_bruto = empresa.get("website") or ""
    website_e_instagram = "instagram.com" in website_bruto.lower()

    return {
        "tem_website": bool(website_bruto) and not website_e_instagram,
        "tem_telefone": bool(empresa.get("telefone")),
        "tem_horario": bool(empresa.get("horario")),
        "tem_email": bool(empresa.get("email")),
    }


def _calcular_score(sinais: dict) -> int:
    """Soma os pesos dos sinais presentes. Resultado: 0 a 100."""
    score = 0
    if sinais["tem_website"]:
        score += PESOS["website"]
    if sinais["tem_telefone"]:
        score += PESOS["telefone"]
    if sinais["tem_horario"]:
        score += PESOS["horario"]
    if sinais["tem_email"]:
        score += PESOS["email"]
    return score


def _calcular_confianca(campos_preenchidos: int) -> str:
    """
    Nível de confiança baseado em quantos campos o OSM tinha.
    Mais campos = mais dados para análise = mais confiança no diagnóstico.

    Atenção: mesmo 'alta' aqui é limitado aos dados públicos disponíveis.
    """
    if campos_preenchidos >= 3:
        return "alta"
    elif campos_preenchidos >= 1:
        return "media"
    else:
        return "baixa"
