"""
core/respostas_documentos.py

Camada de resposta do cliente para documentos oficiais enviados.

Fecha o loop: envio_documento → resposta_registrada → efeito no pipeline.

Para proposta_comercial: chama registrar_aceite_proposta / rejeitar_proposta / etc.
Para contrato_comercial: atualiza status do contrato em contratos_clientes.json.

Idempotência: mesma resposta não pode ser aplicada duas vezes.

Arquivos gerenciados:
  dados/respostas_documentos.json
  dados/historico_respostas_documentos.json

Reutiliza:
  dados/envios_documentos.json
  dados/propostas_comerciais.json
  dados/contratos_clientes.json
  dados/pipeline_comercial.json
  dados/aceites_propostas.json
  dados/historico_propostas_comerciais.json
  dados/historico_contratos.json
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_RESPOSTAS = config.PASTA_DADOS / "respostas_documentos.json"
_ARQ_HISTORICO = config.PASTA_DADOS / "historico_respostas_documentos.json"
_ARQ_ENVIOS    = config.PASTA_DADOS / "envios_documentos.json"
_ARQ_PROPOSTAS = config.PASTA_DADOS / "propostas_comerciais.json"
_ARQ_CONTRATOS = config.PASTA_DADOS / "contratos_clientes.json"
_ARQ_PIPELINE  = config.PASTA_DADOS / "pipeline_comercial.json"
_ARQ_HIST_PROP = config.PASTA_DADOS / "historico_propostas_comerciais.json"
_ARQ_HIST_CT   = config.PASTA_DADOS / "historico_contratos.json"
_ARQ_ACEITES   = config.PASTA_DADOS / "aceites_propostas.json"

_TIPOS_RESPOSTA = {
    "aceitou", "recusou", "pediu_ajuste",
    "pediu_retorno_futuro", "sem_resposta", "aceite_verbal_registrado",
}

_STATUS_APLICA_PROPOSTA = {"aceitou", "aceite_verbal_registrado", "recusou", "pediu_ajuste"}
_STATUS_APLICA_CONTRATO = {"aceitou", "aceite_verbal_registrado", "recusou"}


# ─── I/O ──────────────────────────────────────────────────────────────────────

def _ler(arq: Path, padrao):
    try:
        if arq.exists():
            with open(arq, encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        log.warning(f"[respostas_docs] falha ao ler {arq.name}: {exc}")
    return padrao


def _salvar(arq: Path, dados) -> None:
    import os
    try:
        arq.parent.mkdir(parents=True, exist_ok=True)
        conteudo = json.dumps(dados, ensure_ascii=False, indent=2)
        tmp = arq.with_suffix(arq.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(conteudo)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, arq)
    except Exception as exc:
        log.warning(f"[respostas_docs] falha ao salvar {arq.name}: {exc}")


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def carregar_respostas() -> list:
    return _ler(_ARQ_RESPOSTAS, [])


# ─── Registrar resposta ───────────────────────────────────────────────────────

def registrar_resposta_documento(
    envio_doc_id: str,
    tipo_resposta: str,
    descricao: str = "",
    origem: str = "conselho_painel",
) -> "dict | None":
    """
    Registra resposta do cliente para um envio de documento oficial.
    Cria entrada em respostas_documentos.json.
    Atualiza status do envio em envios_documentos.json.
    Retorna dict da resposta criada ou None se inválida.
    """
    if tipo_resposta not in _TIPOS_RESPOSTA:
        log.warning(f"[respostas_docs] tipo_resposta inválido: {tipo_resposta}")
        tipo_resposta = "sem_resposta"

    # Carregar envio de referência
    envios = _ler(_ARQ_ENVIOS, [])
    envio  = next((e for e in envios if e.get("id") == envio_doc_id), None)
    if not envio:
        log.warning(f"[respostas_docs] envio_documento {envio_doc_id} não encontrado")
        return None

    # Idempotência: se já existe resposta ativa para este envio, retornar
    respostas_existentes = carregar_respostas()
    existente = next(
        (r for r in respostas_existentes
         if r.get("envio_documento_id") == envio_doc_id
         and r.get("status_aplicacao") not in {"ignorado"}),
        None,
    )
    if existente:
        log.info(
            f"[respostas_docs] resposta já existe para envio {envio_doc_id}: "
            f"{existente['id']} ({existente['tipo_resposta']})"
        )
        return existente

    agora   = _agora()
    resp_id = f"rdoc_{uuid.uuid4().hex[:8]}"

    resposta = {
        "id":                resp_id,
        "envio_documento_id": envio_doc_id,
        "documento_id":      envio.get("documento_id", ""),
        "tipo_documento":    envio.get("tipo_documento", ""),
        "referencia_id":     envio.get("referencia_id", ""),
        "proposta_id":       envio.get("proposta_id", ""),
        "contrato_id":       envio.get("contrato_id", ""),
        "conta_id":          "",  # enriquecido abaixo
        "contraparte":       envio.get("contraparte", ""),
        "tipo_resposta":     tipo_resposta,
        "descricao":         descricao,
        "origem":            origem,
        "status_aplicacao":  "pendente",
        "registrada_em":     agora,
        "aplicada_em":       None,
    }

    # Enriquecer conta_id via proposta ou contrato
    if envio.get("proposta_id"):
        props = _ler(_ARQ_PROPOSTAS, [])
        prop  = next((p for p in props if p.get("id") == envio["proposta_id"]), None)
        if prop:
            resposta["conta_id"] = prop.get("conta_id", "")
    elif envio.get("contrato_id"):
        cts = _ler(_ARQ_CONTRATOS, [])
        ct  = next((c for c in cts if c.get("id") == envio["contrato_id"]), None)
        if ct:
            resposta["conta_id"] = ct.get("conta_id", "")

    # Persistir resposta
    respostas_existentes.append(resposta)
    _salvar(_ARQ_RESPOSTAS, respostas_existentes)

    # Atualizar envio: status → resposta_recebida
    for e in envios:
        if e["id"] == envio_doc_id:
            e["status"]       = "resposta_recebida"
            e["atualizado_em"] = agora
            break
    _salvar(_ARQ_ENVIOS, envios)

    _registrar_hist(
        resp_id, "resposta_documento_registrada",
        f"tipo={tipo_resposta} | {envio.get('tipo_documento')} | "
        f"{envio.get('contraparte')} | origem={origem}",
        origem,
    )

    log.info(
        f"[respostas_docs] {resp_id} — {tipo_resposta} para "
        f"{envio.get('tipo_documento')} {envio.get('contraparte')}"
    )
    return resposta


# ─── Aplicar resposta no pipeline ────────────────────────────────────────────

def aplicar_resposta_documento(resposta: dict) -> dict:
    """
    Aplica efeito da resposta no objeto fonte (proposta ou contrato) e pipeline.
    Idempotente: não aplica se status_aplicacao == 'aplicado'.
    Retorna dict com resumo do que foi feito.
    """
    if resposta.get("status_aplicacao") == "aplicado":
        return {"aplicado": False, "motivo": "já aplicado anteriormente"}

    tipo_doc = resposta.get("tipo_documento", "")
    tipo     = resposta.get("tipo_resposta", "sem_resposta")
    agora    = _agora()
    efeitos: list[str] = []

    if tipo_doc == "proposta_comercial":
        resultado = _aplicar_em_proposta(resposta, agora, efeitos)
    elif tipo_doc == "contrato_comercial":
        resultado = _aplicar_em_contrato(resposta, agora, efeitos)
    else:
        resultado = {"aplicado": False, "motivo": f"tipo_documento '{tipo_doc}' sem handler"}

    if resultado.get("aplicado", True) is not False:
        # Marcar resposta como aplicada
        respostas = carregar_respostas()
        for r in respostas:
            if r["id"] == resposta["id"]:
                r["status_aplicacao"] = "aplicado"
                r["aplicada_em"]      = agora
                break
        _salvar(_ARQ_RESPOSTAS, respostas)

        _registrar_hist(
            resposta["id"], "resposta_documento_aplicada",
            f"tipo={tipo} | efeitos: {'; '.join(efeitos) or '—'}",
            resposta.get("origem", ""),
        )

        log.info(f"[respostas_docs] {resposta['id']} aplicado: {efeitos}")
        return {"aplicado": True, "tipo": tipo, "efeitos": efeitos}

    return resultado


def _aplicar_em_proposta(resposta: dict, agora: str, efeitos: list) -> dict:
    """Aplica efeito da resposta em proposta e pipeline comercial."""
    proposta_id = resposta.get("proposta_id", "")
    tipo        = resposta.get("tipo_resposta", "sem_resposta")
    opp_id      = ""

    if not proposta_id:
        return {"aplicado": False, "motivo": "proposta_id ausente"}

    propostas = _ler(_ARQ_PROPOSTAS, [])
    prop = next((p for p in propostas if p.get("id") == proposta_id), None)
    if not prop:
        return {"aplicado": False, "motivo": f"proposta {proposta_id} não encontrada"}

    opp_id = prop.get("oportunidade_id", "")

    if tipo in ("aceitou", "aceite_verbal_registrado"):
        prop["status"]       = "aceita"
        prop["aceita_em"]    = agora
        prop["atualizada_em"] = agora
        efeitos.append("proposta → aceita")

        # Registrar aceite formal em aceites_propostas.json
        aceites = _ler(_ARQ_ACEITES, [])
        if not any(a.get("proposta_id") == proposta_id for a in aceites):
            aceites.append({
                "id":           f"aceite_{uuid.uuid4().hex[:8]}",
                "proposta_id":  proposta_id,
                "tipo_aceite":  "aceite_verbal_registrado" if tipo == "aceite_verbal_registrado" else "aceite_documento",
                "descricao":    resposta.get("descricao", "Aceite registrado via resposta de documento"),
                "origem":       resposta.get("origem", ""),
                "registrado_em": agora,
            })
            _salvar(_ARQ_ACEITES, aceites)
            efeitos.append("aceite formal registrado")

        # Fortalecer oportunidade no pipeline
        if opp_id:
            _atualizar_opp(opp_id, {
                "proposta_status":    "aceita",
                "proposta_aceita_em": agora,
            })
            efeitos.append(f"opp {opp_id} → proposta_status=aceita")

    elif tipo == "recusou":
        prop["status"]        = "rejeitada"
        prop["rejeitada_em"]  = agora
        prop["atualizada_em"] = agora
        efeitos.append("proposta → rejeitada")
        if opp_id:
            _atualizar_opp(opp_id, {
                "proposta_status":          "rejeitada",
                "motivo_perda_proposta":    resposta.get("descricao", ""),
            })
            efeitos.append(f"opp {opp_id} → proposta_status=rejeitada")

    elif tipo == "pediu_ajuste":
        prop["status"]        = "pronta_para_revisao"
        prop["versao"]         = prop.get("versao", 1) + 1
        prop["atualizada_em"] = agora
        efeitos.append(f"proposta → pronta_para_revisao (v{prop['versao']})")
        if opp_id:
            _atualizar_opp(opp_id, {"proposta_status": "em_revisao"})

    elif tipo == "pediu_retorno_futuro":
        prop["atualizada_em"] = agora
        efeitos.append("proposta mantida — retorno futuro registrado")
        if opp_id:
            _atualizar_opp(opp_id, {"proposta_status": "aguardando_retorno"})

    else:  # sem_resposta
        efeitos.append("sem efeito — tipo sem_resposta")

    _salvar(_ARQ_PROPOSTAS, propostas)

    # Historico proposta
    _registrar_hist_proposta(
        proposta_id,
        f"resposta_documento_{tipo}_aplicada",
        f"Via documento oficial | Efeitos: {'; '.join(efeitos)}",
        resposta.get("origem", ""),
    )

    return {"aplicado": True}


def _aplicar_em_contrato(resposta: dict, agora: str, efeitos: list) -> dict:
    """Aplica efeito da resposta em contrato."""
    contrato_id = resposta.get("contrato_id", "")
    tipo        = resposta.get("tipo_resposta", "sem_resposta")

    if not contrato_id:
        return {"aplicado": False, "motivo": "contrato_id ausente"}

    contratos = _ler(_ARQ_CONTRATOS, [])
    ct = next((c for c in contratos if c.get("id") == contrato_id), None)
    if not ct:
        return {"aplicado": False, "motivo": f"contrato {contrato_id} não encontrado"}

    if tipo in ("aceitou", "aceite_verbal_registrado"):
        if ct.get("status") == "aguardando_ativacao":
            ct["status"]      = "ativo"
            ct["ativado_em"]  = agora
            ct["atualizado_em"] = agora
            efeitos.append(f"contrato {contrato_id} → ativo")
        else:
            efeitos.append(f"contrato já em status={ct['status']} — aceite registrado")

    elif tipo == "recusou":
        # Registrar historico mas não cancelar automaticamente
        efeitos.append(f"recusa registrada | contrato mantido em {ct['status']}")

    elif tipo == "pediu_ajuste":
        efeitos.append(f"ajuste solicitado | contrato mantido em {ct['status']}")

    else:
        efeitos.append(f"tipo={tipo} sem efeito direto em contrato")

    _salvar(_ARQ_CONTRATOS, contratos)

    # Historico contrato
    _registrar_hist_contrato(
        contrato_id,
        f"resposta_documento_{tipo}",
        f"Via documento oficial | {resposta.get('descricao', '')} | efeitos: {'; '.join(efeitos)}",
        resposta.get("origem", ""),
    )

    return {"aplicado": True}


# ─── Consultas ────────────────────────────────────────────────────────────────

def respostas_pendentes() -> list:
    return [r for r in carregar_respostas() if r.get("status_aplicacao") == "pendente"]


def resumir_para_painel() -> dict:
    respostas = carregar_respostas()
    envios    = _ler(_ARQ_ENVIOS, [])

    enviados = [
        e for e in envios
        if e.get("status") in ("marcado_como_enviado", "em_fila_assistida", "resposta_recebida")
    ]
    respondidos_ids = {r.get("envio_documento_id") for r in respostas}
    sem_resposta = [
        e for e in enviados
        if e["id"] not in respondidos_ids
        and e.get("status") not in {"resposta_recebida"}
    ]

    return {
        "total_respostas":                  len(respostas),
        "respostas_pendentes":              sum(1 for r in respostas if r.get("status_aplicacao") == "pendente"),
        "respostas_aplicadas":              sum(1 for r in respostas if r.get("status_aplicacao") == "aplicado"),
        "documentos_aceitos":               sum(1 for r in respostas if r.get("tipo_resposta") in ("aceitou", "aceite_verbal_registrado") and r.get("status_aplicacao") == "aplicado"),
        "documentos_recusados":             sum(1 for r in respostas if r.get("tipo_resposta") == "recusou" and r.get("status_aplicacao") == "aplicado"),
        "documentos_enviados_sem_resposta": len(sem_resposta),
    }


# ─── Auxiliares internos ──────────────────────────────────────────────────────

def _atualizar_opp(opp_id: str, campos: dict) -> None:
    try:
        pipeline = _ler(_ARQ_PIPELINE, [])
        agora    = _agora()
        for opp in pipeline:
            if opp.get("id") == opp_id:
                opp.update(campos)
                opp["atualizado_em"] = agora
                break
        _salvar(_ARQ_PIPELINE, pipeline)
    except Exception as exc:
        log.warning(f"[respostas_docs] falha ao atualizar pipeline {opp_id}: {exc}")


def _registrar_hist_proposta(proposta_id: str, evento: str,
                              descricao: str, origem: str) -> None:
    hist = _ler(_ARQ_HIST_PROP, [])
    hist.append({
        "id":           uuid.uuid4().hex[:8],
        "proposta_id":  proposta_id,
        "evento":       evento,
        "descricao":    descricao,
        "origem":       origem,
        "registrado_em": _agora(),
    })
    _salvar(_ARQ_HIST_PROP, hist)


def _registrar_hist_contrato(contrato_id: str, evento: str,
                              descricao: str, origem: str) -> None:
    hist = _ler(_ARQ_HIST_CT, [])
    hist.append({
        "id":           f"hct_{uuid.uuid4().hex[:8]}",
        "contrato_id":  contrato_id,
        "evento":       evento,
        "descricao":    descricao,
        "origem":       origem,
        "registrado_em": _agora(),
    })
    _salvar(_ARQ_HIST_CT, hist)


def _registrar_hist(resp_id: str, evento: str,
                    descricao: str, origem: str) -> None:
    hist = _ler(_ARQ_HISTORICO, [])
    hist.append({
        "id":           uuid.uuid4().hex[:8],
        "resposta_id":  resp_id,
        "evento":       evento,
        "descricao":    descricao,
        "origem":       origem,
        "registrado_em": _agora(),
    })
    _salvar(_ARQ_HISTORICO, hist)
