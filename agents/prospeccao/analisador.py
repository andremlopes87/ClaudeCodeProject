"""
agents/prospeccao/analisador.py — Aplica heurísticas de presença digital.

Responsabilidades:
- Verificar quais campos de contato/presença digital existem nos dados do OSM
- Calcular um score de 0 a 100 (mais alto = mais presença digital identificada)
- Calcular nível de confiança baseado em quantos campos o OSM tinha
- Adicionar esses campos a cada empresa sem modificar os dados brutos originais

O score é um FILTRO DE PRIORIDADE, não uma verdade absoluta.
A ausência de dados no OSM não significa que a empresa não tem presença digital —
pode simplesmente não estar cadastrada corretamente no mapa.

Documentação completa das heurísticas: docs/heuristicas.md
"""

import logging

logger = logging.getLogger(__name__)

# Peso de cada sinal digital no score final
# Soma total = 100 (score máximo possível)
PESOS = {
    "website": 40,
    "telefone": 30,
    "horario": 20,
    "email": 10,
}

SCORE_MAXIMO = sum(PESOS.values())  # 100


def analisar_empresas(empresas: list) -> list:
    """
    Aplica heurísticas em cada empresa da lista.

    Entrada: lista de empresas padronizadas (saída do buscador)
    Saída: mesma lista com campos 'sinais', 'score_digitalizacao',
           'campos_osm_preenchidos' e 'confianca_diagnostico' adicionados
    """
    return [_analisar_empresa(e) for e in empresas]


def _analisar_empresa(empresa: dict) -> dict:
    """Calcula score e sinais para uma única empresa."""
    sinais = {
        "tem_website": bool(empresa.get("website")),
        "tem_telefone": bool(empresa.get("telefone")),
        "tem_horario": bool(empresa.get("horario")),
        "tem_email": bool(empresa.get("email")),
    }

    score = 0
    if sinais["tem_website"]:
        score += PESOS["website"]
    if sinais["tem_telefone"]:
        score += PESOS["telefone"]
    if sinais["tem_horario"]:
        score += PESOS["horario"]
    if sinais["tem_email"]:
        score += PESOS["email"]

    campos_preenchidos = sum(1 for v in sinais.values() if v)

    empresa["sinais"] = sinais
    empresa["score_digitalizacao"] = score
    empresa["campos_osm_preenchidos"] = campos_preenchidos
    empresa["confianca_diagnostico"] = _calcular_confianca(campos_preenchidos)

    return empresa


def _calcular_confianca(campos_preenchidos: int) -> str:
    """
    Calcula nível de confiança do diagnóstico.

    Mais campos preenchidos no OSM = mais dados para análise = mais confiança.
    Atenção: 'alta' aqui significa apenas que temos mais dados públicos disponíveis,
    não que o diagnóstico é definitivo.

    baixa  → 0 campos: quase nada para analisar
    media  → 1-2 campos: alguns dados disponíveis
    alta   → 3-4 campos: dados relativamente completos nos registros públicos
    """
    if campos_preenchidos >= 3:
        return "alta"
    elif campos_preenchidos >= 1:
        return "media"
    else:
        return "baixa"
