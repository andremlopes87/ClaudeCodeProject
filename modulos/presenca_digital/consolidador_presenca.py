"""
modulos/presenca_digital/consolidador_presenca.py — Consolidação comercial da presença digital.

Unifica os sinais de presença digital em uma visão comercial única por empresa:
- dados OSM (website, telefone, email, instagram)
- análise do website (score_presenca_web, classificacao_presenca_web)
- canais digitais enriquecidos (confianca_*, origem_*, *_confirmado)

Campos gerados por empresa:
  score_presenca_consolidado       : 0-100 (qualidade do perfil digital como base para proposta)
  classificacao_presenca_comercial : oportunidade_alta/media/baixa/pouca_utilidade
  pronta_para_oferta_presenca      : True se há canais e classificação permite proposta
  principal_gargalo_presenca       : principal lacuna identificada
  oportunidade_presenca_principal  : o que pode ser melhorado / vendido
  solucao_recomendada_presenca     : solução específica por categoria + gargalo
  prioridade_oferta_presenca       : alta / media / baixa / nula
  motivo_prioridade_presenca       : por que esta prioridade

Documentação: docs/presenca_digital/heuristicas.md
"""

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pesos para score_presenca_consolidado (máximo = 100)
# nome=15, canais=62, site_acessivel=8, web_qualidade=15
# ---------------------------------------------------------------------------

_PESOS_CANAIS = {
    "website": 15,
    "telefone": 12,
    "whatsapp": 12,
    "email": 10,
    "instagram": 8,
    "facebook": 5,
}

_MULTIPLIC_CONF = {
    "alta": 1.0,
    "media": 0.7,
    "baixa": 0.3,
    "nao_identificado": 0.0,
}

_ORDEM_PRIORIDADE = {
    "oportunidade_alta_presenca": 0,
    "oportunidade_media_presenca": 1,
    "oportunidade_baixa_presenca": 2,
    "pouca_utilidade_presenca": 3,
}

_TODOS_CANAIS = ["telefone", "email", "website", "whatsapp", "instagram", "facebook"]

# ---------------------------------------------------------------------------
# Textos por gap principal
# ---------------------------------------------------------------------------

_TEXTOS_GARGALO = {
    "dados_insuficientes": "Dados insuficientes para diagnóstico comercial",
    "sem_canais": "Sem canais digitais identificados nos dados públicos",
    "sem_website": "Sem website próprio — ausência de presença digital estruturada",
    "site_inacessivel": "Website inacessível — site registrado não está respondendo",
    "sem_whatsapp": "Sem WhatsApp identificado — barreira ao contato rápido",
    "sem_cta": "Site sem chamada para ação — visitante não sabe o que fazer",
    "sem_email": "Sem e-mail público de contato",
    "sem_https": "Site sem HTTPS — sinal básico de segurança ausente",
    "sem_instagram": "Sem presença identificada no Instagram",
    "sem_facebook": "Sem presença identificada no Facebook",
    "presenca_estruturada": "Presença digital razoavelmente estruturada",
}

_TEXTOS_OPORTUNIDADE = {
    "dados_insuficientes": "Levantar dados básicos para iniciar diagnóstico de presença",
    "sem_canais": "Identificar e criar canais digitais básicos de contato",
    "sem_website": "Criar presença digital própria com canais de contato integrados",
    "site_inacessivel": "Recuperar site e garantir disponibilidade contínua",
    "sem_whatsapp": "Adicionar WhatsApp como canal de conversão direta no site",
    "sem_cta": "Otimizar site com botões e formulários para geração de contatos",
    "sem_email": "Configurar e-mail profissional e formulário de contato",
    "sem_https": "Migrar para HTTPS para melhorar confiança e segurança",
    "sem_instagram": "Criar e gerenciar perfil Instagram com conteúdo da categoria",
    "sem_facebook": "Criar página Facebook integrada ao site",
    "presenca_estruturada": "Melhorar SEO local e gestão de avaliações Google",
}

