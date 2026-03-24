"""
conectores/canal_email_assistido.py — Canal de email em modo assistido (v0.40).

Prepara emails estruturados SEM enviar. Cada email fica em fila_envio_email.json
com status 'preparado' ou 'bloqueado', pronto para revisão pelo conselho.

Responsabilidades:
  - Validar identidade mínima para montar email
  - Montar assunto e corpo a partir do contexto da execução
  - Aplicar assinatura da empresa (via identidade_empresa)
  - Nunca enviar nada real

Modos do canal:
  desativado  → não processa nada
  assistido   → prepara e para (estado desta etapa)
  real        → futuro: envia via SMTP/API

Identidade lida de:
  dados/config_canal_email.json
  dados/identidade_empresa.json
  dados/assinaturas_empresa.json
  dados/canais_empresa.json
"""

import logging

logger = logging.getLogger(__name__)

# ─── Validação de identidade ──────────────────────────────────────────────────

def validar_identidade_para_email(identidade: dict, canais: dict, config_canal: dict) -> tuple[bool, str]:
    """
    Verifica se a identidade está suficiente para montar email.

    Retorna (True, "") se OK, ou (False, motivo) se bloqueado.
    """
    if not identidade.get("ativa", True):
        return False, "identidade_empresa.ativa=False"

    if not identidade.get("nome_oficial") and not identidade.get("nome_exibicao"):
        return False, "nome_oficial e nome_exibicao ausentes na identidade"

    email_remetente = (
        config_canal.get("email_remetente_planejado")
        or canais.get("email_comercial_planejado")
        or canais.get("email_principal_planejado")
    )
    if not email_remetente:
        return False, "email_remetente_planejado e email_comercial_planejado ausentes em canais_empresa"

    modo = config_canal.get("modo", "desativado")
    if modo not in ("assistido", "real"):
        return False, f"canal_email modo='{modo}' — não está habilitado"

    return True, ""


# ─── Montagem de assunto ──────────────────────────────────────────────────────

def montar_assunto_email(execucao: dict, payload: dict, identidade: dict, config_canal: dict) -> str:
    """
    Monta linha de assunto com base no contexto da execução.
    Sem LLM — só substituição de variáveis.
    """
    prefixo = config_canal.get("assunto_prefixo", "")
    abordagem  = execucao.get("abordagem_inicial_tipo", "padrao")
    linha      = execucao.get("linha_servico_sugerida", "")
    ctx        = payload.get("contexto_oportunidade", {}) if payload else {}
    contraparte = (execucao.get("contraparte") or ctx.get("contraparte", "")).strip()
    categoria   = ctx.get("categoria", "")

    # Templates de assunto por abordagem
    _ASSUNTOS = {
        "exploratoria": "Como {contraparte} pode aparecer melhor no Google",
        "consultiva_diagnostica": "Diagnóstico de presença digital — {contraparte}",
        "followup_sem_resposta":  "Seguimento — {contraparte}",
        "reengajamento":          "Retomando o contato — {contraparte}",
        "padrao":                 "Oportunidade de melhoria digital — {contraparte}",
    }

    template = _ASSUNTOS.get(abordagem, _ASSUNTOS["padrao"])
    assunto  = template.format(contraparte=contraparte or "sua empresa", categoria=categoria)

    if prefixo:
        assunto = f"[{prefixo}] {assunto}"

    return assunto


# ─── Montagem de corpo (texto) ────────────────────────────────────────────────

