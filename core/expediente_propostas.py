"""
core/expediente_propostas.py

Camada de expediente de propostas comerciais da Vetor.

Fecha o loop: proposta aprovada → preparo de envio → email assistido →
              resposta do cliente registrada → comercial absorve.

Não envia nada. Não inventa resposta. Modo totalmente assistido/manual.

Arquivos gerenciados:
  dados/envios_propostas.json
  dados/respostas_propostas.json
  dados/historico_envios_propostas.json

Reutiliza:
  dados/propostas_comerciais.json
  dados/fila_envio_email.json
  dados/historico_email.json
  core/identidade_empresa.py
  core/propostas_empresa.py
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_ENVIOS    = config.PASTA_DADOS / "envios_propostas.json"
_ARQ_RESPOSTAS = config.PASTA_DADOS / "respostas_propostas.json"
_ARQ_HIST_ENVIO = config.PASTA_DADOS / "historico_envios_propostas.json"
_ARQ_FILA_EMAIL = config.PASTA_DADOS / "fila_envio_email.json"
_ARQ_HIST_EMAIL = config.PASTA_DADOS / "historico_email.json"

_STATUS_ELEGIVEIS_ENVIO = {"aprovada_para_envio", "preparada_para_envio"}
_TIPOS_RESPOSTA_VALIDOS = {
    "aceitou", "recusou", "pediu_ajuste",
    "pediu_retorno_futuro", "sem_resposta", "aceite_verbal_registrado",
}


# ─── I/O ──────────────────────────────────────────────────────────────────────

def _ler(arq: Path, padrao):
    try:
        if arq.exists():
            with open(arq, encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        log.warning(f"[expediente] falha ao ler {arq.name}: {exc}")
    return padrao


def _salvar(arq: Path, dados) -> None:
    try:
        arq.parent.mkdir(parents=True, exist_ok=True)
        with open(arq, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.warning(f"[expediente] falha ao salvar {arq.name}: {exc}")


def carregar_envios() -> list:
    return _ler(_ARQ_ENVIOS, [])


def carregar_respostas() -> list:
    return _ler(_ARQ_RESPOSTAS, [])


# ─── Propostas elegíveis para envio ──────────────────────────────────────────

def carregar_propostas_elegiveis_para_envio() -> list:
    """
    Retorna propostas com status aprovada_para_envio que ainda não têm
    envio ativo (não cancelado/bloqueado).
    """
    from core.propostas_empresa import carregar_propostas
    propostas = carregar_propostas()
    envios    = carregar_envios()

    # IDs de propostas que já têm envio ativo
    ja_com_envio = {
        e["proposta_id"] for e in envios
        if e.get("status") not in {"cancelado", "bloqueado"}
    }

    return [
        p for p in propostas
        if p.get("status") in _STATUS_ELEGIVEIS_ENVIO
        and p["id"] not in ja_com_envio
    ]


# ─── Montagem do email da proposta ───────────────────────────────────────────

def montar_email_de_proposta(proposta: dict, config_canal: dict) -> dict:
    """
    Monta dict de email a partir da proposta.
    Usa assunto/corpo/assinatura da proposta + identidade da empresa.
    Retorna dict compatível com fila_envio_email.json.
    """
    try:
        from core.identidade_empresa import (
            carregar_identidade, carregar_assinaturas, carregar_canais,
        )
        identidade  = carregar_identidade()
        assinaturas = carregar_assinaturas()
        canais      = carregar_canais()
    except Exception as exc:
        log.warning(f"[expediente] identidade indisponível: {exc}")
        identidade  = {}
        assinaturas = {}
        canais      = {}

    agora = datetime.now().isoformat(timespec="seconds")

    # Remetente
    email_remetente = (
        config_canal.get("email_remetente_planejado")
        or canais.get("email_comercial_planejado")
        or canais.get("email_principal_planejado", "")
    )
    nome_remetente = (
        config_canal.get("nome_remetente")
        or assinaturas.get("nome_remetente_padrao", "")
        or identidade.get("nome_exibicao", "Equipe Vetor")
    )

    # Destinatário: email da oportunidade (campo email) — pode estar vazio
    email_destino = proposta.get("email_destino", "") or ""

    # Assunto da proposta
    assunto = proposta.get("texto_assunto") or (
        f"Proposta: {proposta.get('oferta_nome', 'Serviço Vetor')} "
        f"para {proposta.get('contraparte', '')}"
    )

    # Corpo: intro + corpo + entregaveis resumidos + fechamento + assinatura
    entregaveis   = proposta.get("entregaveis", [])
    entregaveis_txt = "\n".join(f"  • {e}" for e in entregaveis[:6]) if entregaveis else ""

    premissas     = proposta.get("premissas", [])
    fora_escopo   = proposta.get("fora_do_escopo", [])
    valor_fmt     = (
        f"R$ {float(proposta['proposta_valor']):,.0f}".replace(",", ".")
        if proposta.get("proposta_valor") else "a definir"
    )
    prazo_fmt     = f"{proposta.get('prazo_referencia', '?')} dias úteis"

    assinatura_padrao = (
        assinaturas.get("assinaturas", {}).get("comercial", {}).get("texto_completo", "")
        or f"{nome_remetente}\nVetor Operações Ltda"
    )

    partes = []
    if proposta.get("texto_intro"):
        partes.append(proposta["texto_intro"])
    partes.append("")

    if proposta.get("resumo_problema"):
        partes.append(f"Contexto identificado:\n{proposta['resumo_problema']}")
        partes.append("")

    partes.append(f"Escopo: {proposta.get('escopo', '')}")
    partes.append("")

    if entregaveis_txt:
        partes.append("Entregáveis incluídos:\n" + entregaveis_txt)
        partes.append("")

    if proposta.get("texto_corpo"):
        partes.append(proposta["texto_corpo"])
        partes.append("")

    partes.append(f"Investimento: {valor_fmt}")
    partes.append(f"Prazo estimado: {prazo_fmt}")
    partes.append("")

    if premissas:
        partes.append("Premissas:\n" + "\n".join(f"  • {p}" for p in premissas[:3]))
        partes.append("")

    if fora_escopo:
        partes.append("Fora do escopo:\n" + "\n".join(f"  • {f}" for f in fora_escopo[:3]))
        partes.append("")

    if proposta.get("texto_fechamento"):
        partes.append(proposta["texto_fechamento"])
        partes.append("")

    partes.append("--")
    partes.append(assinatura_padrao)

    corpo_texto = "\n".join(partes)

    # Status: bloqueado se sem email destino
    if not email_destino:
        status = "bloqueado"
        motivo = "email_destino ausente — adicionar email do contato antes de enfileirar"
    else:
        status = "preparado"
        motivo = None

    return {
        "email_destino":             email_destino,
        "assunto":                   assunto,
        "corpo_texto":               corpo_texto,
        "corpo_html_opcional":       "",
        "remetente_nome":            nome_remetente,
        "remetente_email_planejado": email_remetente,
        "responder_para":            config_canal.get("responder_para_planejado", email_remetente),
        "status":                    status,
        "motivo_bloqueio":           motivo,
    }


# ─── Criar envio de proposta ──────────────────────────────────────────────────

def criar_envio_proposta(
    proposta: dict,
    config_canal: dict | None = None,
    origem: str = "expediente_propostas",
) -> dict:
    """
    Cria registro de envio em envios_propostas.json.
    Monta o email e o inclui no registro.
    Não adiciona à fila_envio_email.json ainda — isso é feito por enfileirar_proposta_no_email_assistido().
    """
    if config_canal is None:
        config_canal = _ler_config_canal()

    agora    = datetime.now().isoformat(timespec="seconds")
    envio_id = f"env_{str(uuid.uuid4())[:8]}"
    email    = montar_email_de_proposta(proposta, config_canal)

    envio = {
        "id":                   envio_id,
        "proposta_id":          proposta["id"],
        "oportunidade_id":      proposta.get("oportunidade_id", ""),
        "contraparte":          proposta.get("contraparte", ""),
        "canal":                "email",
        "destinatario":         email["email_destino"],
        "assunto":              email["assunto"],
        "corpo_texto":          email["corpo_texto"],
        "corpo_html_opcional":  email["corpo_html_opcional"],
        "remetente_nome":       email["remetente_nome"],
        "remetente_email":      email["remetente_email_planejado"],
        "status":               "preparado" if email["status"] == "preparado" else "bloqueado",
        "motivo_bloqueio":      email.get("motivo_bloqueio"),
        "fila_email_id":        None,  # preenchido ao enfileirar
        "preparado_em":         agora,
        "enviado_em":           None,
        "respondido_em":        None,
        "atualizado_em":        agora,
        "gerado_por":           origem,
    }

    # Atualizar status da proposta para preparada_para_envio
    from core.propostas_empresa import carregar_propostas, salvar_propostas, registrar_historico_proposta
    propostas = carregar_propostas()
    for p in propostas:
        if p["id"] == proposta["id"]:
            p["status"]       = "preparada_para_envio"
            p["atualizada_em"] = agora
            break
    salvar_propostas(propostas)

    # Persistir envio
    envios = carregar_envios()
    envios.append(envio)
    _salvar(_ARQ_ENVIOS, envios)

    registrar_historico_envio_proposta(
        envio_id, "envio_proposta_criado",
        f"Envio criado para {proposta.get('contraparte')} | "
        f"status={envio['status']} | email={email['email_destino'] or 'sem email'}",
        origem=origem,
    )
    registrar_historico_proposta(
        proposta["id"], "proposta_preparada_para_envio",
        f"Envio {envio_id} preparado | status={envio['status']}",
        origem=origem,
    )

    log.info(
        f"[expediente] envio {envio_id} criado para proposta "
        f"{proposta['id']} ({proposta.get('contraparte')}) — status={envio['status']}"
    )
    return envio


# ─── Enfileirar no email assistido ───────────────────────────────────────────

def enfileirar_proposta_no_email_assistido(
    envio: dict,
    origem: str = "expediente_propostas",
) -> dict:
    """
    Adiciona envio à fila_envio_email.json com campos extras de rastreabilidade.
    Retorna o item de fila criado.
    """
    if envio.get("status") == "bloqueado":
        log.warning(
            f"[expediente] envio {envio['id']} bloqueado "
            f"({envio.get('motivo_bloqueio')}) — não enfileirando"
        )
        return {}

    agora     = datetime.now().isoformat(timespec="seconds")
    fila_id   = f"email_prop_{envio['id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    item_fila = {
        "id":                        fila_id,
        "execucao_id":               envio["id"],          # compatibilidade com visualizador
        "oportunidade_id":           envio.get("oportunidade_id", ""),
        "contraparte":               envio.get("contraparte", ""),
        "email_destino":             envio.get("destinatario", ""),
        "assunto":                   envio["assunto"],
        "corpo_texto":               envio["corpo_texto"],
        "corpo_html_opcional":       envio.get("corpo_html_opcional", ""),
        "remetente_nome":            envio.get("remetente_nome", ""),
        "remetente_email_planejado": envio.get("remetente_email", ""),
        "responder_para":            envio.get("remetente_email", ""),
        "assinatura_tipo":           "comercial",
        "abordagem_tipo":            "proposta_comercial",
        "linha_servico":             "",
        "status":                    "preparado",
        "motivo_bloqueio":           None,
        "pronto_para_envio":         True,
        "simulado":                  True,
        "modo_canal":                "assistido",
        # Campos extras de rastreabilidade de proposta
        "tipo_envio":                "proposta_comercial",
        "proposta_id":               envio["proposta_id"],
        "envio_proposta_id":         envio["id"],
        "origem_envio":              "expediente_propostas",
        "criado_em":                 agora,
        "atualizado_em":             agora,
    }

    fila = _ler(_ARQ_FILA_EMAIL, [])
    # Dedup por envio_proposta_id
    if any(f.get("envio_proposta_id") == envio["id"] for f in fila):
        log.info(f"[expediente] envio {envio['id']} já está na fila — ignorando")
        return {}

    fila.append(item_fila)
    _salvar(_ARQ_FILA_EMAIL, fila)

    # Atualizar envio com fila_email_id e status
    envios = carregar_envios()
    for e in envios:
        if e["id"] == envio["id"]:
            e["fila_email_id"] = fila_id
            e["status"]        = "em_fila_assistida"
            e["atualizada_em"] = agora
            break
    _salvar(_ARQ_ENVIOS, envios)

    # Atualizar proposta
    from core.propostas_empresa import carregar_propostas, salvar_propostas, registrar_historico_proposta
    propostas = carregar_propostas()
    for p in propostas:
        if p["id"] == envio["proposta_id"]:
            p["atualizada_em"] = agora
            break
    salvar_propostas(propostas)

    # Histórico email (compatível com historico_email.json)
    hist_email = _ler(_ARQ_HIST_EMAIL, [])
    hist_email.append({
        "id":               str(uuid.uuid4())[:8],
        "tipo_evento":      "proposta_enfileirada_email",
        "execucao_id":      envio["id"],
        "oportunidade_id":  envio.get("oportunidade_id", ""),
        "proposta_id":      envio["proposta_id"],
        "descricao":        f"Proposta {envio['proposta_id']} enfileirada para {envio.get('contraparte')}",
        "status":           "preparado",
        "simulado":         True,
        "registrado_em":    agora,
    })
    _salvar(_ARQ_HIST_EMAIL, hist_email)

    registrar_historico_envio_proposta(
        envio["id"], "envio_proposta_enfileirado_email",
        f"Item {fila_id} adicionado à fila assistida",
        origem=origem,
    )
    registrar_historico_proposta(
        envio["proposta_id"], "proposta_enfileirada_email",
        f"Fila email: {fila_id}",
        origem=origem,
    )

    log.info(f"[expediente] proposta {envio['proposta_id']} enfileirada: {fila_id}")
    return item_fila


# ─── Marcar como enviada ──────────────────────────────────────────────────────

def marcar_envio_como_enviado(
    proposta_id: str,
    origem: str = "conselho_painel",
) -> tuple[bool, str]:
    """
    Marca proposta e envio como 'enviada' (registro manual de envio externo).
    """
    from core.propostas_empresa import carregar_propostas, salvar_propostas, registrar_historico_proposta
    agora    = datetime.now().isoformat(timespec="seconds")
    propostas = carregar_propostas()
    envios    = carregar_envios()

    prop = next((p for p in propostas if p["id"] == proposta_id), None)
    if not prop:
        return False, f"proposta {proposta_id} não encontrada"

    if prop["status"] in {"aceita", "rejeitada", "arquivada"}:
        return False, f"proposta já em status final: {prop['status']}"

    prop["status"]       = "enviada"
    prop["atualizada_em"] = agora
    salvar_propostas(propostas)

    # Atualizar envio correspondente
    for e in envios:
        if e.get("proposta_id") == proposta_id and e.get("status") not in {"cancelado"}:
            e["status"]      = "enviado_manual_registrado"
            e["enviado_em"]  = agora
            e["atualizada_em"] = agora
            break
    _salvar(_ARQ_ENVIOS, envios)

    registrar_historico_proposta(
        proposta_id, "proposta_marcada_como_enviada",
        f"Envio registrado manualmente por {origem}",
        origem=origem,
    )
    log.info(f"[expediente] proposta {proposta_id} marcada como enviada por {origem}")
    return True, ""


# ─── Registrar resposta do cliente ───────────────────────────────────────────

def registrar_resposta_proposta(
    proposta_id: str,
    tipo_resposta: str,
    descricao: str = "",
    origem: str = "conselho_painel",
    observacoes: str = "",
) -> dict | None:
    """
    Registra resposta do cliente em respostas_propostas.json.
    Retorna o dict da resposta criada, ou None se inválida.
    """
    from core.propostas_empresa import carregar_propostas
    propostas = carregar_propostas()
    prop = next((p for p in propostas if p["id"] == proposta_id), None)
    if not prop:
        log.warning(f"[expediente] proposta {proposta_id} não encontrada para registrar resposta")
        return None

    if tipo_resposta not in _TIPOS_RESPOSTA_VALIDOS:
        log.warning(f"[expediente] tipo_resposta inválido: {tipo_resposta}")
        tipo_resposta = "sem_resposta"

    agora    = datetime.now().isoformat(timespec="seconds")
    resp_id  = f"resp_{str(uuid.uuid4())[:8]}"

    resposta = {
        "id":               resp_id,
        "proposta_id":      proposta_id,
        "oportunidade_id":  prop.get("oportunidade_id", ""),
        "contraparte":      prop.get("contraparte", ""),
        "tipo_resposta":    tipo_resposta,
        "descricao":        descricao,
        "observacoes":      observacoes,
        "origem":           origem,
        "registrada_em":    agora,
        "aplicada_em":      None,
        "status_aplicacao": "pendente",
    }

    respostas = carregar_respostas()
    respostas.append(resposta)
    _salvar(_ARQ_RESPOSTAS, respostas)

    # Atualizar envio com respondido_em
    envios = carregar_envios()
    for e in envios:
        if e.get("proposta_id") == proposta_id and e.get("status") not in {"cancelado"}:
            e["status"]         = "resposta_recebida"
            e["respondido_em"]  = agora
            e["atualizada_em"]  = agora
            break
    _salvar(_ARQ_ENVIOS, envios)

    registrar_historico_envio_proposta(
        resp_id, "resposta_cliente_registrada",
        f"Resposta '{tipo_resposta}' registrada para proposta {proposta_id} "
        f"({prop.get('contraparte')}) por {origem}",
        origem=origem,
    )

    log.info(
        f"[expediente] resposta '{tipo_resposta}' registrada "
        f"para proposta {proposta_id} ({prop.get('contraparte')})"
    )
    return resposta


# ─── Aplicar resposta no pipeline ────────────────────────────────────────────

def aplicar_resposta_proposta(resposta: dict) -> dict:
    """
    Aplica o efeito da resposta na proposta e no pipeline.
    Retorna dict com resumo do que foi feito.
    """
    from core.propostas_empresa import (
        carregar_propostas, salvar_propostas,
        registrar_aceite_proposta, registrar_historico_proposta,
    )

    proposta_id   = resposta["proposta_id"]
    tipo          = resposta["tipo_resposta"]
    opp_id        = resposta.get("oportunidade_id", "")
    agora         = datetime.now().isoformat(timespec="seconds")
    efeitos: list[str] = []

    propostas = carregar_propostas()
    prop = next((p for p in propostas if p["id"] == proposta_id), None)
    if not prop:
        return {"aplicado": False, "motivo": f"proposta {proposta_id} não encontrada"}

    if tipo == "aceitou":
        prop["status"]    = "aceita"
        prop["aceita_em"] = agora
        efeitos.append("proposta -> aceita")
        # Registrar aceite formal
        registrar_aceite_proposta(
            proposta_id,
            tipo_aceite="aceite_comercial",
            descricao=resposta.get("descricao", "Aceite registrado via resposta"),
            origem=resposta.get("origem", ""),
        )
        # Fortalecer oportunidade no pipeline
        if opp_id:
            _atualizar_opp_pipeline(opp_id, {
                "proposta_status": "aceita",
                "proposta_aceita_em": agora,
            })
            efeitos.append(f"opp {opp_id} -> proposta_status=aceita")

    elif tipo == "aceite_verbal_registrado":
        prop["status"]    = "aceita"
        prop["aceita_em"] = agora
        efeitos.append("proposta -> aceita (verbal)")
        registrar_aceite_proposta(
            proposta_id,
            tipo_aceite="aceite_verbal_registrado",
            descricao=resposta.get("descricao", "Aceite verbal registrado"),
            origem=resposta.get("origem", ""),
        )
        if opp_id:
            _atualizar_opp_pipeline(opp_id, {
                "proposta_status": "aceita",
                "proposta_aceita_em": agora,
            })
            efeitos.append(f"opp {opp_id} -> proposta_status=aceita")

    elif tipo == "recusou":
        prop["status"]       = "rejeitada"
        prop["rejeitada_em"] = agora
        efeitos.append("proposta -> rejeitada")
        if opp_id:
            _atualizar_opp_pipeline(opp_id, {
                "proposta_status": "rejeitada",
                "motivo_perda_proposta": resposta.get("descricao", ""),
            })
            efeitos.append(f"opp {opp_id} -> proposta_status=rejeitada")

    elif tipo == "pediu_ajuste":
        prop["status"] = "pronta_para_revisao"
        prop["versao"]  = prop.get("versao", 1) + 1
        efeitos.append(f"proposta -> pronta_para_revisao (v{prop['versao']})")
        if opp_id:
            _atualizar_opp_pipeline(opp_id, {
                "proposta_status": "em_revisao",
            })

    elif tipo == "pediu_retorno_futuro":
        # Manter viva — apenas registrar no histórico
        efeitos.append("proposta mantida — retorno futuro agendado")
        if opp_id:
            _atualizar_opp_pipeline(opp_id, {
                "proposta_status": "aguardando_retorno",
            })

    prop["atualizada_em"] = agora
    salvar_propostas(propostas)

    # Marcar resposta como aplicada
    respostas = carregar_respostas()
    for r in respostas:
        if r["id"] == resposta["id"]:
            r["status_aplicacao"] = "aplicado"
            r["aplicada_em"]      = agora
            break
    _salvar(_ARQ_RESPOSTAS, respostas)

    registrar_historico_proposta(
        proposta_id, f"resposta_{tipo}_aplicada",
        f"Resposta '{tipo}' aplicada. Efeitos: {'; '.join(efeitos)}",
        origem=resposta.get("origem", ""),
    )

    log.info(f"[expediente] resposta {tipo} aplicada a {proposta_id}: {efeitos}")
    return {"aplicado": True, "tipo": tipo, "efeitos": efeitos}


# ─── Respostas pendentes para o comercial ────────────────────────────────────

def respostas_pendentes_de_aplicacao() -> list:
    """Retorna respostas ainda não aplicadas ao pipeline."""
    return [r for r in carregar_respostas() if r.get("status_aplicacao") == "pendente"]


# ─── Auxiliares de pipeline ───────────────────────────────────────────────────

def _atualizar_opp_pipeline(opp_id: str, campos: dict) -> None:
    """Atualiza campos de proposta na oportunidade do pipeline comercial."""
    arq = config.PASTA_DADOS / "pipeline_comercial.json"
    if not arq.exists():
        return
    try:
        with open(arq, encoding="utf-8") as f:
            pipeline = json.load(f)
        agora = datetime.now().isoformat(timespec="seconds")
        for opp in pipeline:
            if opp.get("id") == opp_id:
                opp.update(campos)
                opp["atualizado_em"] = agora
                break
        with open(arq, "w", encoding="utf-8") as f:
            json.dump(pipeline, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.warning(f"[expediente] falha ao atualizar pipeline {opp_id}: {exc}")


def _ler_config_canal() -> dict:
    arq = config.PASTA_DADOS / "config_canal_email.json"
    if arq.exists():
        try:
            with open(arq, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"modo": "assistido", "habilitado": True}


# ─── Histórico de envios ──────────────────────────────────────────────────────

def registrar_historico_envio_proposta(
    envio_id: str, evento: str, descricao: str, origem: str = ""
) -> None:
    historico = _ler(_ARQ_HIST_ENVIO, [])
    historico.append({
        "id":                str(uuid.uuid4())[:8],
        "envio_proposta_id": envio_id,
        "evento":            evento,
        "descricao":         descricao,
        "origem":            origem,
        "registrado_em":     datetime.now().isoformat(timespec="seconds"),
    })
    if len(historico) > 1000:
        historico = historico[-1000:]
    _salvar(_ARQ_HIST_ENVIO, historico)


# ─── Resumo para painel e observabilidade ────────────────────────────────────

def resumir_para_painel() -> dict:
    envios    = carregar_envios()
    respostas = carregar_respostas()
    hist      = _ler(_ARQ_HIST_ENVIO, [])

    por_status: dict = {}
    for e in envios:
        s = e.get("status", "?")
        por_status[s] = por_status.get(s, 0) + 1

    return {
        "total_envios":         len(envios),
        "preparados":           por_status.get("preparado", 0),
        "em_fila_assistida":    por_status.get("em_fila_assistida", 0),
        "enviados":             por_status.get("enviado_manual_registrado", 0),
        "com_resposta":         por_status.get("resposta_recebida", 0),
        "bloqueados":           por_status.get("bloqueado", 0),
        "respostas_pendentes":  sum(1 for r in respostas if r.get("status_aplicacao") == "pendente"),
        "respostas_aplicadas":  sum(1 for r in respostas if r.get("status_aplicacao") == "aplicado"),
        "historico_recente":    hist[-15:] if hist else [],
    }
