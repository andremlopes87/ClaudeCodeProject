"""
agents/prospeccao/abordabilidade.py — Calcula se e como uma empresa pode ser contatada.

Responsabilidades:
- Determinar se há canal prático de contato direto (telefone ou e-mail)
- Identificar o canal principal e o dado de contato concreto
- Sinalizar empresas sem canal útil para que não subam indevidamente na lista

Regras de abordabilidade:
- Telefone: canal direto e prático → abordavel_agora = True
- E-mail: canal direto → abordavel_agora = True
- Website sem telefone/email: canal indireto, não conta como abordável agora
- Sem nenhum: não é abordável com os dados disponíveis

A abordabilidade é calculada APÓS a priorização para poder influenciar
a ordenação final sem interferir na classificação comercial.
"""

import logging

logger = logging.getLogger(__name__)


def calcular_abordabilidade(empresas: list) -> list:
    """
    Adiciona campos de abordabilidade a cada empresa.

    Deve ser chamado após priorizar_empresas.

    Entrada: lista com classificação comercial e sinais
    Saída: mesma lista com campos de abordabilidade adicionados
    """
    return [_calcular(e) for e in empresas]


def _calcular(empresa: dict) -> dict:
    """Determina canais de contato disponíveis e abordabilidade prática."""
    sinais = empresa.get("sinais", {})
    tem_telefone = sinais.get("tem_telefone", False)
    tem_email = sinais.get("tem_email", False)
    tem_website = sinais.get("tem_website", False)

    # Campos de utilidade dos dados de contato
    empresa["tem_telefone_util"] = tem_telefone
    empresa["tem_email_util"] = tem_email
    empresa["tem_site_util"] = tem_website

    # Abordável agora = tem canal de contato direto (telefone ou e-mail)
    # Website sem telefone/e-mail é canal indireto — não conta como abordável imediato
    abordavel = tem_telefone or tem_email
    empresa["abordavel_agora"] = abordavel

    # Canal sugerido e dado de contato principal
    canal, contato, tipo = _resolver_canal(empresa, tem_telefone, tem_email, tem_website)
    empresa["canal_abordagem_sugerido"] = canal
    empresa["contato_principal"] = contato
    empresa["tipo_contato_principal"] = tipo

    # Motivo quando não é abordável
    if abordavel:
        empresa["motivo_nao_abordavel"] = None
    elif tem_website:
        empresa["motivo_nao_abordavel"] = (
            "Apenas website identificado nos dados públicos. "
            "Sem telefone ou e-mail direto para abordagem imediata."
        )
    else:
        empresa["motivo_nao_abordavel"] = (
            "Nenhum canal de contato direto identificado nos dados públicos do OpenStreetMap."
        )

    return empresa


def _resolver_canal(empresa: dict, tem_telefone: bool, tem_email: bool, tem_website: bool):
    """
    Define canal principal, dado de contato e tipo.

    Prioridade: telefone > e-mail > website (indireto) > nenhum
    """
    if tem_telefone:
        return "telefone", empresa.get("telefone"), "telefone"
    if tem_email:
        return "email", empresa.get("email"), "email"
    if tem_website:
        return "website_contato_indireto", empresa.get("website"), "website"
    return "sem_canal_identificado", None, None
