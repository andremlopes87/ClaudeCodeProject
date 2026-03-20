"""
agents/prospeccao/diagnosticador.py — Gera diagnóstico textual para cada empresa.

Atualizado para usar classificacao_comercial do priorizador.
O diagnóstico é gerado APÓS a priorização para poder refletir a classificação.

IMPORTANTE: O texto nunca afirma além do que os dados permitem.
A ausência de um campo não significa que a empresa não tem aquilo —
significa que não foi identificado nos dados públicos disponíveis.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

_OBSERVACAO_BASE = (
    "Diagnóstico inicial baseado exclusivamente em dados públicos do OpenStreetMap. "
    "Verificação manual recomendada antes de qualquer abordagem."
)

_OBSERVACAO_INSTAGRAM = (
    " Ausência de Instagram neste registro não significa que a empresa não tem perfil — "
    "apenas que não foi identificado em tags OSM ou campo website nos dados disponíveis."
)


def diagnosticar_empresas(empresas: list) -> list:
    """
    Gera diagnóstico textual para cada empresa.

    Deve ser chamado APÓS o priorizador, pois usa classificacao_comercial.

    Entrada: lista com sinais, scores e classificação (saída do priorizador)
    Saída: mesma lista com 'diagnostico', 'e_candidata',
           'observacao_limite_dados' e 'gerado_em' adicionados
    """
    return [_diagnosticar(e) for e in empresas]


def _diagnosticar(empresa: dict) -> dict:
    """Gera diagnóstico completo para uma empresa."""
    classificacao = empresa.get("classificacao_comercial", "pouco_util")
    sinais = empresa.get("sinais", {})
    score_presenca = empresa.get("score_presenca_digital", 0)
    tem_instagram = empresa.get("tem_instagram", False)

    empresa["diagnostico"] = _gerar_texto(classificacao, sinais, score_presenca, tem_instagram)
    empresa["e_candidata"] = classificacao in ("semi_digital_prioritaria", "analogica")
    empresa["observacao_limite_dados"] = _gerar_observacao(tem_instagram)
    empresa["gerado_em"] = datetime.now().isoformat()

    return empresa


def _gerar_texto(classificacao: str, sinais: dict, score_presenca: int, tem_instagram: bool) -> str:
    """Gera texto de diagnóstico adequado à classificação comercial."""
    presentes = _listar(sinais, tem_instagram, encontrados=True)
    ausentes = _listar(sinais, tem_instagram, encontrados=False)

    if classificacao == "pouco_util":
        return (
            "Dados públicos insuficientes para análise útil. "
            "Registro sem identificação ou informações mínimas nos dados do OpenStreetMap."
        )

    if classificacao == "digital_basica":
        partes = [f"Indícios de presença digital relativamente organizada nos dados públicos."]
        if presentes:
            partes.append(f"Identificado: {', '.join(presentes)}.")
        partes.append(
            "Oportunidade de melhoria pode existir, mas não é evidente com os dados disponíveis."
        )
        return " ".join(partes)

    if classificacao == "semi_digital_prioritaria":
        partes = ["Indícios de presença digital parcial nos dados públicos."]
        if presentes:
            partes.append(f"Identificado: {', '.join(presentes)}.")
        if ausentes:
            partes.append(f"Não identificado nos dados públicos: {', '.join(ausentes)}.")
        if tem_instagram:
            partes.append("Presença no Instagram identificada nos dados públicos.")
        partes.append(
            "Perfil compatível com oportunidade de melhoria em presença digital ou automação."
        )
        return " ".join(partes)

    # analogica
    partes = ["Baixa presença digital identificada nos dados públicos."]
    if ausentes:
        partes.append(f"Não identificado: {', '.join(ausentes)}.")
    partes.append(
        "Empresa pode ter presença digital não registrada nos dados públicos. "
        "Verificação manual necessária."
    )
    return " ".join(partes)


def _gerar_observacao(tem_instagram: bool) -> str:
    """Observação sobre limites dos dados, incluindo nota sobre Instagram se necessário."""
    obs = _OBSERVACAO_BASE
    if not tem_instagram:
        obs += _OBSERVACAO_INSTAGRAM
    return obs


def _listar(sinais: dict, tem_instagram: bool, encontrados: bool) -> list:
    """Retorna lista legível de sinais presentes ou ausentes."""
    mapa = {
        "tem_website": "site próprio",
        "tem_telefone": "telefone",
        "tem_horario": "horário de funcionamento",
        "tem_email": "e-mail",
    }
    resultado = [label for chave, label in mapa.items() if bool(sinais.get(chave)) == encontrados]

    if encontrados and tem_instagram:
        resultado.append("Instagram")
    elif not encontrados and not tem_instagram:
        resultado.append("Instagram")

    return resultado
