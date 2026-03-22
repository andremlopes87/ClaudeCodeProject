"""
agentes/marketing/agente_marketing.py — Agente de marketing da empresa.

Responsabilidade:
  Ler os artefatos produzidos pela linha de marketing (fila_propostas_marketing.json,
  fila_oportunidades_marketing.json) e transformá-los em operações concretas:
  handoffs para comercial e deliberações para o conselho.

Não reanalisa websites. Não recria planos. Não envia nada real.
Opera sobre o que a linha de marketing já produziu.

Autonomia:
  Pode sozinho: importar oportunidades, criar handoffs, criar deliberações,
  marcar baixa prioridade, marcar revisão.
  Não pode: negociar preço, enviar proposta real, descartar em massa.
"""

import json
import logging
from datetime import datetime
from hashlib import md5
from pathlib import Path
from unicodedata import normalize

import config
from core.controle_agente import (
    carregar_estado,
    configurar_log_agente,
    ja_processado,
    marcar_pendente,
    marcar_processado,
    salvar_estado,
)

_NOME_AGENTE = "agente_marketing"

_ARQ_PROPOSTAS      = "fila_propostas_marketing.json"
_ARQ_OPORTUNIDADES  = "fila_oportunidades_marketing.json"
_ARQ_FILA_AGT       = "fila_oportunidades_marketing_agente.json"
_ARQ_HISTORICO      = "historico_marketing_agente.json"
_ARQ_PIPELINE       = "pipeline_comercial.json"
_ARQ_FILA_EXEC_COM  = "fila_execucao_comercial.json"
_ARQ_HANDOFFS       = "handoffs_agentes.json"
_ARQ_DELIBERACOES   = "deliberacoes_conselho.json"

# Threshold: complexidade alta → deliberação; senão → handoff direto
_COMPLEXIDADES_SENSIVEIS = {"alta", "muito_alta"}


# ─── Ponto de entrada público ─────────────────────────────────────────────────

