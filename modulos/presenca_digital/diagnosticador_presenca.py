"""
modulos/presenca_digital/diagnosticador_presenca.py — Classifica e diagnostica presença digital.

Responsabilidades:
- Calcular score_presenca_web com base nos sinais do site
- Classificar o nível de presença digital do site
- Gerar diagnóstico curto e útil por empresa
- Identificar a principal oportunidade de melhoria de marketing

Deve ser chamado APÓS analisar_presenca_web, que adiciona os campos de sinais web.

Documentação completa: docs/presenca_digital/heuristicas.md
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pesos para score_presenca_web (0-100)
# ---------------------------------------------------------------------------

_PESOS_WEB = {
    "site_acessivel": 20,       # base: sem isso, nada mais importa
    "usa_https": 10,            # credibilidade e SEO
    "tem_telefone_no_site": 20, # contato direto mais valioso
    "tem_email_no_site": 15,    # alternativa de contato
    "tem_whatsapp_no_site": 15, # canal preferido no Brasil
    "tem_instagram_no_site": 10,# presença em redes sociais
    "tem_facebook_no_site": 5,  # canal adicional
    "tem_cta_clara": 5,         # facilidade de conversão
}
# Total máximo: 100


# ---------------------------------------------------------------------------
# Classificação por score
# ---------------------------------------------------------------------------

def _classificar(score: int, acessivel: bool) -> str:
    """
    Classifica o nível de presença digital com base no score.

    Classificações:
    - dados_insuficientes: site não acessível ou sem website
    - presenca_fraca: acessível mas sem elementos de contato ou conversão
    - presenca_basica: tem 1-2 elementos de contato
    - presenca_razoavel: bem estruturado, falta pouco
    - presenca_boa: site completo e organizado
    """
    if not acessivel:
        return "dados_insuficientes"
    if score >= 76:
        return "presenca_boa"
    if score >= 56:
        return "presenca_razoavel"
    if score >= 36:
        return "presenca_basica"
    return "presenca_fraca"


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------

def _calcular_score(empresa: dict) -> int:
    """Calcula score_presenca_web somando pesos dos sinais presentes."""
    score = 0
    for campo, peso in _PESOS_WEB.items():
        if empresa.get(campo):
            score += peso
    return min(score, 100)


# ---------------------------------------------------------------------------
# Oportunidade de marketing
# ---------------------------------------------------------------------------

def _oportunidade_marketing(empresa: dict) -> str:
    """
    Identifica a principal oportunidade de melhoria de marketing digital.

    Prioriza lacunas com maior impacto comercial, na ordem:
    site inacessível → WhatsApp → telefone → CTA → e-mail → HTTPS → Instagram → Facebook
    """
    if not empresa.get("site_acessivel"):
        url = empresa.get("website", "")
        if url:
            return "Verificar disponibilidade do site — não respondeu na análise"
        return "Criar site próprio para ter presença digital mínima"

    # Lacunas em ordem de impacto
    if not empresa.get("tem_whatsapp_no_site"):
        return "Adicionar botão de WhatsApp para facilitar contato direto com clientes"
    if not empresa.get("tem_telefone_no_site"):
        return "Incluir número de telefone visível no site para contato imediato"
    if not empresa.get("tem_cta_clara"):
        return "Adicionar chamada clara para ação (agendar, solicitar orçamento ou falar no WhatsApp)"
    if not empresa.get("tem_email_no_site"):
        return "Incluir e-mail de contato visível no site"
    if not empresa.get("usa_https"):
        return "Migrar site para HTTPS para mais credibilidade e melhor posicionamento no Google"
    if not empresa.get("tem_instagram_no_site"):
        return "Adicionar link para o perfil no Instagram para aumentar alcance"
    if not empresa.get("tem_facebook_no_site"):
        return "Adicionar link para a página no Facebook"
    return "Site bem estruturado — focar em SEO local e conteúdo atualizado para mais visibilidade"


# ---------------------------------------------------------------------------
# Diagnóstico textual
# ---------------------------------------------------------------------------

def _diagnostico(empresa: dict, score: int, classificacao: str) -> str:
    """Gera diagnóstico curto e direto sobre a presença digital do site."""
    nome = empresa.get("nome", "o estabelecimento")
    url = empresa.get("website", "") or ""

    if not empresa.get("tem_site"):
        return (
            f"{nome} não tem website registrado nos dados públicos. "
            f"Não foi possível analisar a presença digital via site."
        )

    if not empresa.get("site_acessivel"):
        status = empresa.get("status_http_site")
        status_txt = f" (HTTP {status})" if status else " (sem resposta)"
        return (
            f"Site de {nome}{status_txt} não respondeu durante a análise. "
            f"Pode estar temporariamente fora do ar ou com problema técnico."
        )

    # Site acessível — descrever o que foi encontrado e o que falta
    encontrados = []
    if empresa.get("tem_telefone_no_site"):
        encontrados.append("telefone")
    if empresa.get("tem_email_no_site"):
        encontrados.append("e-mail")
    if empresa.get("tem_whatsapp_no_site"):
        encontrados.append("WhatsApp")
    if empresa.get("tem_instagram_no_site"):
        encontrados.append("link para Instagram")
    if empresa.get("tem_facebook_no_site"):
        encontrados.append("link para Facebook")
    if empresa.get("tem_cta_clara"):
        encontrados.append("chamada para ação")
    if empresa.get("usa_https"):
        encontrados.append("HTTPS")

    ausentes = []
    if not empresa.get("tem_telefone_no_site"):
        ausentes.append("telefone")
    if not empresa.get("tem_whatsapp_no_site"):
        ausentes.append("WhatsApp")
    if not empresa.get("tem_cta_clara"):
        ausentes.append("chamada para ação")
    if not empresa.get("tem_email_no_site"):
        ausentes.append("e-mail")
    if not empresa.get("usa_https"):
        ausentes.append("HTTPS")

    partes = [f"Site de {nome} acessível (score de presença web: {score}/100)."]
    if encontrados:
        partes.append(f"Identificado: {', '.join(encontrados)}.")
    if ausentes:
        partes.append(f"Não identificado: {', '.join(ausentes)}.")
    partes.append(f"Nível: {classificacao.replace('_', ' ')}.")
    return " ".join(partes)


# ---------------------------------------------------------------------------
# Confiança do diagnóstico
# ---------------------------------------------------------------------------

def _confianca(empresa: dict) -> str:
    """
    Nível de confiança do diagnóstico de presença digital.

    - alta: site acessível e HTML parseado com sucesso
    - baixa: site inacessível (dados limitados)
    - sem_dados: empresa sem website nos dados públicos
    """
    if not empresa.get("tem_site"):
        return "sem_dados"
    if empresa.get("site_acessivel"):
        return "alta"
    return "baixa"


def _observacao_limite(empresa: dict) -> str:
    """Nota sobre limitações da análise para esta empresa."""
    if not empresa.get("tem_site"):
        return (
            "Empresa sem website registrado nos dados públicos do OpenStreetMap. "
            "Análise web não foi possível nesta execução."
        )
    if not empresa.get("site_acessivel"):
        return (
            "Site registrado mas não respondeu durante a análise. "
            "Resultado pode ser diferente em outra tentativa. "
            "Verificar manualmente se o site está no ar."
        )
    return (
        "Análise baseada em verificação simples do HTML público. "
        "Conteúdo dinâmico (JavaScript), anúncios e redes sociais não foram analisados. "
        "Ausência de sinal não garante que o elemento não existe no site."
    )


# ---------------------------------------------------------------------------
# Ponto de entrada do módulo
# ---------------------------------------------------------------------------

def diagnosticar_presenca(empresas: list) -> list:
    """
    Calcula score, classifica e gera diagnóstico de presença digital para cada empresa.

    Deve ser chamado após analisar_presenca_web.

    Entrada: lista de empresas com campos de análise web adicionados
    Saída: mesma lista com campos de diagnóstico adicionados
    """
    return [_diagnosticar(e) for e in empresas]


def _diagnosticar(empresa: dict) -> dict:
    """Adiciona todos os campos de diagnóstico de presença digital para uma empresa."""
    score = _calcular_score(empresa)
    acessivel = bool(empresa.get("site_acessivel"))
    classificacao = _classificar(score, acessivel)

    empresa["score_presenca_web"] = score
    empresa["classificacao_presenca_web"] = classificacao
    empresa["diagnostico_presenca_digital"] = _diagnostico(empresa, score, classificacao)
    empresa["oportunidade_marketing_principal"] = _oportunidade_marketing(empresa)
    empresa["confianca_diagnostico_presenca"] = _confianca(empresa)
    empresa["observacao_limite_dados_presenca"] = _observacao_limite(empresa)

    return empresa
