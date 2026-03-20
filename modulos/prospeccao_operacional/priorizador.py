"""
agents/prospeccao/priorizador.py — Calcula prioridade comercial de cada empresa.

Responsabilidades:
- Calcular score_prontidao_ia (oportunidade comercial, 0-100)
- Classificar cada empresa comercialmente
- Gerar prioridade de abordagem e motivo textual
- Ordenar lista por prioridade para o arquivo final

Diferença dos scores:
  score_presenca_digital → mede o que foi encontrado nos dados públicos
  score_prontidao_ia     → mede a oportunidade comercial de abordar esta empresa

A base do score_prontidao_ia é o nome identificado + sinais básicos de organização.
Instagram entra como bônus complementar, não como base, porque raramente
está disponível nos dados públicos do OSM.
"""

import logging

logger = logging.getLogger(__name__)

# Ordem para sorting (menor = mais prioritário)
_ORDEM_PRIORIDADE = {"alta": 0, "media": 1, "baixa": 2, "nula": 3}

# Limiar mínimo de score_prontidao_ia para ser classificada como semi_digital
_LIMIAR_SEMI_DIGITAL = 40

# Limiar de score_presenca_digital para ser considerada "já organizada"
_LIMIAR_DIGITAL_BASICA = 65


def priorizar_empresas(empresas: list) -> list:
    """
    Calcula score_prontidao_ia, classificacao_comercial e motivo para cada empresa.

    Entrada: lista com sinais e score_presenca_digital (saída do analisador)
    Saída: mesma lista com campos de priorização adicionados
    """
    return [_priorizar(e) for e in empresas]


def ordenar_por_prioridade(empresas: list) -> list:
    """
    Ordena empresas para candidatas_priorizadas.json e candidatas_abordaveis.json.

    Critérios (em ordem):
    1. prioridade_abordagem (alta > media > baixa > nula)
    2. abordavel_agora (True primeiro — empresa abordável sobe sobre não-abordável)
    3. score_prontidao_ia (maior primeiro)
    4. campos_osm_preenchidos (maior primeiro — mais dados = mais confiança)

    O critério 2 garante que uma empresa semi_digital abordável venha
    antes de uma semi_digital sem canal de contato identificado.
    """
    return sorted(
        empresas,
        key=lambda e: (
            _ORDEM_PRIORIDADE.get(e.get("prioridade_abordagem", "nula"), 3),
            0 if e.get("abordavel_agora") else 1,
            -e.get("score_prontidao_ia", 0),
            -e.get("campos_osm_preenchidos", 0),
        ),
    )


def _nome_valido(nome: str) -> bool:
    """Um nome é válido se não é vazio e não é o placeholder padrão."""
    return bool(nome) and nome != "(sem nome registrado)"


def _priorizar(empresa: dict) -> dict:
    """Calcula e adiciona todos os campos de priorização para uma empresa."""
    nome = empresa.get("nome", "")
    valido = _nome_valido(nome)
    score_presenca = empresa.get("score_presenca_digital", 0)
    campos = empresa.get("campos_osm_preenchidos", 0)
    sinais = empresa.get("sinais", {})
    tem_instagram = empresa.get("tem_instagram", False)

    score_prontidao = _calcular_prontidao(valido, sinais, score_presenca, tem_instagram)
    classificacao = _classificar(valido, score_presenca, score_prontidao, campos)
    prioridade = _mapear_prioridade(classificacao)
    motivo = _gerar_motivo(valido, sinais, score_presenca, score_prontidao, classificacao, tem_instagram)

    empresa["score_prontidao_ia"] = score_prontidao
    empresa["classificacao_comercial"] = classificacao
    empresa["prioridade_abordagem"] = prioridade
    empresa["motivo_prioridade"] = motivo

    return empresa


def _calcular_prontidao(nome_valido: bool, sinais: dict, score_presenca: int, tem_instagram: bool) -> int:
    """
    Calcula score de oportunidade comercial (0-100).

    Lógica:
    - Nome identificado é a base. Sem nome, score = 0.
    - Sinais básicos de organização digital adicionam pontos.
    - Instagram é bônus complementar (não é base), pois raramente aparece no OSM.
    - Empresa já muito organizada recebe penalidade (menos oportunidade para nós).
    """
    if not nome_valido:
        return 0

    score = 25  # ponto de partida: nome identificado

    # Sinais de organização digital (base principal)
    if sinais.get("tem_telefone"):
        score += 20  # sinal mais valioso: empresa é acessível e atende clientes
    if sinais.get("tem_website"):
        score += 15  # tem presença web, mas pode ter lacunas
    if sinais.get("tem_horario"):
        score += 10  # organização operacional mínima
    if sinais.get("tem_email"):
        score += 5

    # Bônus complementar: Instagram
    # Peso intencional baixo porque raramente está nos dados do OSM
    if tem_instagram:
        score += 5

    # Penalidade: empresa já bem organizada tem menos oportunidade
    if score_presenca >= _LIMIAR_DIGITAL_BASICA:
        score = max(0, score - 20)

    return min(score, 100)


