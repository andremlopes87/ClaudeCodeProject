"""
core/expediente_documentos_email.py

Camada de expediente de envio de documentos oficiais por email assistido.

Liga documentos gerados (proposta/contrato) ao canal de email assistido:
  documento gerado → preparar_envio_documento()
                   → enfileirar_documento_no_email_assistido()
                   → marcar_documento_como_enviado()

Sem SMTP real. Modo totalmente assistido.
Segue o mesmo padrão de core/expediente_propostas.py.

Arquivos gerenciados:
  dados/envios_documentos.json
  dados/historico_envios_documentos.json

Reutiliza:
  dados/documentos_oficiais.json
  dados/propostas_comerciais.json
  dados/contratos_clientes.json
  dados/contas_clientes.json
  dados/fila_envio_email.json
  dados/historico_email.json
  core/identidade_empresa.py
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_ENVIOS    = config.PASTA_DADOS / "envios_documentos.json"
_ARQ_HIST      = config.PASTA_DADOS / "historico_envios_documentos.json"
_ARQ_DOCS      = config.PASTA_DADOS / "documentos_oficiais.json"
_ARQ_PROPOSTAS = config.PASTA_DADOS / "propostas_comerciais.json"
_ARQ_CONTRATOS = config.PASTA_DADOS / "contratos_clientes.json"
_ARQ_CONTAS    = config.PASTA_DADOS / "contas_clientes.json"
_ARQ_FILA_EMAIL = config.PASTA_DADOS / "fila_envio_email.json"
_ARQ_HIST_EMAIL = config.PASTA_DADOS / "historico_email.json"

# Tipos de documento que geram envio por email
_TIPOS_COM_ENVIO = {"proposta_comercial", "contrato_comercial"}

# Status elegíveis por tipo de documento-fonte
_STATUS_PROP_ELEGIVEL = {"aprovada_para_envio", "preparada_para_envio", "enviada"}
_STATUS_CT_ELEGIVEL   = {"aguardando_ativacao", "ativo"}


# ─── I/O ──────────────────────────────────────────────────────────────────────

def _ler(arq: Path, padrao):
    try:
        if arq.exists():
            with open(arq, encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        log.warning(f"[exp_docs_email] falha ao ler {arq.name}: {exc}")
    return padrao


def _salvar(arq: Path, dados) -> None:
    try:
        arq.parent.mkdir(parents=True, exist_ok=True)
        with open(arq, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.warning(f"[exp_docs_email] falha ao salvar {arq.name}: {exc}")


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def carregar_envios_documentos() -> list:
    return _ler(_ARQ_ENVIOS, [])


# ─── Busca de email do destinatário ───────────────────────────────────────────

def _resolver_email_destino(doc: dict) -> str:
    """
    Tenta resolver o email do destinatário para o documento.
    Ordem: proposta.email_destino → conta.email_comercial → contrato.email_comercial.
    """
    email = ""

    # Via proposta
    if doc.get("proposta_id"):
        props = _ler(_ARQ_PROPOSTAS, [])
        prop = next((p for p in props if p.get("id") == doc["proposta_id"]), None)
        if prop:
            email = prop.get("email_destino", "")

    # Via conta
    if not email and doc.get("conta_id"):
        contas = _ler(_ARQ_CONTAS, [])
        conta = next((c for c in contas if c.get("id") == doc["conta_id"]), None)
        if conta:
            email = conta.get("email_comercial", "") or conta.get("email", "")

    # Via contrato
    if not email and doc.get("contrato_id"):
        cts = _ler(_ARQ_CONTRATOS, [])
        ct = next((c for c in cts if c.get("id") == doc["contrato_id"]), None)
        if ct:
            # tenta pela conta do contrato
            if ct.get("conta_id"):
                contas = _ler(_ARQ_CONTAS, [])
                conta = next((c for c in contas if c.get("id") == ct["conta_id"]), None)
                if conta:
                    email = conta.get("email_comercial", "") or conta.get("email", "")

    return email.strip()


# ─── Montagem do email ────────────────────────────────────────────────────────

def _montar_email_de_documento(
    doc: dict,
    config_canal: dict,
) -> dict:
    """
    Monta dict de email para um documento oficial.
    Retorna campos compatíveis com fila_envio_email.json.
    """
    try:
        from core.identidade_empresa import (
            carregar_identidade, carregar_assinaturas, carregar_canais,
        )
        identidade  = carregar_identidade()
        assinaturas = carregar_assinaturas()
        canais      = carregar_canais()
    except Exception as exc:
        log.warning(f"[exp_docs_email] identidade indisponível: {exc}")
        identidade  = {}
        assinaturas = {}
        canais      = {}

    empresa_nome = (
        identidade.get("nome_exibicao") or
        identidade.get("nome_oficial", "Vetor")
    )

    # Remetente
    email_remetente = (
        config_canal.get("email_remetente_planejado")
        or canais.get("email_comercial_planejado")
        or canais.get("email_principal_planejado", "")
    )
    nome_remetente = (
        config_canal.get("nome_remetente")
        or assinaturas.get("nome_remetente_padrao", "")
        or empresa_nome
    )

    assinatura_texto = (
        assinaturas.get("assinaturas", {}).get("comercial", {}).get("texto_completo", "")
        or f"{nome_remetente}\n{empresa_nome}"
    )

    email_destino = _resolver_email_destino(doc)
    tipo_doc      = doc.get("tipo_documento", "")
    titulo        = doc.get("titulo", "—")
    contraparte   = titulo.split("—")[-1].strip() if "—" in titulo else "Cliente"
    caminho_doc   = doc.get("caminho_arquivo", "")
    versao        = doc.get("versao", 1)

    # Conteúdo específico por tipo
    if tipo_doc == "proposta_comercial":
        assunto = f"Proposta Comercial — {contraparte}"
        contexto = ""
        if doc.get("proposta_id"):
            props = _ler(_ARQ_PROPOSTAS, [])
            prop  = next((p for p in props if p.get("id") == doc["proposta_id"]), None)
            if prop:
                valor = prop.get("proposta_valor", 0)
                prazo = prop.get("prazo_referencia", "?")
                contexto = (
                    f"Oferta: {prop.get('oferta_nome', '—')}\n"
                    f"Valor: R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    + f" | Prazo: {prazo} dias úteis"
                )
        corpo_texto = (
            f"Olá, {contraparte}.\n\n"
            f"Segue nossa proposta comercial conforme alinhado.\n\n"
            f"{contexto}\n\n"
            f"O documento completo (versão {versao}) está disponível em:\n"
            f"{caminho_doc}\n\n"
            f"Para confirmar o interesse ou discutir ajustes, entre em contato.\n\n"
            f"--\n{assinatura_texto}"
        )
        abordagem_tipo = "proposta_comercial"

    elif tipo_doc == "contrato_comercial":
        assunto = f"Compromisso Comercial — {contraparte}"
        contexto = ""
        if doc.get("contrato_id"):
            cts = _ler(_ARQ_CONTRATOS, [])
            ct  = next((c for c in cts if c.get("id") == doc["contrato_id"]), None)
            if ct:
                valor = ct.get("valor_total", 0)
                contexto = (
                    f"Serviço: {ct.get('oferta_nome', '—')}\n"
                    f"Valor total: R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                )
        corpo_texto = (
            f"Olá, {contraparte}.\n\n"
            f"Segue nosso compromisso comercial para formalização do serviço contratado.\n\n"
            f"{contexto}\n\n"
            f"O documento completo (versão {versao}) está disponível em:\n"
            f"{caminho_doc}\n\n"
            f"Confirme o recebimento respondendo a este email.\n\n"
            f"--\n{assinatura_texto}"
        )
        abordagem_tipo = "contrato_comercial"

    else:
        assunto = f"Documento Oficial — {contraparte}"
        corpo_texto = (
            f"Olá, {contraparte}.\n\n"
            f"Segue documento oficial: {titulo}\n\n"
            f"Disponível em: {caminho_doc}\n\n"
            f"--\n{assinatura_texto}"
        )
        abordagem_tipo = "documento_oficial"

    # Status: bloqueado se sem email destino
    if not email_destino:
        status = "bloqueado"
        motivo = "email_destino ausente — verificar conta ou proposta"
    else:
        status = "preparado"
        motivo = None

    return {
        "email_destino":             email_destino,
        "assunto":                   assunto,
        "corpo_texto":               corpo_texto.strip(),
        "remetente_nome":            nome_remetente,
        "remetente_email_planejado": email_remetente,
        "responder_para":            config_canal.get("responder_para_planejado", email_remetente),
        "abordagem_tipo":            abordagem_tipo,
        "status":                    status,
        "motivo_bloqueio":           motivo,
    }


# ─── Criar envio de documento ─────────────────────────────────────────────────

def preparar_envio_documento(
    doc_id: str,
    config_canal: dict | None = None,
    origem: str = "expediente_documentos",
) -> "dict | None":
    """
    Cria registro de envio em envios_documentos.json para um documento oficial.
    Não adiciona à fila_envio_email ainda — isso é feito por enfileirar_documento_no_email_assistido().
    Idempotente: retorna envio existente se já preparado para o mesmo doc_id.
    """
    docs = _ler(_ARQ_DOCS, [])
    doc  = next((d for d in docs if d.get("id") == doc_id), None)
    if not doc:
        log.warning(f"[exp_docs_email] documento {doc_id} não encontrado")
        return None

    tipo_doc = doc.get("tipo_documento", "")
    if tipo_doc not in _TIPOS_COM_ENVIO:
        log.debug(f"[exp_docs_email] tipo {tipo_doc} não gera envio por email")
        return None

    # Idempotência: verificar se já existe envio ativo para este doc_id
    envios = carregar_envios_documentos()
    existente = next(
        (e for e in envios
         if e.get("documento_id") == doc_id
         and e.get("status") not in {"cancelado"}),
        None,
    )
    if existente:
        log.debug(f"[exp_docs_email] envio já existe para {doc_id}: {existente['id']}")
        return existente

    if config_canal is None:
        try:
            from core.integrador_email import carregar_config_canal_email
            config_canal = carregar_config_canal_email()
        except Exception:
            config_canal = {}

    agora    = _agora()
    envio_id = f"env_doc_{uuid.uuid4().hex[:8]}"
    email    = _montar_email_de_documento(doc, config_canal)

    envio = {
        "id":               envio_id,
        "documento_id":     doc_id,
        "tipo_documento":   tipo_doc,
        "referencia_id":    doc.get("referencia_id", ""),
        "proposta_id":      doc.get("proposta_id", ""),
        "contrato_id":      doc.get("contrato_id", ""),
        "contraparte":      doc.get("titulo", "").split("—")[-1].strip() if "—" in doc.get("titulo", "") else "",
        "destinatario":     email["email_destino"],
        "assunto":          email["assunto"],
        "corpo_texto":      email["corpo_texto"],
        "remetente_nome":   email["remetente_nome"],
        "remetente_email":  email["remetente_email_planejado"],
        "caminho_documento": doc.get("caminho_arquivo", ""),
        "status":           "preparado" if email["status"] == "preparado" else "bloqueado",
        "motivo_bloqueio":  email.get("motivo_bloqueio"),
        "fila_email_id":    None,
        "preparado_em":     agora,
        "enviado_em":       None,
        "atualizado_em":    agora,
        "gerado_por":       origem,
    }

    envios.append(envio)
    _salvar(_ARQ_ENVIOS, envios)

    _registrar_historico(
        envio_id, "envio_documento_preparado",
        f"{tipo_doc} | {doc.get('titulo', '?')} | status={envio['status']} "
        f"| destino={email['email_destino'] or 'sem email'}",
        origem,
    )

    log.info(
        f"[exp_docs_email] envio {envio_id} preparado para {doc_id} "
        f"({doc.get('titulo', '?')}) — status={envio['status']}"
    )
    return envio


# ─── Enfileirar no email assistido ───────────────────────────────────────────

def enfileirar_documento_no_email_assistido(
    envio: dict,
    origem: str = "expediente_documentos",
) -> dict:
    """
    Adiciona envio de documento à fila_envio_email.json.
    Retorna o item de fila criado ou {} se bloqueado/já enfileirado.
    """
    if envio.get("status") == "bloqueado":
        log.warning(
            f"[exp_docs_email] envio {envio['id']} bloqueado "
            f"({envio.get('motivo_bloqueio')}) — não enfileirando"
        )
        return {}

    fila = _ler(_ARQ_FILA_EMAIL, [])
    # Dedup por envio_documento_id
    if any(f.get("envio_documento_id") == envio["id"] for f in fila):
        log.info(f"[exp_docs_email] envio {envio['id']} já está na fila — ignorando")
        return {}

    agora   = _agora()
    fila_id = f"email_doc_{envio['id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    item_fila = {
        "id":                        fila_id,
        "execucao_id":               envio["id"],
        "oportunidade_id":           "",
        "contraparte":               envio.get("contraparte", ""),
        "email_destino":             envio.get("destinatario", ""),
        "assunto":                   envio["assunto"],
        "corpo_texto":               envio["corpo_texto"],
        "corpo_html_opcional":       "",
        "remetente_nome":            envio.get("remetente_nome", ""),
        "remetente_email_planejado": envio.get("remetente_email", ""),
        "responder_para":            envio.get("remetente_email", ""),
        "assinatura_tipo":           "comercial",
        "abordagem_tipo":            "documento_oficial",
        "linha_servico":             "",
        "status":                    "preparado",
        "motivo_bloqueio":           None,
        "pronto_para_envio":         True,
        "simulado":                  True,
        "modo_canal":                "assistido",
        # Rastreabilidade de documento oficial
        "tipo_envio":                "documento_oficial",
        "documento_id":              envio["documento_id"],
        "proposta_id":               envio.get("proposta_id", ""),
        "contrato_id":               envio.get("contrato_id", ""),
        "envio_documento_id":        envio["id"],
        "origem_envio":              "expediente_documentos",
        "criado_em":                 agora,
        "atualizado_em":             agora,
    }

    fila.append(item_fila)
    _salvar(_ARQ_FILA_EMAIL, fila)

    # Atualizar envio com fila_email_id e status
    envios = carregar_envios_documentos()
    for e in envios:
        if e["id"] == envio["id"]:
            e["fila_email_id"] = fila_id
            e["status"]        = "em_fila_assistida"
            e["atualizado_em"] = agora
            break
    _salvar(_ARQ_ENVIOS, envios)

    # Histórico email
    hist_email = _ler(_ARQ_HIST_EMAIL, [])
    hist_email.append({
        "id":              uuid.uuid4().hex[:8],
        "tipo_evento":     "documento_enfileirado_email",
        "execucao_id":     envio["id"],
        "oportunidade_id": "",
        "documento_id":    envio["documento_id"],
        "proposta_id":     envio.get("proposta_id", ""),
        "contrato_id":     envio.get("contrato_id", ""),
        "descricao":       f"Documento {envio['documento_id']} enfileirado para {envio.get('contraparte', '?')}",
        "status":          "preparado",
        "simulado":        True,
        "registrado_em":   agora,
    })
    _salvar(_ARQ_HIST_EMAIL, hist_email)

    _registrar_historico(
        envio["id"], "envio_documento_enfileirado",
        f"Item {fila_id} adicionado à fila assistida",
        origem,
    )

    log.info(
        f"[exp_docs_email] documento {envio['documento_id']} enfileirado: {fila_id}"
    )
    return item_fila


# ─── Marcar como enviado ──────────────────────────────────────────────────────

def marcar_documento_como_enviado(
    envio_doc_id: str,
    origem: str = "conselho_painel",
) -> tuple[bool, str]:
    """Marca envio de documento como enviado (registro manual)."""
    agora  = _agora()
    envios = carregar_envios_documentos()
    envio  = next((e for e in envios if e["id"] == envio_doc_id), None)
    if not envio:
        return False, f"envio {envio_doc_id} não encontrado"

    if envio["status"] in {"cancelado"}:
        return False, f"envio em status final: {envio['status']}"

    envio["status"]      = "marcado_como_enviado"
    envio["enviado_em"]  = agora
    envio["atualizado_em"] = agora
    _salvar(_ARQ_ENVIOS, envios)

    _registrar_historico(
        envio_doc_id, "envio_documento_marcado_enviado",
        f"Envio registrado manualmente por {origem}",
        origem,
    )
    log.info(f"[exp_docs_email] envio {envio_doc_id} marcado como enviado por {origem}")
    return True, ""


# ─── Histórico de envios ──────────────────────────────────────────────────────

def _registrar_historico(
    envio_id: str, evento: str, descricao: str, origem: str
) -> None:
    historico = _ler(_ARQ_HIST, [])
    historico.append({
        "id":          uuid.uuid4().hex[:8],
        "envio_id":    envio_id,
        "evento":      evento,
        "descricao":   descricao,
        "origem":      origem,
        "registrado_em": _agora(),
    })
    _salvar(_ARQ_HIST, historico)


# ─── Processar documentos elegíveis em lote ───────────────────────────────────

def processar_documentos_elegiveis(origem: str = "expediente_documentos") -> dict:
    """
    Lê documentos gerados elegíveis e prepara envio para os que ainda não têm envio ativo.
    Chamado opcionalmente durante o ciclo.
    """
    docs   = _ler(_ARQ_DOCS, [])
    n_prep = 0
    n_bloq = 0
    n_skip = 0

    try:
        from core.integrador_email import carregar_config_canal_email
        config_canal = carregar_config_canal_email()
    except Exception:
        config_canal = {}

    envios_ativos = {
        e["documento_id"] for e in carregar_envios_documentos()
        if e.get("status") not in {"cancelado"}
    }

    for doc in docs:
        tipo_doc = doc.get("tipo_documento", "")
        if tipo_doc not in _TIPOS_COM_ENVIO:
            continue
        if doc.get("status") in ("arquivado", "obsoleto"):
            continue
        doc_id = doc.get("id", "")
        if not doc_id or doc_id in envios_ativos:
            n_skip += 1
            continue

        # Verificar elegibilidade da fonte
        elegivel = False
        if tipo_doc == "proposta_comercial" and doc.get("proposta_id"):
            props = _ler(_ARQ_PROPOSTAS, [])
            prop  = next((p for p in props if p.get("id") == doc["proposta_id"]), None)
            if prop and prop.get("status") in _STATUS_PROP_ELEGIVEL:
                elegivel = True
        elif tipo_doc == "contrato_comercial" and doc.get("contrato_id"):
            cts = _ler(_ARQ_CONTRATOS, [])
            ct  = next((c for c in cts if c.get("id") == doc["contrato_id"]), None)
            if ct and ct.get("status") in _STATUS_CT_ELEGIVEL:
                elegivel = True

        if not elegivel:
            continue

        envio = preparar_envio_documento(doc_id, config_canal, origem)
        if envio:
            if envio.get("status") == "preparado":
                n_prep += 1
            else:
                n_bloq += 1

    log.info(
        f"[exp_docs_email] batch: {n_prep} preparados | "
        f"{n_bloq} bloqueados | {n_skip} ignorados"
    )
    return {"preparados": n_prep, "bloqueados": n_bloq, "ignorados": n_skip}


# ─── KPIs para painel ────────────────────────────────────────────────────────

def resumir_para_painel() -> dict:
    envios = carregar_envios_documentos()
    total        = len(envios)
    preparados   = sum(1 for e in envios if e.get("status") == "preparado")
    em_fila      = sum(1 for e in envios if e.get("status") == "em_fila_assistida")
    enviados     = sum(1 for e in envios if e.get("status") == "marcado_como_enviado")
    bloqueados   = sum(1 for e in envios if e.get("status") == "bloqueado")
    cancelados   = sum(1 for e in envios if e.get("status") == "cancelado")
    return {
        "total_envios_documentos":  total,
        "envios_preparados":        preparados,
        "envios_em_fila":           em_fila,
        "envios_documentos_enviados": enviados,
        "envios_bloqueados":        bloqueados,
        "envios_cancelados":        cancelados,
    }
