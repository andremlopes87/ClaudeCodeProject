"""
agents/prospeccao/diagnosticador.py — Gera diagnóstico textual para cada empresa.

Responsabilidades:
- Transformar score e sinais em texto de diagnóstico legível
- Usar linguagem cuidadosa que não afirma além do que os dados permitem
- Marcar se a empresa é candidata (score abaixo do limite configurado)
- Adicionar metadados de confiança e origem dos dados

IMPORTANTE: O diagnóstico nunca deve afirmar que uma empresa "não tem site" ou
"não usa tecnologia" — apenas que esses itens não foram identificados nos dados
públicos do OpenStreetMap, o que é diferente.
"""

import logging
from datetime import datetime
from typing import Optional

import config

logger = logging.getLogger(__name__)

OBSERVACAO_PADRAO = (
    "Diagnóstico inicial baseado exclusivamente em dados públicos do OpenStreetMap. "
    "Verificação manual recomendada antes de qualquer abordagem."
)


def diagnosticar_empresas(empresas: list) -> list:
    """
    Gera diagnóstico para cada empresa da lista.

    Entrada: lista com score e sinais (saída do analisador)
    Saída: mesma lista com 'diagnostico', 'e_candidata',
           'observacao_limite_dados' e 'gerado_em' adicionados
    """
    return [_diagnosticar(e) for e in empresas]


def _diagnosticar(empresa: dict) -> dict:
    """Gera diagnóstico completo para uma única empresa."""
    score = empresa.get("score_digitalizacao", 0)
    sinais = empresa.get("sinais", {})
    confianca = empresa.get("confianca_diagnostico", "baixa")
    campos_preenchidos = empresa.get("campos_osm_preenchidos", 0)

    ausentes = _listar_ausentes(sinais)
    presentes = _listar_presentes(sinais)

    diagnostico = _gerar_texto(score, ausentes, presentes, confianca, campos_preenchidos)
    e_candidata = score < config.LIMITE_SCORE_CANDIDATA

    empresa["diagnostico"] = diagnostico
    empresa["e_candidata"] = e_candidata
    empresa["fonte_dados"] = empresa.get("fonte_dados", "OpenStreetMap/Overpass")
    empresa["observacao_limite_dados"] = OBSERVACAO_PADRAO
    empresa["gerado_em"] = datetime.now().isoformat()

    return empresa


def _listar_ausentes(sinais: dict) -> list:
    """Retorna lista legível dos campos de presença digital NÃO encontrados."""
    mapa = {
        "tem_website": "site",
        "tem_telefone": "telefone público",
        "tem_horario": "horário de funcionamento",
        "tem_email": "e-mail de contato",
    }
    return [mapa[k] for k, v in sinais.items() if not v]


def _listar_presentes(sinais: dict) -> list:
    """Retorna lista legível dos campos de presença digital encontrados."""
    mapa = {
        "tem_website": "site",
        "tem_telefone": "telefone público",
        "tem_horario": "horário de funcionamento",
        "tem_email": "e-mail de contato",
    }
    return [mapa[k] for k, v in sinais.items() if v]


def _gerar_texto(
    score: int,
    ausentes: list,
    presentes: list,
    confianca: str,
    campos_preenchidos: int,
) -> str:
    """
    Gera texto de diagnóstico com linguagem cuidadosa.
    Não afirma certezas além do que os dados públicos permitem.
    """
    partes = []

    # Caso sem dados: quase nada no OSM
    if campos_preenchidos == 0:
        partes.append(
            "Dados públicos insuficientes para análise de presença digital. "
            "Nenhuma informação de contato ou presença online foi identificada "
            "nos registros públicos do OpenStreetMap para este estabelecimento"
        )
        if ausentes:
            partes.append(
                f"Itens não encontrados nos dados públicos: {', '.join(ausentes)}"
            )
        return ". ".join(partes) + "."

    # Caso com algum dado
    if ausentes:
        partes.append(
            f"Indícios de baixa presença digital nos dados públicos disponíveis: "
            f"{', '.join(ausentes)} não identificados nos registros do OpenStreetMap"
        )

    if presentes:
        partes.append(
            f"Identificado nos dados públicos: {', '.join(presentes)}"
        )

    # Comentário baseado no score
    if score < 20:
        partes.append(
            "Perfil sugere operação com baixo uso de canais digitais rastreáveis publicamente. "
            "Pode ser candidato a soluções de presença online, agendamento ou atendimento automatizado"
        )
    elif score < config.LIMITE_SCORE_CANDIDATA:
        partes.append(
            "Presença digital parcial nos dados públicos. "
            "Pode haver oportunidade de melhoria em canais digitais ainda não rastreados"
        )
    else:
        partes.append(
            "Presença digital razoável identificada nos dados públicos disponíveis"
        )

    return ". ".join(partes) + "."