_SOLUCOES_POR_GAP: dict = {
    "dados_insuficientes": {
        "default": "Pesquisa e mapeamento digital básico da empresa",
    },
    "sem_canais": {
        "default": "Pesquisa de canais públicos disponíveis e criação de perfil básico",
    },
    "sem_website": {
        "barbearia": "Landing page com agendamento online e botão WhatsApp",
        "salao_de_beleza": "Landing page com agendamento online e galeria de trabalhos",
        "oficina_mecanica": "Página de orçamento online com formulário e WhatsApp",
        "borracharia": "Página de serviços com WhatsApp e mapa de localização",
        "acougue": "Cardápio digital com WhatsApp para pedidos e horários",
        "padaria": "Cardápio digital com horários e WhatsApp para encomendas",
        "autopecas": "Catálogo de peças com formulário de cotação online",
        "default": "Landing page com canais de contato, localização e horários",
    },
    "site_inacessivel": {
        "default": "Diagnóstico e recuperação do site com monitoramento de disponibilidade",
    },
    "sem_whatsapp": {
        "default": "Integração de botão WhatsApp no site com mensagem pré-configurada",
    },
    "sem_cta": {
        "barbearia": "Botão de agendamento online em destaque com horários disponíveis",
        "salao_de_beleza": "Sistema de agendamento integrado ao site existente",
        "oficina_mecanica": "Formulário de orçamento online em destaque no site",
        "default": "Botões de contato e conversão em destaque no site",
    },
    "sem_email": {
        "default": "Configuração de e-mail profissional e formulário de contato no site",
    },
    "sem_https": {
        "default": "Migração para HTTPS e configuração de certificado SSL",
    },
    "sem_instagram": {
        "barbearia": "Criação e gestão de Instagram com fotos de cortes e promoções",
        "salao_de_beleza": "Criação e gestão de Instagram com antes/depois e agenda",
        "oficina_mecanica": "Criação de Instagram com dicas de manutenção e serviços",
        "default": "Criação e gestão de perfil Instagram com conteúdo da categoria",
    },
    "sem_facebook": {
        "default": "Criação de página Facebook integrada ao site com avaliações",
    },
    "presenca_estruturada": {
        "default": "SEO local: otimização Google Meu Negócio e gestão de avaliações",
    },
}


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def consolidar_presenca(empresas: list) -> list:
    """
    Aplica consolidação comercial de presença digital em todas as empresas.

    Entrada: lista de empresas após analisador_web, diagnosticador_presenca e enriquecedor_canais
    Saída: mesma lista com campos de consolidação adicionados
    """
    logger.info(f"Consolidando presenca digital de {len(empresas)} empresas...")
    resultado = [_consolidar(e) for e in empresas]

    contagens: dict = {}
    for e in resultado:
        cls = e.get("classificacao_presenca_comercial", "pouca_utilidade_presenca")
        contagens[cls] = contagens.get(cls, 0) + 1

    for cls, n in sorted(contagens.items(), key=lambda x: _ORDEM_PRIORIDADE.get(x[0], 9)):
        logger.info(f"  {cls}: {n}")

    return resultado


def gerar_fila_marketing(empresas: list) -> list:
    """
    Gera fila de oportunidades de marketing digital para ação comercial.

    Inclui empresas com classificacao_presenca_comercial:
    - oportunidade_alta_presenca
    - oportunidade_media_presenca

    Ordenação: prioridade → score_presenca_consolidado (desc) → score_prontidao_ia (desc)
    """
    _ORDEM_P = {"alta": 0, "media": 1, "baixa": 2, "nula": 3}

    candidatas = [
        e for e in empresas
        if e.get("classificacao_presenca_comercial") in (
            "oportunidade_alta_presenca",
            "oportunidade_media_presenca",
        )
    ]
    return sorted(
        candidatas,
        key=lambda e: (
            _ORDEM_P.get(e.get("prioridade_oferta_presenca", "nula"), 3),
            -e.get("score_presenca_consolidado", 0),
            -e.get("score_prontidao_ia", 0),
        ),
    )


# ---------------------------------------------------------------------------
# Consolidação por empresa
# ---------------------------------------------------------------------------