def _classificar(nome_valido: bool, score_presenca: int, score_prontidao: int, campos: int) -> str:
    """
    Classifica a empresa comercialmente com base nos dois scores.

    Ordem de avaliação:
    1. Sem nome → pouco_util (não tem como abordar)
    2. Muito organizada → digital_basica (pouca oportunidade agora)
    3. Nome + sinal digital + score alto → semi_digital_prioritaria (melhor alvo)
    4. Nome mas baixo sinal → analogica (pode ser abordada, mais difícil)
    5. Qualquer outro caso → pouco_util
    """
    if not nome_valido:
        return "pouco_util"

    if score_presenca >= _LIMIAR_DIGITAL_BASICA:
        return "digital_basica"

    # Sweet spot: nome + pelo menos um campo OSM preenchido + score de prontidão alto
    if score_prontidao >= _LIMIAR_SEMI_DIGITAL and campos > 0:
        return "semi_digital_prioritaria"

    # Tem nome mas dados muito pobres ou score baixo
    if score_prontidao >= 25:
        return "analogica"

    return "pouco_util"


def _mapear_prioridade(classificacao: str) -> str:
    return {
        "semi_digital_prioritaria": "alta",
        "analogica": "media",
        "digital_basica": "baixa",
        "pouco_util": "nula",
    }.get(classificacao, "nula")


def _gerar_motivo(
    nome_valido: bool,
    sinais: dict,
    score_presenca: int,
    score_prontidao: int,
    classificacao: str,
    tem_instagram: bool,
) -> str:
    """Gera texto explicativo claro sobre por que a empresa recebeu essa prioridade."""

    if classificacao == "pouco_util":
        if not nome_valido:
            return (
                "Sem nome identificado nos dados públicos. "
                "Abordagem comercial não é prática sem identificação mínima do estabelecimento."
            )
        return "Dados públicos insuficientes para abordagem comercial útil."

    if classificacao == "digital_basica":
        return (
            f"Presença digital relativamente organizada nos dados públicos "
            f"(score de presença: {score_presenca}/100). "
            f"Oportunidade de melhoria é menos evidente nesta fase inicial."
        )

    presentes = _listar_sinais(sinais, tem_instagram, encontrados=True)
    ausentes = _listar_sinais(sinais, tem_instagram, encontrados=False)

    if classificacao == "semi_digital_prioritaria":
        partes = ["Empresa identificada com sinais digitais parciais."]
        if presentes:
            partes.append(f"Identificado nos dados públicos: {', '.join(presentes)}.")
        if ausentes:
            partes.append(f"Lacunas identificadas: {', '.join(ausentes)}.")
        partes.append(
            "Perfil sugere operação ainda pouco estruturada digitalmente. "
            "Boa janela para soluções de presença online, agendamento ou atendimento automatizado."
        )
        return " ".join(partes)

    # analogica
    partes = ["Empresa identificável, mas com baixa presença digital nos dados públicos."]
    if ausentes:
        partes.append(f"Não identificado nos dados públicos: {', '.join(ausentes)}.")
    partes.append(
        "Pode ser abordada comercialmente, mas tende a exigir mais esforço de convencimento."
    )
    return " ".join(partes)


def _listar_sinais(sinais: dict, tem_instagram: bool, encontrados: bool) -> list:
    """Retorna lista legível de sinais presentes ou ausentes."""
    mapa = {
        "tem_website": "site próprio",
        "tem_telefone": "telefone",
        "tem_horario": "horário de funcionamento",
        "tem_email": "e-mail",
    }
    resultado = [label for chave, label in mapa.items() if bool(sinais.get(chave)) == encontrados]

    # Instagram: aparece em "encontrados" se tem, em "ausentes" se não tem
    if encontrados and tem_instagram:
        resultado.append("Instagram")
    elif not encontrados and not tem_instagram:
        resultado.append("Instagram")

    return resultado