def executar() -> dict:
    """
    Ponto de entrada para o orquestrador.
    Lê artefatos de marketing, triagem, cria handoffs/deliberações.
    Retorna resumo da execução.
    """
    log, _ = configurar_log_agente(_NOME_AGENTE)
    log.info("=" * 60)
    log.info(f"AGENTE MARKETING — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    estado    = carregar_estado(_NOME_AGENTE)
    insumos   = carregar_insumos_marketing()
    ja_no_fluxo = detectar_oportunidades_ja_no_fluxo()

    fila_agente = _carregar_json(_ARQ_FILA_AGT, [])
    historico   = _carregar_json(_ARQ_HISTORICO, [])
    handoffs    = _carregar_json(_ARQ_HANDOFFS, [])
    deliberacoes = _carregar_json(_ARQ_DELIBERACOES, [])

    n_importadas   = 0
    n_handoffs     = 0
    n_deliberacoes = 0
    n_baixa_prio   = 0
    n_revisao      = 0
    n_ja_no_fluxo  = 0

    log.info(
        f"Propostas encontradas: {len(insumos)} | "
        f"Já no fluxo: {len(ja_no_fluxo)}"
    )

    for item in insumos:
        chave = str(item.get("osm_id", ""))
        if not chave:
            continue

        # Dedup: já processado pelo agente antes
        if ja_processado(estado, f"mkt_{chave}"):
            continue

        # Dedup: já está em pipeline / execução / handoff / deliberação ativa
        if chave in ja_no_fluxo:
            log.info(f"  [ja_no_fluxo] {item.get('nome', chave)}")
            marcar_processado(estado, f"mkt_{chave}")
            n_ja_no_fluxo += 1
            continue

        # Importar para fila do agente
        oport = importar_oportunidade_marketing(item)
        fila_agente.append(oport)
        registrar_historico_marketing(historico, oport, "oportunidade_importada",
                                      f"Importada da linha de marketing — prioridade={oport['prioridade']}")
        n_importadas += 1
        log.info(f"  [importada] {oport['empresa']} | prio={oport['prioridade']}")

        # Triagem
        destino, requer_delib = classificar_para_handoff_ou_deliberacao(item)
        oport["status"]            = "triada"
        oport["pronto_para_handoff"] = destino == "agente_comercial" and not requer_delib
        oport["destino_sugerido"]  = destino
        oport["requer_deliberacao"] = requer_delib
        oport["atualizado_em"]     = datetime.now().isoformat(timespec="seconds")

        registrar_historico_marketing(historico, oport, "oportunidade_triada",
                                      f"Triagem: destino={destino} requer_deliberacao={requer_delib}")

        if oport["prioridade"] == "baixa":
            oport["status"] = "baixa_prioridade"
            registrar_historico_marketing(historico, oport, "marcada_baixa_prioridade",
                                          "Prioridade baixa — sem handoff gerado")
            marcar_processado(estado, f"mkt_{chave}")
            n_baixa_prio += 1
            log.info(f"    → baixa_prioridade")
            continue

        if destino == "em_revisao":
            oport["status"] = "em_revisao"
            registrar_historico_marketing(historico, oport, "marcada_revisao",
                                          "Sem dados suficientes para handoff — enviada para revisão")
            marcar_processado(estado, f"mkt_{chave}")
            n_revisao += 1
            log.info(f"    → em_revisao")
            continue

        if requer_delib:
            delib = criar_deliberacao_marketing(item, oport)
            deliberacoes.append(delib)
            oport["status"] = "aguardando_conselho"
            registrar_historico_marketing(historico, oport, "deliberacao_criada",
                                          f"Deliberação criada: {delib['id']}")
            marcar_pendente(estado, f"mkt_{chave}")
            n_deliberacoes += 1
            log.info(f"    → deliberacao ({delib['id']})")
        else:
            handoff = criar_handoff_comercial_marketing(item, oport, handoffs)
            if handoff:
                handoffs.append(handoff)
                oport["status"] = "pronta_para_handoff"
                registrar_historico_marketing(historico, oport, "handoff_criado",
                                              f"Handoff criado para agente_comercial: {handoff['id']}")
                n_handoffs += 1
                log.info(f"    → handoff ({handoff['id']})")

        marcar_processado(estado, f"mkt_{chave}")

    # Persistir
    _salvar_json(_ARQ_FILA_AGT, fila_agente)
    _salvar_json(_ARQ_HISTORICO, historico)
    _salvar_json(_ARQ_HANDOFFS, handoffs)
    _salvar_json(_ARQ_DELIBERACOES, deliberacoes)
    salvar_estado_agente_marketing(estado, n_importadas, n_handoffs, n_deliberacoes)

    log.info(
        f"Importadas: {n_importadas} | Handoffs: {n_handoffs} | "
        f"Deliberações: {n_deliberacoes} | Baixa prio: {n_baixa_prio} | "
        f"Revisão: {n_revisao} | Já no fluxo: {n_ja_no_fluxo}"
    )
    log.info("=" * 60)

    return {
        "importadas":        n_importadas,
        "handoffs_criados":  n_handoffs,
        "deliberacoes":      n_deliberacoes,
        "baixa_prioridade":  n_baixa_prio,
        "em_revisao":        n_revisao,
        "ja_no_fluxo":       n_ja_no_fluxo,
        "fila_agente_total": len(fila_agente),
    }


# ─── Funções públicas ─────────────────────────────────────────────────────────

def carregar_insumos_marketing() -> list:
    """
    Carrega oportunidades da linha de marketing.
    Prefere fila_propostas_marketing.json (plano completo).
    Complementa com fila_oportunidades_marketing.json para itens sem proposta.
    """
    propostas     = _carregar_json(_ARQ_PROPOSTAS, [])
    oportunidades = _carregar_json(_ARQ_OPORTUNIDADES, [])

    ids_propostas = {str(p.get("osm_id")) for p in propostas}
    extras = [o for o in oportunidades if str(o.get("osm_id")) not in ids_propostas]
    return propostas + extras


def detectar_oportunidades_ja_no_fluxo() -> set:
    """
    Retorna set de osm_ids que já estão em:
    - pipeline_comercial.json (campo oportunidade_id contém osm_id)
    - fila_execucao_comercial.json
    - handoffs_agentes.json (handoff ativo de origem marketing)
    - deliberacoes_conselho.json (pendente de origem marketing)
    - fila_oportunidades_marketing_agente.json (já importado pelo agente)
    """
    ja_no_fluxo = set()

    # Pipeline comercial — oportunidade_id = "oport_{osm_id}"
    for opp in _carregar_json(_ARQ_PIPELINE, []):
        opp_id = opp.get("oportunidade_id", "") or opp.get("id", "")
        osm = _extrair_osm_do_id(opp_id)
        if osm:
            ja_no_fluxo.add(osm)
        # também pelo nome normalizado
        if opp.get("osm_id"):
            ja_no_fluxo.add(str(opp["osm_id"]))

    # Fila de execução comercial
    for item in _carregar_json(_ARQ_FILA_EXEC_COM, []):
        osm = _extrair_osm_do_id(item.get("oportunidade_id", ""))
        if osm:
            ja_no_fluxo.add(osm)
        if item.get("osm_id"):
            ja_no_fluxo.add(str(item["osm_id"]))

    # Handoffs ativos do agente_marketing
    for hoff in _carregar_json(_ARQ_HANDOFFS, []):
        if hoff.get("agente_origem") == _NOME_AGENTE and hoff.get("status") != "concluido":
            ref = hoff.get("referencia_id", "")
            osm = _extrair_osm_do_id(ref)
            if osm:
                ja_no_fluxo.add(osm)

    # Deliberações pendentes do agente_marketing
    for delib in _carregar_json(_ARQ_DELIBERACOES, []):
        if delib.get("agente_origem") == _NOME_AGENTE and delib.get("status") in ("pendente", "em_analise"):
            for ref in delib.get("referencia_ids", []):
                osm = _extrair_osm_do_id(ref)
                if osm:
                    ja_no_fluxo.add(osm)

    # Já na fila do agente
    for item in _carregar_json(_ARQ_FILA_AGT, []):
        if item.get("origem_id"):
            ja_no_fluxo.add(str(item["origem_id"]))

    return ja_no_fluxo


def importar_oportunidade_marketing(item: dict) -> dict:
    """Monta item padronizado para fila_oportunidades_marketing_agente.json."""
    agora  = datetime.now().isoformat(timespec="seconds")
    osm_id = str(item.get("osm_id", ""))
    ts_id  = datetime.now().strftime("%Y%m%d%H%M%S")
    oport_id = f"mkt_{osm_id}_{ts_id}"

    prioridade = (
        item.get("prioridade_execucao_marketing")
        or item.get("prioridade_oferta_presenca")
        or item.get("prioridade_abordagem")
        or "media"
    )

    return {
        "id":                    oport_id,
        "origem_id":             osm_id,
        "empresa":               item.get("nome", ""),
        "categoria":             item.get("categoria", ""),
        "cidade":                item.get("cidade", ""),
        "prioridade":            prioridade,
        "diagnostico_resumido":  item.get("resumo_oportunidade_marketing")
                                 or item.get("diagnostico_presenca_digital", ""),
        "oportunidade_marketing": item.get("oportunidade_marketing_principal")
                                  or item.get("oportunidade_presenca_principal", ""),
        "plano_resumido":        _resumir_plano(item),
        "proposta_resumida":     item.get("proposta_resumida_marketing", ""),
        "oferta_principal":      item.get("oferta_principal_comercial", ""),
        "status":                "nova",
        "pronto_para_handoff":   False,
        "destino_sugerido":      None,
        "requer_deliberacao":    False,
        "registrado_em":         agora,
        "atualizado_em":         agora,
    }


def classificar_para_handoff_ou_deliberacao(item: dict) -> tuple[str, bool]:
    """
    Retorna (destino, requer_deliberacao).

    Destino: "agente_comercial" | "em_revisao"
    requer_deliberacao: True quando escopo sensível (complexidade alta, etc.)
    """
    pronta         = item.get("pronta_para_oferta_presenca", False)
    plano_gerado   = item.get("plano_marketing_gerado", False)
    complexidade   = item.get("nivel_complexidade_execucao", "")
    prioridade     = (
        item.get("prioridade_execucao_marketing")
        or item.get("prioridade_oferta_presenca")
        or item.get("prioridade_abordagem")
        or "media"
    )

    # Sem dados suficientes → revisão
    if not pronta and not plano_gerado:
        return "em_revisao", False

    # Alta complexidade → deliberação
    if complexidade in _COMPLEXIDADES_SENSIVEIS:
        return "agente_comercial", True

    # Prioridade nula sem plano → revisão
    if prioridade in ("nula", None, ""):
        return "em_revisao", False

    return "agente_comercial", False


def criar_handoff_comercial_marketing(item: dict, oport: dict, handoffs_existentes: list) -> dict | None:
    """
    Cria handoff para agente_comercial.
    Retorna None se já existir handoff ativo para o mesmo osm_id.
    """
    osm_id = str(item.get("osm_id", ""))
    ref_id = f"mkt_{osm_id}"

    # Evitar duplicata ativa
    for h in handoffs_existentes:
        if (
            h.get("referencia_id") == ref_id
            and h.get("agente_destino") == "agente_comercial"
            and h.get("status") not in ("concluido", "cancelado")
        ):
            return None

    agora  = datetime.now().isoformat(timespec="seconds")
    chave  = f"{ref_id}|handoff|{agora}"
    hf_id  = "hf_mkt_" + md5(chave.encode()).hexdigest()[:10]

    prioridade = oport.get("prioridade", "media")
    empresa    = item.get("nome", "empresa")
    canal      = item.get("canal_primeiro_contato") or item.get("canal_abordagem_sugerido", "telefone")
    oferta     = item.get("oferta_principal_comercial", oport.get("oferta_principal", ""))
    proposta   = item.get("proposta_resumida_marketing", "")

    descricao = (
        f"{empresa} — {oferta or 'Proposta de marketing digital'} | "
        f"Canal: {canal} | Proposta: {proposta[:120] if proposta else '—'}"
    )

    return {
        "id":             hf_id,
        "agente_origem":  _NOME_AGENTE,
        "agente_destino": "agente_comercial",
        "tipo_handoff":   "oportunidade_marketing",
        "referencia_id":  ref_id,
        "descricao":      descricao,
        "prioridade":     prioridade,
        "status":         "pendente",
        "depende_de":     None,
        "registrado_em":  agora,
        "atualizado_em":  agora,
    }


def criar_deliberacao_marketing(item: dict, oport: dict) -> dict:
    """Cria deliberação para o conselho sobre oportunidade sensível."""
    agora  = datetime.now().isoformat(timespec="seconds")
    osm_id = str(item.get("osm_id", ""))
    chave  = f"delib_mkt_{osm_id}|{agora}"
    d_id   = "delib_mkt_" + md5(chave.encode()).hexdigest()[:10]

    empresa      = item.get("nome", "empresa")
    complexidade = item.get("nivel_complexidade_execucao", "?")
    proposta     = item.get("proposta_resumida_marketing", "")
    oferta       = item.get("oferta_principal_comercial", "")

    return {
        "id":                  d_id,
        "agente_origem":       _NOME_AGENTE,
        "tipo":                "oportunidade_marketing_complexa",
        "titulo":              f"{empresa} — Oportunidade de marketing (complexidade {complexidade})",
        "descricao":           proposta[:300] if proposta else oferta,
        "contexto_resumido":   (
            f"{empresa} | complexidade={complexidade} | "
            f"prioridade={oport.get('prioridade', '?')} | "
            f"oferta: {oferta[:100] if oferta else '—'}"
        ),
        "impacto":             "medio",
        "urgencia":            "normal",
        "recomendacao_agente": (
            f"Revisar proposta e decidir se avança para apresentação comercial. "
            f"Oferta: {oferta[:120] if oferta else '—'}"
        ),
        "alternativas":        [],
        "status":              "pendente",
        "referencia_ids":      [f"mkt_{osm_id}"],
        "criado_em":           agora,
        "atualizado_em":       agora,
        "resolvido_em":        None,
        "decisao_conselho":    None,
        "observacao_conselho": None,
    }


def registrar_historico_marketing(historico: list, oport: dict, evento: str, descricao: str) -> None:
    """Registra evento no historico_marketing_agente.json (in-place)."""
    agora = datetime.now().isoformat(timespec="seconds")
    chave = f"{oport['id']}|{evento}|{agora}"
    ev_id = "hev_mkt_" + md5(chave.encode()).hexdigest()[:10]

    historico.append({
        "id":              ev_id,
        "oportunidade_id": oport["id"],
        "empresa":         oport.get("empresa", ""),
        "evento":          evento,
        "descricao":       descricao,
        "origem":          _NOME_AGENTE,
        "registrado_em":   agora,
    })


def salvar_estado_agente_marketing(estado: dict, n_importadas: int, n_handoffs: int, n_deliberacoes: int) -> None:
    """Atualiza e persiste o estado do agente."""
    agora = datetime.now().isoformat(timespec="seconds")
    estado["ultima_execucao"] = agora

    contadores = estado.setdefault("contadores", {})
    contadores["total_importadas"]   = contadores.get("total_importadas", 0) + n_importadas
    contadores["total_handoffs"]     = contadores.get("total_handoffs", 0) + n_handoffs
    contadores["total_deliberacoes"] = contadores.get("total_deliberacoes", 0) + n_deliberacoes

    estado["ultimo_snapshot"] = {
        "importadas":   n_importadas,
        "handoffs":     n_handoffs,
        "deliberacoes": n_deliberacoes,
        "registrado_em": agora,
    }

    salvar_estado(_NOME_AGENTE, estado)


# ─── Internos ─────────────────────────────────────────────────────────────────

def _extrair_osm_do_id(id_str: str) -> str:
    """
    Extrai osm_id numérico de strings como 'oport_12295658387' ou 'mkt_12295658387'.
    Retorna string vazia se não encontrar padrão.
    """
    if not id_str:
        return ""
    partes = id_str.replace("oport_", "").replace("mkt_", "").split("_")
    for parte in partes:
        if parte.isdigit() and len(parte) > 5:
            return parte
    return ""


def _resumir_plano(item: dict) -> str:
    """Extrai resumo do plano de 30 dias ou usa quick_wins como fallback."""
    plano = item.get("plano_30_dias_marketing")
    if isinstance(plano, dict):
        semana1 = plano.get("semana_1", "")
        if semana1:
            return f"Semana 1: {semana1[:150]}"
    quick = item.get("quick_wins_marketing")
    if isinstance(quick, list) and quick:
        return "; ".join(str(q) for q in quick[:2])
    return str(plano or "")[:150]


def _carregar_json(nome: str, padrao):
    caminho = config.PASTA_DADOS / nome
    if not caminho.exists():
        return padrao
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def _salvar_json(nome: str, dados) -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = config.PASTA_DADOS / nome
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