def _consolidar(empresa: dict) -> dict:
    """Aplica consolidação completa em uma única empresa."""
    score = _calcular_score_consolidado(empresa)
    gap = _detectar_gap(empresa)
    classificacao = _classificar_comercialmente(empresa, score, gap)
    prioridade = _prioridade_oferta(classificacao)

    empresa["score_presenca_consolidado"] = score
    empresa["classificacao_presenca_comercial"] = classificacao
    empresa["pronta_para_oferta_presenca"] = _pronta_para_oferta(empresa, classificacao)
    empresa["principal_gargalo_presenca"] = _TEXTOS_GARGALO.get(gap, gap)
    empresa["oportunidade_presenca_principal"] = _TEXTOS_OPORTUNIDADE.get(gap, gap)
    empresa["solucao_recomendada_presenca"] = _solucao_recomendada(empresa, gap)
    empresa["prioridade_oferta_presenca"] = prioridade
    empresa["motivo_prioridade_presenca"] = _motivo_prioridade(empresa, classificacao, gap)

    return empresa


# ---------------------------------------------------------------------------
# Score consolidado
# ---------------------------------------------------------------------------

def _calcular_score_consolidado(empresa: dict) -> int:
    """
    Calcula score_presenca_consolidado (0-100).

    Mede a qualidade do perfil digital como base para proposta comercial:
    - quanto sabemos sobre os canais da empresa
    - se o website existe e funciona
    - se a presença web tem qualidade
    """
    score = 0

    # Empresa identificável (tem nome, não é pouco_util)
    if empresa.get("classificacao_comercial") != "pouco_util":
        score += 15

    # Canais confirmados (ponderados por confiança)
    for canal, peso in _PESOS_CANAIS.items():
        conf = empresa.get(f"confianca_{canal}", "nao_identificado")
        mult = _MULTIPLIC_CONF.get(conf, 0.0)
        score += round(peso * mult)

    # Site acessível
    if empresa.get("site_acessivel"):
        score += 8

    # Qualidade da presença web (normalizada)
    score_web = empresa.get("score_presenca_web") or 0
    score += round(score_web / 100 * 15)

    return min(score, 100)


# ---------------------------------------------------------------------------
# Detecção do gap principal
# ---------------------------------------------------------------------------

def _detectar_gap(empresa: dict) -> str:
    """
    Identifica o gap mais crítico da presença digital.

    Retorna código interno usado para gerar textos de gargalo, oportunidade e solução.
    Ordem de prioridade: existência de dados → website → qualidade do site → canais no site.
    """
    if empresa.get("classificacao_comercial") == "pouco_util":
        return "dados_insuficientes"

    tem_canal = any(
        empresa.get(f"confianca_{c}", "nao_identificado") != "nao_identificado"
        for c in _TODOS_CANAIS
    )
    if not tem_canal:
        return "sem_canais"

    if not empresa.get("website_confirmado"):
        return "sem_website"

    if empresa.get("tem_site") and not empresa.get("site_acessivel"):
        return "site_inacessivel"

    if not empresa.get("whatsapp_confirmado"):
        return "sem_whatsapp"

    if not empresa.get("tem_cta_clara"):
        return "sem_cta"

    if not empresa.get("email_confirmado"):
        return "sem_email"

    if not empresa.get("usa_https"):
        return "sem_https"

    if not empresa.get("instagram_confirmado"):
        return "sem_instagram"

    if not empresa.get("facebook_confirmado"):
        return "sem_facebook"

    return "presenca_estruturada"


# ---------------------------------------------------------------------------
# Classificação comercial
# ---------------------------------------------------------------------------