def montar_corpo_email_texto(
    execucao: dict,
    payload: dict,
    identidade: dict,
    guia: dict,
    assinaturas: dict,
    canais: dict,
    config_canal: dict,
) -> str:
    """
    Monta corpo do email em texto puro.
    Tom e postura lidos de guia_comunicacao_empresa.json.
    Assinatura lida de assinaturas_empresa.json.
    """
    abordagem   = execucao.get("abordagem_inicial_tipo", "padrao")
    ctx         = payload.get("contexto_oportunidade", {}) if payload else {}
    contraparte = (execucao.get("contraparte") or ctx.get("contraparte", "Prezado(a)")).strip()
    cidade      = ctx.get("cidade", "")
    categoria   = ctx.get("categoria", "")
    linha       = execucao.get("linha_servico_sugerida", "")

    roteiro     = payload.get("roteiro_base", "") if payload else ""
    proxima_acao = payload.get("acao_sugerida", "") if payload else ""

    nome_empresa = identidade.get("nome_exibicao") or identidade.get("nome_oficial", "")
    postura      = guia.get("estilo_abertura", "direto ao ponto")
    fechamento   = guia.get("estilo_fechamento", "ação clara, sem pressão")

    # Saudação
    saudacao = f"Olá, equipe {contraparte}," if contraparte else "Prezado(a),"

    # Corpo principal por abordagem
    if abordagem == "exploratoria":
        loc = f" em {cidade}" if cidade else ""
        cat_str = f" de {categoria}" if categoria else ""
        corpo_principal = (
            f"Pesquisamos estabelecimentos{cat_str}{loc} e identificamos uma oportunidade "
            f"de melhoria de presença digital para {contraparte}.\n\n"
        )
        if roteiro:
            corpo_principal += f"{_limpar_roteiro(roteiro)}\n\n"
        else:
            corpo_principal += (
                "Muitos negócios locais perdem clientes simplesmente porque não aparecem quando alguém "
                "pesquisa no Google. Com algumas melhorias simples, isso muda.\n\n"
            )
        corpo_principal += (
            "Se quiser entender o que identificamos especificamente para seu negócio, "
            "é só responder este e-mail ou entrar em contato pelo canal mais conveniente.\n"
        )

    elif abordagem == "consultiva_diagnostica":
        corpo_principal = (
            f"Realizamos uma análise de presença digital de {contraparte} e encontramos "
            f"pontos específicos que podem ser melhorados.\n\n"
        )
        if roteiro:
            corpo_principal += f"{_limpar_roteiro(roteiro)}\n\n"
        corpo_principal += (
            "Podemos detalhar cada ponto identificado e apresentar como seria a solução "
            "prática para cada um — sem compromisso e sem custo inicial.\n"
        )

    elif abordagem in ("followup_sem_resposta", "reengajamento"):
        corpo_principal = (
            f"Tentamos contato anteriormente e não conseguimos falar com a equipe de {contraparte}.\n\n"
            "Deixamos em aberto a possibilidade de conversa sobre como melhorar a presença digital do negócio. "
            "Se o momento não for ideal, tudo bem — é só nos avisar.\n"
        )

    else:
        corpo_principal = (
            f"{roteiro}\n\n" if roteiro
            else "Identificamos uma oportunidade de melhoria digital para seu negócio.\n\n"
        )

    # Assinatura
    assinatura_tipo = config_canal.get("assinatura_tipo_padrao", "comercial")
    nome_remetente = (
        config_canal.get("nome_remetente")
        or assinaturas.get("nome_remetente_padrao", nome_empresa)
    )
    cargo     = assinaturas.get("cargo_remetente_padrao", "")
    email_rem = (
        config_canal.get("email_remetente_planejado")
        or canais.get("email_comercial_planejado", "")
    )
    wa        = canais.get("whatsapp_oficial", "")

    assinatura_linhas = [f"\n---\n{nome_remetente}"]
    if cargo:
        assinatura_linhas.append(cargo)
    assinatura_linhas.append(nome_empresa)
    if email_rem:
        assinatura_linhas.append(email_rem)
    if wa:
        assinatura_linhas.append(f"WhatsApp: {wa}")
    assinatura = "\n".join(assinatura_linhas)

    return f"{saudacao}\n\n{corpo_principal}\n{assinatura}"


def montar_corpo_email_html_opcional(corpo_texto: str, config_canal: dict) -> str:
    """
    Versão HTML simples do corpo, se usar_html=True.
    Caso contrário, retorna string vazia.
    """
    if not config_canal.get("usar_html", False):
        return ""
    linhas = corpo_texto.split("\n")
    html_linhas = []
    for linha in linhas:
        if linha.strip() == "---":
            html_linhas.append("<hr>")
        elif linha.strip():
            html_linhas.append(f"<p>{linha}</p>")
    return "\n".join(html_linhas)


