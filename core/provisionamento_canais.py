import logging
"""
core/provisionamento_canais.py — Camada de provisionamento de canais reais (v0.42).

Gerencia o estado de ativação do canal email real:
  - provisionamento_email_real.json  — configurações externas e status DNS/SMTP
  - checklist_ativacao_email.json    — checklist auditável de pré-requisitos
  - historico_provisionamento_email.json — log de eventos de ativação

Esta camada não envia email, não acessa registradores de domínio,
não conecta SMTP. Apenas mantém o estado e valida prontidão.

Lógica de status:
  nao_pronto       → domínio não registrado (bloqueio crítico)
  em_preparacao    → domínio registrado, infra incompleta (< 50% obrigatórios)
  quase_pronto     → >= 50% obrigatórios, mas não todos
  pronto_para_modo_real → todos obrigatórios concluídos

Usado por:
  core/integrador_email.py  (guarda modo=real sem pré-requisitos)
  conselho_app/app.py        (página /ativacao-email)
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

import config

_ARQ_PROV   = "provisionamento_email_real.json"
_ARQ_CK     = "checklist_ativacao_email.json"
_ARQ_HIST   = "historico_provisionamento_email.json"

# ─── Checklist padrão ─────────────────────────────────────────────────────────

_CHECKLIST_PADRAO = [
    {
        "id":          "dominio_registrado",
        "titulo":      "Domínio registrado",
        "descricao":   "Registrar vetorops.com.br no registro.br ou registrador confiável",
        "obrigatorio": True,
        "status":      "pendente",
        "observacoes": "",
        "atualizado_em": None,
    },
    {
        "id":          "dominio_apontado",
        "titulo":      "DNS configurado e apontado",
        "descricao":   "Nameservers do domínio apontando para o provedor de email escolhido",
        "obrigatorio": True,
        "status":      "pendente",
        "observacoes": "",
        "atualizado_em": None,
    },
    {
        "id":          "caixa_principal_criada",
        "titulo":      "Caixa principal criada (contato@)",
        "descricao":   "Caixa contato@vetorops.com.br criada no provedor de email",
        "obrigatorio": False,
        "status":      "pendente",
        "observacoes": "",
        "atualizado_em": None,
    },
    {
        "id":          "caixa_comercial_criada",
        "titulo":      "Caixa comercial criada (comercial@)",
        "descricao":   "Caixa comercial@vetorops.com.br criada — usada como remetente padrão",
        "obrigatorio": True,
        "status":      "pendente",
        "observacoes": "",
        "atualizado_em": None,
    },
    {
        "id":          "caixa_financeiro_criada",
        "titulo":      "Caixa financeiro criada (financeiro@)",
        "descricao":   "Caixa financeiro@vetorops.com.br criada",
        "obrigatorio": False,
        "status":      "pendente",
        "observacoes": "",
        "atualizado_em": None,
    },
    {
        "id":          "credenciais_seguras_definidas",
        "titulo":      "Credenciais SMTP definidas como variáveis de ambiente",
        "descricao":   "SMTP_HOST, SMTP_PORTA, SMTP_USUARIO, SMTP_SENHA definidos — NUNCA no repo",
        "obrigatorio": True,
        "status":      "pendente",
        "observacoes": "",
        "atualizado_em": None,
    },
    {
        "id":          "mx_configurado",
        "titulo":      "MX records configurados",
        "descricao":   "Registros MX do domínio apontando para o servidor de email",
        "obrigatorio": True,
        "status":      "pendente",
        "observacoes": "",
        "atualizado_em": None,
    },
    {
        "id":          "spf_configurado",
        "titulo":      "SPF configurado",
        "descricao":   "Registro TXT SPF adicionado ao DNS para autorizar o servidor de envio",
        "obrigatorio": True,
        "status":      "pendente",
        "observacoes": "Exemplo: v=spf1 include:zoho.com ~all",
        "atualizado_em": None,
    },
    {
        "id":          "dkim_configurado",
        "titulo":      "DKIM configurado",
        "descricao":   "Chave DKIM gerada pelo provedor e adicionada ao DNS",
        "obrigatorio": True,
        "status":      "pendente",
        "observacoes": "Necessário para deliverability e evitar spam",
        "atualizado_em": None,
    },
    {
        "id":          "dmarc_configurado",
        "titulo":      "DMARC configurado",
        "descricao":   "Política DMARC adicionada ao DNS (pode ser p=none no início)",
        "obrigatorio": False,
        "status":      "pendente",
        "observacoes": "Recomendado para reputação futura, não obrigatório para início",
        "atualizado_em": None,
    },
    {
        "id":          "config_canal_email_preenchida",
        "titulo":      "config_canal_email.json preenchido com dados reais",
        "descricao":   "email_remetente_planejado, nome_remetente e responder_para preenchidos com endereços reais",
        "obrigatorio": True,
        "status":      "pendente",
        "observacoes": "",
        "atualizado_em": None,
    },
    {
        "id":          "teste_assistido_validado",
        "titulo":      "Pelo menos 1 ciclo em modo assistido validado",
        "descricao":   "Rodar ciclo em modo=assistido, revisar emails preparados na fila e confirmar conteúdo correto",
        "obrigatorio": True,
        "status":      "concluido",   # já feito em v0.40
        "observacoes": "Validado durante implementação v0.40",
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
    },
    {
        "id":          "whitelist_teste_configurada",
        "titulo":      "Lista de emails de teste definida",
        "descricao":   "Definir whitelist_emails_teste em config_canal_email.json antes do primeiro envio real",
        "obrigatorio": True,
        "status":      "pendente",
        "observacoes": "Garante que o primeiro envio só vai para endereços controlados",
        "atualizado_em": None,
    },
    {
        "id":          "envio_teste_controlado_validado",
        "titulo":      "Envio de teste controlado validado",
        "descricao":   "Envio real para whitelist_emails_teste, verificar recebimento, SPF/DKIM/DMARC, não-spam",
        "obrigatorio": True,
        "status":      "pendente",
        "observacoes": "Só executar após todos os itens anteriores concluídos",
        "atualizado_em": None,
    },
]

# ─── Provisionamento padrão ────────────────────────────────────────────────────

def _prov_padrao() -> dict:
    agora = datetime.now().isoformat(timespec="seconds")
    # Ler identidade/canais para pré-preencher planejados
    nome_empresa = "Vetor Operações Ltda"
    dominio      = "vetorops.com.br"
    try:
        from core.identidade_empresa import carregar_identidade, carregar_canais
        ident  = carregar_identidade()
        canais = carregar_canais()
        nome_empresa = ident.get("nome_oficial", nome_empresa)
        dominio      = canais.get("dominio_oficial_planejado", dominio)
        c_principal  = canais.get("email_principal_planejado", f"contato@{dominio}")
        c_comercial  = canais.get("email_comercial_planejado", f"comercial@{dominio}")
        c_financeiro = canais.get("email_financeiro_planejado", f"financeiro@{dominio}")
        c_operacoes  = canais.get("email_operacoes_planejado", f"operacoes@{dominio}")
    except Exception:
        c_principal  = f"contato@{dominio}"
        c_comercial  = f"comercial@{dominio}"
        c_financeiro = f"financeiro@{dominio}"
        c_operacoes  = f"operacoes@{dominio}"

    return {
        "empresa":                  nome_empresa,
        "dominio_planejado":        dominio,
        "provedor_email_planejado": "",
        "caixa_principal_planejada":  c_principal,
        "caixa_comercial_planejada":  c_comercial,
        "caixa_financeiro_planejada": c_financeiro,
        "caixa_operacoes_planejada":  c_operacoes,
        "smtp_host_planejado":      "",
        "smtp_porta_planejada":     587,
        "smtp_usuario_planejado":   "",
        # Status externo — preenchido manualmente após configuração
        "dominio_registrado":       False,
        "dns_configurado":          False,
        "mx_configurado":           False,
        "spf_configurado":          False,
        "dkim_configurado":         False,
        "dmarc_configurado":        False,
        "smtp_validado":            False,
        "remetente_validado":       False,
        "whitelist_teste_definida": False,
        # Derivado
        "pronto_para_modo_real":    False,
        "bloqueios":                [],
        "observacoes":              "",
        "criado_em":                agora,
        "atualizado_em":            agora,
    }


# ─── Load / Save ──────────────────────────────────────────────────────────────

def carregar_provisionamento_email() -> dict:
    """Carrega provisionamento_email_real.json. Cria com padrões se ausente."""
    arq = config.PASTA_DADOS / _ARQ_PROV
    if not arq.exists():
        dados = _prov_padrao()
        _salvar_json(_ARQ_PROV, dados)
        return dados
    return _carregar_json(_ARQ_PROV, _prov_padrao())


def salvar_provisionamento_email(dados: dict, origem: str = "manual") -> dict:
    """
    Salva provisionamento, reavalia prontidão, registra histórico.
    Retorna o dict atualizado com bloqueios e pronto_para_modo_real recalculados.
    """
    checklist = carregar_checklist_ativacao()
    apto, bloqueios = _avaliar_prontidao(dados, checklist)
    dados["pronto_para_modo_real"] = apto
    dados["bloqueios"]             = bloqueios
    dados["atualizado_em"]         = datetime.now().isoformat(timespec="seconds")
    _salvar_json(_ARQ_PROV, dados)

    evento = "provisionamento_atualizado" if apto else "provisionamento_incompleto"
    descricao = (
        f"pronto_para_modo_real={apto} | "
        f"bloqueios={len(bloqueios)} | origem={origem}"
    )
    registrar_evento_provisionamento(evento, descricao, origem)
    return dados


def carregar_checklist_ativacao() -> list:
    """Carrega checklist_ativacao_email.json. Cria padrão se ausente."""
    arq = config.PASTA_DADOS / _ARQ_CK
    if not arq.exists():
        _salvar_json(_ARQ_CK, _CHECKLIST_PADRAO)
        return list(_CHECKLIST_PADRAO)
    return _carregar_json(_ARQ_CK, list(_CHECKLIST_PADRAO))


def salvar_checklist_ativacao(items: list, origem: str = "manual") -> None:
    """Salva checklist e registra evento no histórico."""
    _salvar_json(_ARQ_CK, items)
    concluidos = sum(1 for i in items if i.get("status") == "concluido")
    total      = len(items)
    registrar_evento_provisionamento(
        "checklist_atualizado",
        f"{concluidos}/{total} itens concluídos | origem={origem}",
        origem,
    )


def registrar_evento_provisionamento(
    evento: str, descricao: str, origem: str = "sistema"
) -> None:
    """Adiciona evento ao historico_provisionamento_email.json."""
    hist = _carregar_json(_ARQ_HIST, [])
    hist.append({
        "id":           str(uuid.uuid4())[:8],
        "evento":       evento,
        "descricao":    descricao,
        "origem":       origem,
        "registrado_em": datetime.now().isoformat(timespec="seconds"),
    })
    _salvar_json(_ARQ_HIST, hist)


# ─── Avaliação de prontidão ───────────────────────────────────────────────────

def _avaliar_prontidao(prov: dict, checklist: list) -> tuple[bool, list]:
    """
    Avalia se pronto_para_modo_real pode ser True.
    Retorna (apto: bool, bloqueios: list[str]).
    """
    bloqueios = []

    # Identidade mínima
    try:
        from core.identidade_empresa import carregar_identidade, carregar_canais
        ident  = carregar_identidade()
        canais = carregar_canais()
        if not ident.get("nome_oficial"):
            bloqueios.append("identidade_empresa: nome_oficial ausente")
        if not canais.get("dominio_oficial_planejado"):
            bloqueios.append("canais_empresa: dominio_oficial_planejado ausente")
        if not canais.get("email_comercial_planejado"):
            bloqueios.append("canais_empresa: email_comercial_planejado ausente")
    except Exception as exc:
        bloqueios.append(f"Erro ao carregar identidade: {exc}")

    # Provisionamento externo
    if not prov.get("dominio_registrado"):
        bloqueios.append("Domínio não registrado (etapa externa obrigatória)")
    if not prov.get("mx_configurado"):
        bloqueios.append("MX records não configurados")
    if not prov.get("spf_configurado"):
        bloqueios.append("SPF não configurado")
    if not prov.get("dkim_configurado"):
        bloqueios.append("DKIM não configurado")
    if not prov.get("smtp_validado"):
        bloqueios.append("SMTP não validado")
    if not prov.get("remetente_validado"):
        bloqueios.append("Remetente não validado")
    if not prov.get("whitelist_teste_definida"):
        bloqueios.append("Whitelist de teste não definida")

    # Checklist obrigatórios
    obrigatorios_pendentes = [
        i["titulo"] for i in checklist
        if i.get("obrigatorio") and i.get("status") != "concluido"
    ]
    for item in obrigatorios_pendentes:
        bloqueios.append(f"Checklist obrigatório pendente: {item}")

    # config_canal_email
    try:
        from core.integrador_email import carregar_config_canal_email
        cfg = carregar_config_canal_email()
        if not cfg.get("email_remetente_planejado"):
            bloqueios.append("config_canal_email: email_remetente_planejado vazio")
    except Exception as _err:
        logging.warning("erro ignorado: %s", _err)

    return len(bloqueios) == 0, bloqueios


def avaliar_prontidao_modo_real() -> dict:
    """API pública — retorna dict com apto, bloqueios e status."""
    prov      = carregar_provisionamento_email()
    checklist = carregar_checklist_ativacao()
    apto, bloqueios = _avaliar_prontidao(prov, checklist)
    status    = calcular_status_geral(prov, checklist)
    return {
        "apto":      apto,
        "bloqueios": bloqueios,
        "status":    status,
    }


def validar_modo_real_permitido() -> tuple[bool, str]:
    """
    Chamado pelo integrador_email antes de processar em modo=real.
    Retorna (permitido: bool, motivo_bloqueio: str).
    """
    resultado = avaliar_prontidao_modo_real()
    if resultado["apto"]:
        return True, ""
    primeiro_bloqueio = resultado["bloqueios"][0] if resultado["bloqueios"] else "pré-requisitos incompletos"
    return False, primeiro_bloqueio


def calcular_status_geral(prov: dict, checklist: list) -> str:
    """
    Calcula status da ativação:
      nao_pronto         — domínio não registrado
      em_preparacao      — domínio registrado, < 50% obrigatórios concluídos
      quase_pronto       — >= 50% obrigatórios, mas não todos
      pronto_para_modo_real — todos obrigatórios concluídos
    """
    if not prov.get("dominio_registrado"):
        return "nao_pronto"

    obrigatorios = [i for i in checklist if i.get("obrigatorio")]
    if not obrigatorios:
        return "em_preparacao"

    concluidos = sum(1 for i in obrigatorios if i.get("status") == "concluido")
    total      = len(obrigatorios)
    pct        = concluidos / total

    if pct >= 1.0:
        return "pronto_para_modo_real"
    if pct >= 0.5:
        return "quase_pronto"
    return "em_preparacao"


# ─── Resumo para painel ───────────────────────────────────────────────────────

def resumir_para_painel() -> dict:
    """
    Retorna dict completo para /ativacao-email e para index.html.
    """
    prov      = carregar_provisionamento_email()
    checklist = carregar_checklist_ativacao()
    hist      = _carregar_json(_ARQ_HIST, [])
    apto, bloqueios = _avaliar_prontidao(prov, checklist)
    status    = calcular_status_geral(prov, checklist)

    prov["pronto_para_modo_real"] = apto
    prov["bloqueios"]             = bloqueios

    obrigatorios = [i for i in checklist if i.get("obrigatorio")]
    concluidos   = sum(1 for i in obrigatorios if i.get("status") == "concluido")

    return {
        "provisionamento":  prov,
        "checklist":        checklist,
        "historico_recente": sorted(hist, key=lambda x: x.get("registrado_em",""), reverse=True)[:20],
        "status_geral":     status,
        "apto":             apto,
        "bloqueios":        bloqueios,
        "progresso": {
            "concluidos":  concluidos,
            "total_obrig": len(obrigatorios),
            "percentual":  int(concluidos / len(obrigatorios) * 100) if obrigatorios else 0,
        },
    }


# ─── Helpers JSON ─────────────────────────────────────────────────────────────

def _carregar_json(nome: str, padrao):
    caminho = config.PASTA_DADOS / nome
    if not caminho.exists():
        return padrao
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return padrao


def _salvar_json(nome: str, dados) -> None:
    import os
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = config.PASTA_DADOS / nome
    conteudo = json.dumps(dados, ensure_ascii=False, indent=2)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)