def _classificar_comercialmente(empresa: dict, score: int, gap: str) -> str:
    """
    Classifica a empresa quanto à oportunidade comercial de presença digital.

    oportunidade_alta_presenca : tem contato + presença fraca/básica + score suficiente
    oportunidade_media_presenca: tem canais mas perfil incompleto
    oportunidade_baixa_presenca: tem canais mas pouca lacuna para explorar
    pouca_utilidade_presenca   : sem identificação ou sem canais úteis
    """
    class_comercial = empresa.get("classificacao_comercial", "pouco_util")
    class_web = empresa.get("classificacao_presenca_web", "dados_insuficientes")

    # Descarte imediato
    if class_comercial == "pouco_util" or score < 15:
        return "pouca_utilidade_presenca"

    n_canais = sum(
        1 for c in _TODOS_CANAIS
        if empresa.get(f"confianca_{c}", "nao_identificado") != "nao_identificado"
    )

    # Tem canal de contato direto confirmado (telefone ou email com confiança usável)
    tem_contato_util = (
        empresa.get("confianca_telefone", "nao_identificado") in ("alta", "media")
        or empresa.get("confianca_email", "nao_identificado") in ("alta", "media")
    )

    # Presença digital com lacuna clara (fraca, básica ou sem website)
    presenca_com_lacuna = class_web in ("presenca_fraca", "presenca_basica", "dados_insuficientes")
    sem_website_com_canal = gap == "sem_website" and n_canais >= 1

    # oportunidade_alta: tem contato + presença fraca + score suficiente
    if tem_contato_util and score >= 25 and (presenca_com_lacuna or sem_website_com_canal):
        return "oportunidade_alta_presenca"

    # oportunidade_media: tem canais mas perfil ainda incompleto
    if n_canais >= 1 and score >= 20:
        return "oportunidade_media_presenca"

    # oportunidade_baixa: tem algo mas lacuna pequena (presença boa ou dados parciais)
    if score >= 15 and n_canais >= 1:
        return "oportunidade_baixa_presenca"

    return "pouca_utilidade_presenca"


# ---------------------------------------------------------------------------
# Campos derivados da classificação
# ---------------------------------------------------------------------------

def _pronta_para_oferta(empresa: dict, classificacao: str) -> bool:
    """
    True se a empresa tem classificação favorável E canal de contato disponível para proposta.
    """
    if classificacao not in ("oportunidade_alta_presenca", "oportunidade_media_presenca"):
        return False
    return (
        empresa.get("confianca_telefone", "nao_identificado") in ("alta", "media")
        or empresa.get("confianca_email", "nao_identificado") in ("alta", "media")
        or empresa.get("confianca_website", "nao_identificado") in ("alta", "media")
    )


def _solucao_recomendada(empresa: dict, gap: str) -> str:
    """Solução específica para o gap, adaptada à categoria da empresa."""
    categoria_id = empresa.get("categoria_id", "default")
    solucoes = _SOLUCOES_POR_GAP.get(gap, {})
    return solucoes.get(categoria_id) or solucoes.get("default", "Diagnóstico de presença digital completo")


def _prioridade_oferta(classificacao: str) -> str:
    return {
        "oportunidade_alta_presenca": "alta",
        "oportunidade_media_presenca": "media",
        "oportunidade_baixa_presenca": "baixa",
        "pouca_utilidade_presenca": "nula",
    }.get(classificacao, "nula")


def _motivo_prioridade(empresa: dict, classificacao: str, gap: str) -> str:
    """Texto explicando por que esta empresa tem esta prioridade."""
    nome = empresa.get("nome", "Empresa")

    if classificacao == "oportunidade_alta_presenca":
        contato = (
            empresa.get("contato_principal")
            or empresa.get("telefone_confirmado")
            or "canal identificado"
        )
        gargalo = _TEXTOS_GARGALO.get(gap, gap).lower()
        return (
            f"{nome} tem canal de contato confirmado ({contato}) e presença digital fraca — "
            f"gargalo principal: {gargalo}."
        )

    if classificacao == "oportunidade_media_presenca":
        return (
            f"{nome} tem canais digitais parcialmente identificados mas perfil incompleto — "
            f"potencial para proposta moderada de melhoria de presença."
        )

    if classificacao == "oportunidade_baixa_presenca":
        if empresa.get("classificacao_presenca_web") == "presenca_boa":
            return f"{nome} já tem presença digital bem estruturada — oportunidade de melhoria limitada."
        return (
            f"{nome} tem dados insuficientes para proposta direta de melhoria de presença."
        )

    if gap == "sem_canais":
        return (
            f"{nome} identificada mas sem canais digitais confirmados — "
            f"não é possível sustentar proposta agora."
        )

    return f"{nome} sem dados suficientes para proposta comercial de presença digital."