def _limpar_roteiro(roteiro: str) -> str:
    """Remove prefixos de instrução interna do roteiro antes de usar no corpo."""
    prefixos_remover = [
        "Executar email para", "Registrar resultado em historico_abordagens.json.",
    ]
    resultado = roteiro
    for prefixo in prefixos_remover:
        if resultado.startswith(prefixo):
            resultado = resultado[len(prefixo):].strip()
    return resultado.strip()


# ─── Preparação do email ──────────────────────────────────────────────────────

def preparar_email_para_execucao(
    execucao: dict,
    identidade: dict,
    guia: dict,
    assinaturas: dict,
    canais: dict,
    config_canal: dict,
) -> dict:
    """
    Prepara o dict completo do email para um item de execução.

    Retorna dict com todos os campos de fila_envio_email.json.
    Não persiste — apenas monta. A persistência é feita pelo integrador_email.
    """
    from datetime import datetime
    import uuid

    agora   = datetime.now().isoformat(timespec="seconds")
    payload = execucao.get("payload_execucao", {}) or {}

    # Validar identidade
    ok, motivo_bloqueio = validar_identidade_para_email(identidade, canais, config_canal)

    # Email destino
    email_destino = (
        payload.get("contato_destino", "")
        if payload.get("canal") == "email" or execucao.get("canal") == "email"
        else ""
    )
    if config_canal.get("exigir_email_destino", True) and not email_destino:
        ok = False
        motivo_bloqueio = motivo_bloqueio or "email_destino ausente no payload"

    # Remetente
    email_remetente = (
        config_canal.get("email_remetente_planejado")
        or canais.get("email_comercial_planejado")
        or canais.get("email_principal_planejado", "")
    )
    nome_remetente = (
        config_canal.get("nome_remetente")
        or assinaturas.get("nome_remetente_padrao", "")
    )

    email_id = f"email_{execucao['id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    if ok:
        assunto    = montar_assunto_email(execucao, payload, identidade, config_canal)
        corpo      = montar_corpo_email_texto(execucao, payload, identidade, guia, assinaturas, canais, config_canal)
        corpo_html = montar_corpo_email_html_opcional(corpo, config_canal)
        status     = "preparado"
        pronto     = True
    else:
        assunto    = ""
        corpo      = ""
        corpo_html = ""
        status     = "bloqueado"
        pronto     = False

    return {
        "id":                     email_id,
        "execucao_id":            execucao["id"],
        "oportunidade_id":        execucao.get("oportunidade_id", ""),
        "contraparte":            execucao.get("contraparte", ""),
        "email_destino":          email_destino,
        "assunto":                assunto,
        "corpo_texto":            corpo,
        "corpo_html_opcional":    corpo_html,
        "remetente_nome":         nome_remetente,
        "remetente_email_planejado": email_remetente,
        "responder_para":         config_canal.get("responder_para_planejado", email_remetente),
        "assinatura_tipo":        config_canal.get("assinatura_tipo_padrao", "comercial"),
        "abordagem_tipo":         execucao.get("abordagem_inicial_tipo", "padrao"),
        "linha_servico":          execucao.get("linha_servico_sugerida", ""),
        "status":                 status,
        "motivo_bloqueio":        motivo_bloqueio if not ok else None,
        "pronto_para_envio":      pronto,
        "simulado":               True,   # sempre True nesta etapa (sem envio real)
        "modo_canal":             config_canal.get("modo", "assistido"),
        "criado_em":              agora,
        "atualizado_em":          agora,
    }


# ─── Histórico ────────────────────────────────────────────────────────────────

def registrar_historico_email(
    hist: list,
    tipo_evento: str,
    execucao_id: str,
    oportunidade_id: str,
    descricao: str,
    status: str,
) -> None:
    """Adiciona evento ao historico_email (in-place)."""
    from datetime import datetime
    import uuid
    hist.append({
        "id":              str(uuid.uuid4())[:8],
        "tipo_evento":     tipo_evento,
        "execucao_id":     execucao_id,
        "oportunidade_id": oportunidade_id,
        "descricao":       descricao,
        "status":          status,
        "registrado_em":   datetime.now().isoformat(timespec="seconds"),
    })
