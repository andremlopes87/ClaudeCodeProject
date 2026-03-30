import logging
"""
core/identidade_empresa.py — Camada de identidade operacional da empresa (v0.39).

Fonte única e auditável da identidade da empresa.
Lida por: agente_comercial, agente_executor_contato, painel do conselho,
          futuros conectores reais de email/WhatsApp.

Arquivos gerenciados:
  dados/identidade_empresa.json      — identidade institucional
  dados/guia_comunicacao_empresa.json — tom de voz e posicionamento
  dados/assinaturas_empresa.json     — assinaturas por contexto
  dados/canais_empresa.json          — canais oficiais planejados/configurados
  dados/historico_identidade_empresa.json — trilha de auditoria
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

import config

_ARQ_IDENTIDADE  = config.PASTA_DADOS / "identidade_empresa.json"
_ARQ_GUIA        = config.PASTA_DADOS / "guia_comunicacao_empresa.json"
_ARQ_ASSINATURAS = config.PASTA_DADOS / "assinaturas_empresa.json"
_ARQ_CANAIS      = config.PASTA_DADOS / "canais_empresa.json"
_ARQ_HISTORICO   = config.PASTA_DADOS / "historico_identidade_empresa.json"

# ─── Padrões provisórios ──────────────────────────────────────────────────────
# Servem de ponto de partida antes do conselho definir os valores reais.

_IDENTIDADE_PADRAO = {
    "id_empresa":             "empresa_ia_001",
    "nome_oficial":           "Empresa IA",
    "nome_exibicao":          "Empresa IA",
    "descricao_curta":        "Agência de presença digital e automação para pequenos negócios.",
    "descricao_media":        (
        "Ajudamos pequenas empresas a aparecerem online, atenderem melhor e "
        "crescerem com menos esforço manual — usando tecnologia acessível e suporte humano próximo."
    ),
    "proposta_valor_resumida": (
        "Presença digital real e automação de atendimento para quem não tem tempo de cuidar disso sozinho."
    ),
    "publico_alvo":           "Pequenos negócios locais com baixa presença digital (barbearias, oficinas, padarias, restaurantes, etc.)",
    "linhas_servico":         [
        "marketing_presenca_digital",
        "automacao_atendimento",
    ],
    "cidade_base":            "",
    "pais_base":              "Brasil",
    "idioma_padrao":          "pt-BR",
    "ativa":                  True,
    "criado_em":              "",
    "atualizado_em":          "",
}

_GUIA_PADRAO = {
    "tom_voz":               "claro, objetivo, consultivo, sem floreio",
    "nivel_formalidade":     "medio",
    "palavras_que_usa":      [
        "resultado", "simples", "prático", "rápido", "sua empresa",
        "clientes", "aparecer no Google", "sem complicação",
    ],
    "palavras_que_evita":    [
        "incrível", "revolucionário", "disruptivo", "sinergia",
        "solução end-to-end", "ecossistema", "paradigma",
    ],
    "estilo_abertura":       "direto ao ponto: apresentar o problema identificado antes de qualquer oferta",
    "estilo_fechamento":     "ação clara: próximo passo concreto, sem pressão",
    "postura_comercial":     "diagnostica, sem pressão — mostrar o problema, deixar o cliente decidir",
    "postura_consultiva":    "parceiro próximo, linguagem simples, sem jargão técnico",
    "postura_cobranca":      "firme e respeitosa — clareza sobre prazo e valor, sem desculpas",
    "observacoes":           "Nunca prometer resultado que depende de terceiros. Falar sempre como parceiro, não como vendedor.",
    "atualizado_em":         "",
}

_ASSINATURAS_PADRAO = {
    "nome_remetente_padrao":  "Equipe Empresa IA",
    "cargo_remetente_padrao": "Consultoria de Presença Digital",
    "assinatura_comercial_texto": (
        "\n---\n{nome_remetente}\n{cargo}\n{nome_empresa}\n{email_comercial}"
    ),
    "assinatura_comercial_html_opcional": "",
    "assinatura_financeiro_texto": (
        "\n---\n{nome_remetente}\nFinanceiro — {nome_empresa}\n{email_financeiro}"
    ),
    "assinatura_financeiro_html_opcional": "",
    "assinatura_institucional_texto": (
        "\n---\n{nome_empresa}\n{descricao_curta}\n{site_oficial}"
    ),
    "atualizado_em": "",
}

_CANAIS_PADRAO = {
    "dominio_oficial_planejado":    "",
    "email_principal_planejado":    "",
    "email_comercial_planejado":    "",
    "email_financeiro_planejado":   "",
    "instagram_oficial":            "",
    "site_oficial":                 "",
    "whatsapp_oficial":             "",
    "status_configuracao_email":    "nao_definido",
    "status_configuracao_site":     "nao_definido",
    "observacoes":                  "Canais ainda não configurados. Definir domínio antes de configurar email.",
    "atualizado_em":                "",
}

# Status válidos para configuração
STATUS_EMAIL_VALIDOS = {
    "nao_definido",
    "definido_sem_configurar",
    "configurado_modo_assistido",
    "configurado_real",
}


# ─── I/O ─────────────────────────────────────────────────────────────────────

def _ler(arq: Path, padrao: dict) -> dict:
    if not arq.exists():
        return dict(padrao)
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except Exception:
        return dict(padrao)


def _salvar_arq(arq: Path, dados: dict) -> None:
    """Escrita atômica: .tmp → fsync → os.replace"""
    import os
    arq.parent.mkdir(parents=True, exist_ok=True)
    conteudo = json.dumps(dados, ensure_ascii=False, indent=2)
    tmp = arq.with_suffix(arq.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, arq)


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ─── Leitura ─────────────────────────────────────────────────────────────────

def carregar_identidade() -> dict:
    """Carrega identidade_empresa.json. Inicializa com padrão se não existir."""
    dados = _ler(_ARQ_IDENTIDADE, _IDENTIDADE_PADRAO)
    if not dados.get("criado_em"):
        # Primeiro acesso: inicializar e salvar
        dados["criado_em"] = _agora()
        dados["atualizado_em"] = _agora()
        _salvar_arq(_ARQ_IDENTIDADE, dados)
    return dados


def carregar_guia_comunicacao() -> dict:
    dados = _ler(_ARQ_GUIA, _GUIA_PADRAO)
    if not dados.get("atualizado_em"):
        dados["atualizado_em"] = _agora()
        _salvar_arq(_ARQ_GUIA, dados)
    return dados


def carregar_assinaturas() -> dict:
    dados = _ler(_ARQ_ASSINATURAS, _ASSINATURAS_PADRAO)
    if not dados.get("atualizado_em"):
        dados["atualizado_em"] = _agora()
        _salvar_arq(_ARQ_ASSINATURAS, dados)
    return dados


def carregar_canais() -> dict:
    dados = _ler(_ARQ_CANAIS, _CANAIS_PADRAO)
    if not dados.get("atualizado_em"):
        dados["atualizado_em"] = _agora()
        _salvar_arq(_ARQ_CANAIS, dados)
    return dados


# ─── Escrita com histórico ────────────────────────────────────────────────────

def salvar_identidade(dados: dict, origem: str = "painel") -> dict:
    """Salva identidade com timestamp e registro no histórico."""
    dados["atualizado_em"] = _agora()
    if not dados.get("criado_em"):
        dados["criado_em"] = _agora()
    _salvar_arq(_ARQ_IDENTIDADE, dados)
    _registrar_historico("identidade_atualizada",
                         f"nome_oficial='{dados.get('nome_oficial','')}' | "
                         f"linhas={dados.get('linhas_servico',[])}", origem)
    return dados


def salvar_guia_comunicacao(dados: dict, origem: str = "painel") -> dict:
    dados["atualizado_em"] = _agora()
    _salvar_arq(_ARQ_GUIA, dados)
    _registrar_historico("guia_comunicacao_atualizado",
                         f"tom='{dados.get('tom_voz','')}' | "
                         f"formalidade='{dados.get('nivel_formalidade','')}'", origem)
    return dados


def salvar_assinaturas(dados: dict, origem: str = "painel") -> dict:
    dados["atualizado_em"] = _agora()
    _salvar_arq(_ARQ_ASSINATURAS, dados)
    _registrar_historico("assinaturas_atualizadas",
                         f"remetente='{dados.get('nome_remetente_padrao','')}'", origem)
    return dados


def salvar_canais(dados: dict, origem: str = "painel") -> dict:
    dados["atualizado_em"] = _agora()
    _salvar_arq(_ARQ_CANAIS, dados)
    _registrar_historico("canais_atualizados",
                         f"dominio='{dados.get('dominio_oficial_planejado','')}' | "
                         f"status_email='{dados.get('status_configuracao_email','')}'", origem)
    return dados


# ─── Histórico ────────────────────────────────────────────────────────────────

def _registrar_historico(evento: str, descricao: str, origem: str = "sistema") -> None:
    historico = []
    if _ARQ_HISTORICO.exists():
        try:
            historico = json.loads(_ARQ_HISTORICO.read_text(encoding="utf-8"))
        except Exception:
            historico = []
    historico.append({
        "id":           str(uuid.uuid4())[:8],
        "evento":       evento,
        "descricao":    descricao,
        "origem":       origem,
        "registrado_em": _agora(),
    })
    _salvar_arq(_ARQ_HISTORICO, historico[-200:])


# ─── Utilitários de uso pelos agentes ────────────────────────────────────────

def obter_assinatura(tipo: str = "comercial") -> str:
    """
    Retorna texto de assinatura com variáveis substituídas.

    tipo: 'comercial' | 'financeiro' | 'institucional'
    """
    assinaturas = carregar_assinaturas()
    identidade  = carregar_identidade()
    canais      = carregar_canais()

    template_key = f"assinatura_{tipo}_texto"
    template = assinaturas.get(template_key, "")

    return template.format(
        nome_remetente=assinaturas.get("nome_remetente_padrao", "Equipe"),
        cargo=assinaturas.get("cargo_remetente_padrao", ""),
        nome_empresa=identidade.get("nome_exibicao") or identidade.get("nome_oficial", ""),
        email_comercial=canais.get("email_comercial_planejado", "(email a definir)"),
        email_financeiro=canais.get("email_financeiro_planejado", "(email a definir)"),
        site_oficial=canais.get("site_oficial", "(site a definir)"),
        descricao_curta=identidade.get("descricao_curta", ""),
    )


def obter_contexto_remetente() -> dict:
    """
    Retorna dict com dados de remetente para uso em payloads de execução.
    Usado pelo agente_executor_contato para enriquecer payload_execucao.
    """
    identidade  = carregar_identidade()
    assinaturas = carregar_assinaturas()
    canais      = carregar_canais()

    return {
        "nome_empresa":         identidade.get("nome_exibicao") or identidade.get("nome_oficial", ""),
        "nome_remetente":       assinaturas.get("nome_remetente_padrao", ""),
        "cargo_remetente":      assinaturas.get("cargo_remetente_padrao", ""),
        "email_comercial":      canais.get("email_comercial_planejado", ""),
        "email_principal":      canais.get("email_principal_planejado", ""),
        "whatsapp_oficial":     canais.get("whatsapp_oficial", ""),
        "site_oficial":         canais.get("site_oficial", ""),
        "proposta_valor":       identidade.get("proposta_valor_resumida", ""),
        "status_email":         canais.get("status_configuracao_email", "nao_definido"),
        "assinatura_comercial": obter_assinatura("comercial"),
    }


def obter_contexto_comercial() -> dict:
    """
    Retorna resumo de identidade + guia para uso pelo agente_comercial.
    Contexto para enriquecer handoffs e mensagens geradas.
    """
    identidade = carregar_identidade()
    guia       = carregar_guia_comunicacao()

    return {
        "nome_empresa":        identidade.get("nome_exibicao") or identidade.get("nome_oficial", ""),
        "descricao_curta":     identidade.get("descricao_curta", ""),
        "proposta_valor":      identidade.get("proposta_valor_resumida", ""),
        "linhas_servico":      identidade.get("linhas_servico", []),
        "tom_voz":             guia.get("tom_voz", ""),
        "postura_comercial":   guia.get("postura_comercial", ""),
        "estilo_abertura":     guia.get("estilo_abertura", ""),
        "estilo_fechamento":   guia.get("estilo_fechamento", ""),
        "palavras_que_usa":    guia.get("palavras_que_usa", []),
        "palavras_que_evita":  guia.get("palavras_que_evita", []),
    }


# ─── Resumo para painel ───────────────────────────────────────────────────────

def resumir_identidade_para_painel() -> dict:
    """Snapshot completo para o painel do conselho."""
    identidade  = carregar_identidade()
    guia        = carregar_guia_comunicacao()
    assinaturas = carregar_assinaturas()
    canais      = carregar_canais()

    historico = []
    if _ARQ_HISTORICO.exists():
        try:
            historico = json.loads(_ARQ_HISTORICO.read_text(encoding="utf-8"))
        except Exception as _err:
            logging.warning("erro ignorado: %s", _err)

    return {
        "identidade":      identidade,
        "guia":            guia,
        "assinaturas":     assinaturas,
        "canais":          canais,
        "historico":       list(reversed(historico))[:20],
        "status_completo": _avaliar_completude(identidade, canais),
    }


def _avaliar_completude(identidade: dict, canais: dict) -> dict:
    """Avalia quais campos essenciais ainda estão vazios."""
    campos_ok = []
    campos_pendentes = []

    checks = [
        (identidade.get("nome_oficial"), "nome_oficial"),
        (identidade.get("descricao_curta"), "descricao_curta"),
        (identidade.get("proposta_valor_resumida"), "proposta_valor_resumida"),
        (identidade.get("linhas_servico"), "linhas_servico"),
        (identidade.get("cidade_base"), "cidade_base"),
        (canais.get("dominio_oficial_planejado"), "dominio_oficial_planejado"),
        (canais.get("email_comercial_planejado"), "email_comercial_planejado"),
        (canais.get("instagram_oficial"), "instagram_oficial"),
        (canais.get("site_oficial"), "site_oficial"),
    ]
    for valor, campo in checks:
        (campos_ok if valor else campos_pendentes).append(campo)

    pct = int(100 * len(campos_ok) / len(checks)) if checks else 0
    return {
        "percentual":      pct,
        "campos_ok":       campos_ok,
        "campos_pendentes": campos_pendentes,
        "status":          "completo" if pct == 100 else ("parcial" if pct >= 50 else "inicial"),
    }
