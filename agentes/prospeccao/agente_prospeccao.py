"""
agentes/prospeccao/agente_prospeccao.py — Agente de prospecção operacional.

Lê os artefatos produzidos pela linha de prospecção, identifica oportunidades
novas que ainda não entraram no fluxo comercial, classifica, registra estado
e entrega para o agente_comercial via fila_execucao_comercial.json.

Missão:
  - Não roda scraping novo.
  - Não reimplementa a prospecção base.
  - Usa a inteligência já produzida (candidatas_com_canais_digitais.json etc.).
  - Funciona como camada operacional/autônoma em cima dessa linha.
  - Não envia contato real. Não descarta em massa. Prefere conservadorismo.

Fontes lidas:
  dados/candidatas_com_canais_digitais.json   — principal (dados ricos com abordagem)
  dados/fila_revisao.json                      — complementar (tracking histórico)
  dados/prospeccao_historico.json              — complementar (vezes encontrada)

Entregáveis:
  dados/fila_oportunidades_prospeccao.json    — oportunidades classificadas
  dados/historico_prospeccao_agente.json      — log auditável de eventos
  dados/fila_execucao_comercial.json          — novas candidatas prontas (append)
  dados/handoffs_agentes.json                 — handoffs informativos (append)
  dados/estado_agente_prospeccao.json
"""

import json
import logging
from datetime import datetime
from hashlib import md5
from pathlib import Path

import config
from core.llm_router import LLMRouter
from core.politicas_empresa import carregar_politicas
from core.controle_agente import (
    carregar_estado,
    salvar_estado,
    ja_processado,
    marcar_processado,
    registrar_execucao,
    configurar_log_agente,
)

NOME_AGENTE = "agente_prospeccao"

_ARQ_CANDIDATAS   = "candidatas_com_canais_digitais.json"
_ARQ_REVISAO      = "fila_revisao.json"
_ARQ_HISTORICO_P  = "prospeccao_historico.json"
_ARQ_FILA_EXEC    = "fila_execucao_comercial.json"
_ARQ_PIPELINE     = "pipeline_comercial.json"
_ARQ_HANDOFFS     = "handoffs_agentes.json"
_ARQ_FILA_PROSP   = "fila_oportunidades_prospeccao.json"
_ARQ_HIST_AGENTE  = "historico_prospeccao_agente.json"


# ─── Ponto de entrada ─────────────────────────────────────────────────────────

def executar() -> dict:
    log, caminho_log = configurar_log_agente(NOME_AGENTE)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")

    log.info("=" * 60)
    log.info(f"AGENTE PROSPECÇÃO — inicio {ts}")
    log.info("=" * 60)

    estado = carregar_estado(NOME_AGENTE)
    log.info(
        f"Estado: ultima_execucao={estado['ultima_execucao']} | "
        f"processados={len(estado['itens_processados'])}"
    )

    router = LLMRouter()

    # ── ETAPA 0: Carregar políticas operacionais ───────────────────────────────
    politicas = carregar_politicas()
    limite_novas = politicas.get("prospeccao", {}).get("limite_novas_por_ciclo", 0)
    ritmo        = politicas.get("prospeccao", {}).get("ritmo", "normal")
    modo_empresa = politicas.get("modo_empresa", "normal")
    log.info(f"Politicas carregadas: modo={modo_empresa} | limite_novas={limite_novas} | ritmo={ritmo}")

    # ── ETAPA 1: Carregar insumos ─────────────────────────────────────────────
    insumos = carregar_insumos_prospeccao(log)

    # ── ETAPA 2: Detectar oportunidades já no fluxo comercial ────────────────
    ja_no_fluxo = detectar_oportunidades_ja_no_fluxo_comercial(
        insumos["fila_exec"], insumos["pipeline"]
    )
    log.info(f"Já no fluxo comercial: {len(ja_no_fluxo)} osm_ids")

    # ── ETAPA 3: Carregar artefatos de saída existentes ───────────────────────
    fila_prosp  = _carregar_json(_ARQ_FILA_PROSP, [])
    hist_agente = _carregar_json(_ARQ_HIST_AGENTE, [])
    fila_exec   = insumos["fila_exec"]
    handoffs    = _carregar_json(_ARQ_HANDOFFS, [])

    ids_ja_na_fila_prosp = {o["origem_id"] for o in fila_prosp}
    ids_handoffs_ativos  = _ids_com_handoff_ativo(handoffs)

    # ── ETAPA 4: Processar candidatas ─────────────────────────────────────────
    n_novas = n_prontas = n_revisao = n_baixa = n_skip = 0
    n_novas_ciclo = 0  # contador para respeitar limite_novas_por_ciclo

    for candidata in insumos["candidatas"]:
        osm_id = str(candidata.get("osm_id", ""))
        chave  = f"prosp_{osm_id}"

        # Dedup: já processado neste ou em ciclos anteriores via estado
        if ja_processado(estado, chave):
            n_skip += 1
            continue

        # Dedup: já está no fluxo comercial (pipeline ou fila_exec)
        if osm_id in ja_no_fluxo:
            log.info(f"  [skip-fluxo] {candidata.get('nome','?')[:40]} — já no fluxo comercial")
            marcar_processado(estado, chave)
            n_skip += 1
            continue

        # Respeitar limite de novas por ciclo (0 = sem limite)
        if limite_novas > 0 and n_novas_ciclo >= limite_novas:
            log.info(f"  [limite_ciclo] atingido ({limite_novas}) — parando novas entradas | ritmo={ritmo}")
            break

        # Classificar
        status, prioridade = classificar_para_handoff_ou_revisao(candidata)

        # LLM: refinar avaliação de qualidade do lead (ponto 3 — fallback = regra acima)
        _ctx_lead = {
            "empresa":          candidata.get("nome", ""),
            "categoria":        candidata.get("categoria", ""),
            "cidade":           candidata.get("cidade", ""),
            "score_presenca":   candidata.get("score_presenca_consolidado", candidata.get("score_presenca_digital", 0)),
            "tem_whatsapp":     bool(candidata.get("whatsapp")),
            "tem_site":         bool(candidata.get("website")),
            "abordavel":        candidata.get("abordavel_agora", False),
            "prioridade_regra": prioridade,
            "categorias":       ["lead_quente", "lead_morno", "lead_frio", "descartar"],
            "instrucao":        "Classificar qualidade do lead. Conservador: preferir lead_morno a descartar.",
        }
        _res_lead = router.classificar(_ctx_lead)
        _class_llm = _res_lead["resultado"] if (_res_lead["sucesso"] and not _res_lead["fallback_usado"]) else None
        log.info(f"  [llm] lead={'LLM' if _class_llm else 'regra'} | {candidata.get('nome','?')[:40]}")

        n_novas += 1
        n_novas_ciclo += 1

        # Montar oportunidade de prospecção
        opp_prosp = _montar_oportunidade_prospeccao(candidata, status, prioridade)
        if _class_llm:
            opp_prosp["classificacao_llm"] = _class_llm

        # Atualizar ou inserir na fila_prosp
        if osm_id in ids_ja_na_fila_prosp:
            _atualizar_opp_prosp(fila_prosp, osm_id, status, prioridade)
        else:
            fila_prosp.append(opp_prosp)
            ids_ja_na_fila_prosp.add(osm_id)

        # Registrar histórico
        registrar_historico_prospeccao(
            hist_agente, opp_prosp["id"], candidata.get("nome", ""),
            "oportunidade_importada",
            f"Importada de {_ARQ_CANDIDATAS} | prioridade={prioridade} | status={status}",
        )

        # Para prontas: adicionar a fila_execucao_comercial e criar handoff
        if status == "pronta_para_handoff":
            n_prontas += 1
            # Só adiciona à fila_exec se ainda não estiver lá
            if not _ja_na_fila_exec(fila_exec, osm_id):
                entrada_exec = _preparar_entrada_fila_exec(candidata)
                fila_exec.append(entrada_exec)
                log.info(
                    f"  [→ fila_exec] {candidata.get('nome','?')[:40]} | "
                    f"prioridade={prioridade} | canal={candidata.get('canal_abordagem_sugerido','?')}"
                )
            # Handoff informativo (se não existir)
            if osm_id not in ids_handoffs_ativos:
                hf = criar_handoff_comercial(opp_prosp, osm_id)
                handoffs.append(hf)
                ids_handoffs_ativos.add(osm_id)
                registrar_historico_prospeccao(
                    hist_agente, opp_prosp["id"], candidata.get("nome", ""),
                    "handoff_criado", f"Handoff criado: {hf['id']} → agente_comercial",
                )
        elif status == "em_revisao":
            n_revisao += 1
            registrar_historico_prospeccao(
                hist_agente, opp_prosp["id"], candidata.get("nome", ""),
                "marcada_revisao", f"Não abordável agora: {candidata.get('motivo_nao_abordavel','')}",
            )
            log.info(f"  [revisao] {candidata.get('nome','?')[:40]}")
        elif status == "baixa_prioridade":
            n_baixa += 1
            registrar_historico_prospeccao(
                hist_agente, opp_prosp["id"], candidata.get("nome", ""),
                "marcada_baixa_prioridade", f"Abordável mas prioridade baixa",
            )
            log.info(f"  [baixa] {candidata.get('nome','?')[:40]}")

        marcar_processado(estado, chave)

    # ── ETAPA 5: Persistir ────────────────────────────────────────────────────
    _salvar_json(_ARQ_FILA_PROSP,  fila_prosp)
    _salvar_json(_ARQ_HIST_AGENTE, hist_agente)
    _salvar_json(_ARQ_FILA_EXEC,   fila_exec)
    _salvar_json(_ARQ_HANDOFFS,    handoffs)

    # ── ETAPA 6: Salvar estado ────────────────────────────────────────────────
    registrar_execucao(
        estado,
        saldo    = 0.0,
        resumo   = f"novas={n_novas} prontas={n_prontas} revisao={n_revisao} baixa={n_baixa} skip={n_skip}",
        n_escalados = 0,
        n_autonomos = n_prontas,
        hash_exec   = md5(f"{ts}{n_novas}".encode()).hexdigest()[:12],
    )
    salvar_estado(NOME_AGENTE, estado)

    resumo = {
        "agente":             NOME_AGENTE,
        "timestamp":          ts,
        "candidatas_lidas":   len(insumos["candidatas"]),
        "ja_no_fluxo":        len(ja_no_fluxo),
        "novas_processadas":  n_novas,
        "prontas_para_handoff": n_prontas,
        "em_revisao":         n_revisao,
        "baixa_prioridade":   n_baixa,
        "skip":               n_skip,
        "fila_prosp_total":   len(fila_prosp),
        "modo_empresa":       modo_empresa,
        "limite_novas_ciclo": limite_novas,
        "caminho_log":        str(caminho_log),
    }

    # Memória do agente (melhor esforço)
    try:
        from core.llm_memoria import atualizar_memoria_agente
        atualizar_memoria_agente(NOME_AGENTE, {
            "resumo_ciclo_anterior": (
                f"{n_novas} novas, {n_prontas} prontas, "
                f"{n_revisao} revisao, {n_baixa} baixa, {n_skip} skip"
            )
        })
    except Exception as _exc_mem:
        log.warning(f"[memoria] {_exc_mem}")

    log.info("=" * 60)
    log.info(f"AGENTE PROSPECÇÃO — concluído")
    log.info(f"  candidatas lidas   : {len(insumos['candidatas'])}")
    log.info(f"  já no fluxo        : {len(ja_no_fluxo)}")
    log.info(f"  novas processadas  : {n_novas}")
    log.info(f"  prontas_para_handoff: {n_prontas}")
    log.info(f"  em_revisao         : {n_revisao}")
    log.info(f"  baixa_prioridade   : {n_baixa}")
    log.info(f"  skip (já proc.)    : {n_skip}")
    log.info("=" * 60)

    return resumo


# ─── Funções públicas ─────────────────────────────────────────────────────────

def carregar_insumos_prospeccao(log=None) -> dict:
    """Carrega todas as fontes de prospecção."""
    candidatas = _carregar_json(_ARQ_CANDIDATAS, [])
    fila_exec  = _carregar_json(_ARQ_FILA_EXEC, [])
    pipeline   = _carregar_json(_ARQ_PIPELINE, [])
    revisao    = _carregar_json(_ARQ_REVISAO, [])
    historico  = _carregar_json(_ARQ_HISTORICO_P, [])

    if log:
        log.info(
            f"Insumos: candidatas={len(candidatas)} | fila_exec={len(fila_exec)} | "
            f"pipeline={len(pipeline)} | revisao={len(revisao)} | historico={len(historico)}"
        )
    return {
        "candidatas": candidatas,
        "fila_exec":  fila_exec,
        "pipeline":   pipeline,
        "revisao":    revisao,
        "historico":  historico,
    }


def detectar_oportunidades_ja_no_fluxo_comercial(fila_exec: list, pipeline: list) -> set:
    """
    Retorna set de osm_ids que já estão no fluxo comercial.
    Verifica fila_execucao_comercial.json e pipeline_comercial.json.
    """
    ids_fila = {str(e.get("osm_id", "")) for e in fila_exec}
    ids_pipe = {str(o.get("origem_id", "")) for o in pipeline}
    return ids_fila | ids_pipe


def classificar_para_handoff_ou_revisao(candidata: dict) -> tuple[str, str]:
    """
    Classifica a candidata em um status e prioridade.
    Retorna (status, prioridade).

    Conservadorismo: dúvida vai para revisão ou baixa_prioridade, nunca descartada.
    """
    abordavel  = candidata.get("abordavel_agora", False)
    prioridade = candidata.get("prioridade_abordagem", "") or ""
    prioridade = prioridade.lower().strip()

    if not abordavel:
        return "em_revisao", prioridade or "indefinida"

    if prioridade in ("alta", ""):
        return "pronta_para_handoff", "alta"
    elif prioridade == "media":
        return "pronta_para_handoff", "media"
    else:
        return "baixa_prioridade", "baixa"


def criar_handoff_comercial(opp_prosp: dict, osm_id: str) -> dict:
    """
    Cria handoff informativo em handoffs_agentes.json.
    Agente destino: agente_comercial.
    O pickup real é via fila_execucao_comercial.json.
    """
    agora = datetime.now().isoformat(timespec="seconds")
    return {
        "id":             f"hf_prosp_{osm_id}",
        "agente_origem":  NOME_AGENTE,
        "agente_destino": "agente_comercial",
        "tipo":           "novo_lead_prospeccao",
        "referencia_id":  opp_prosp["id"],
        "contraparte":    opp_prosp["empresa"],
        "descricao": (
            f"Novo lead de prospecção: {opp_prosp['empresa']} | "
            f"prioridade={opp_prosp['prioridade']} | "
            f"canal={opp_prosp.get('canal_sugerido','?')}"
        ),
        "status":         "pendente",
        "urgencia":       "normal",
        "registrado_em":  agora,
        "atualizado_em":  agora,
    }


def registrar_historico_prospeccao(
    historico: list,
    oportunidade_id: str,
    empresa: str,
    evento: str,
    descricao: str,
) -> None:
    """Registra evento no historico_prospeccao_agente.json (in-place)."""
    agora = datetime.now().isoformat(timespec="seconds")
    chave = f"{oportunidade_id}|{evento}|{agora}"
    ev_id = "ev_prosp_" + md5(chave.encode()).hexdigest()[:10]
    historico.append({
        "id":              ev_id,
        "oportunidade_id": oportunidade_id,
        "empresa":         empresa,
        "evento":          evento,
        "descricao":       descricao[:200],
        "origem":          _ARQ_CANDIDATAS,
        "registrado_em":   agora,
    })


# ─── Internos ─────────────────────────────────────────────────────────────────

def _montar_oportunidade_prospeccao(candidata: dict, status: str, prioridade: str) -> dict:
    osm_id = str(candidata.get("osm_id", ""))
    agora  = datetime.now().isoformat(timespec="seconds")

    # Montar resumo da abordagem com o que estiver disponível
    pacote = (
        candidata.get("oportunidade_principal", "")
        or candidata.get("oportunidade_presenca_principal", "")
        or candidata.get("oferta_principal_comercial", "")
        or "Sem abordagem mapeada"
    )

    return {
        "id":                        f"prosp_oport_{osm_id}",
        "origem_id":                 osm_id,
        "empresa":                   candidata.get("nome", ""),
        "categoria":                 candidata.get("categoria", candidata.get("categoria_id", "")),
        "cidade":                    candidata.get("cidade", ""),
        "prioridade":                prioridade,
        "abordavel":                 candidata.get("abordavel_agora", False),
        "motivo_priorizacao":        (candidata.get("motivo_prioridade", "") or "")[:200],
        "pacote_abordagem_resumido": pacote[:200],
        "canal_sugerido":            candidata.get("canal_abordagem_sugerido", ""),
        "contato_principal":         candidata.get("contato_principal", ""),
        "score_presenca":            candidata.get("score_presenca_consolidado", candidata.get("score_presenca_digital", 0)),
        "status":                    status,
        "pronto_para_handoff":       status == "pronta_para_handoff",
        "destino_sugerido":          "agente_comercial" if status == "pronta_para_handoff" else None,
        "registrado_em":             agora,
        "atualizado_em":             agora,
    }


def _atualizar_opp_prosp(fila_prosp: list, osm_id: str, status: str, prioridade: str) -> None:
    """Atualiza status/prioridade de oportunidade já existente na fila_prosp (in-place)."""
    agora = datetime.now().isoformat(timespec="seconds")
    for opp in fila_prosp:
        if opp.get("origem_id") == osm_id:
            opp["status"]              = status
            opp["prioridade"]          = prioridade
            opp["pronto_para_handoff"] = status == "pronta_para_handoff"
            opp["atualizado_em"]       = agora
            break


def _preparar_entrada_fila_exec(candidata: dict) -> dict:
    """
    Monta item compatível com fila_execucao_comercial.json para o agente_comercial.
    Preserva campos originais da candidata e adiciona campos esperados pelo comercial.
    """
    item = dict(candidata)  # preserva todos os campos ricos da candidata

    # Garantir campos esperados por pipeline_manager._lead_para_oportunidade()
    if "nivel_prioridade_comercial" not in item:
        item["nivel_prioridade_comercial"] = candidata.get("prioridade_abordagem", "media") or "media"
    if "proxima_acao_comercial" not in item:
        item["proxima_acao_comercial"] = (
            candidata.get("motivo_abordagem", "")
            or candidata.get("oportunidade_principal", "")
            or f"Abordar {candidata.get('nome','empresa')} via {candidata.get('canal_abordagem_sugerido','telefone')}"
        )
    if "observacoes_comerciais" not in item:
        item["observacoes_comerciais"] = candidata.get("observacoes_abordagem", "")
    if "estado" not in item:
        item["estado"] = "SP"   # default para São José do Rio Preto (cidade configurada)

    item["_origem_agente"] = NOME_AGENTE
    return item


def _preparar_entrada_fila_exec(candidata: dict) -> dict:
    """
    Monta item compatível com fila_execucao_comercial.json para o agente_comercial.
    Preserva campos originais da candidata e adiciona campos esperados pelo comercial.
    """
    item = dict(candidata)  # preserva todos os campos ricos da candidata

    # Garantir campos esperados por pipeline_manager._lead_para_oportunidade()
    if "nivel_prioridade_comercial" not in item:
        item["nivel_prioridade_comercial"] = candidata.get("prioridade_abordagem", "media") or "media"
    if "proxima_acao_comercial" not in item:
        item["proxima_acao_comercial"] = (
            candidata.get("motivo_abordagem", "")
            or candidata.get("oportunidade_principal", "")
            or f"Abordar {candidata.get('nome', 'empresa')} via {candidata.get('canal_abordagem_sugerido', 'telefone')}"
        )
    if "observacoes_comerciais" not in item:
        item["observacoes_comerciais"] = candidata.get("observacoes_abordagem", "")
    if "estado" not in item:
        item["estado"] = "SP"

    item["_origem_agente"] = NOME_AGENTE
    return item


def _ja_na_fila_exec(fila_exec: list, osm_id: str) -> bool:
    return any(str(e.get("osm_id", "")) == osm_id for e in fila_exec)


def _ids_com_handoff_ativo(handoffs: list) -> set:
    """
    Retorna set de osm_ids que já têm handoff ativo do agente_prospeccao.
    Evita criar handoff duplicado para a mesma empresa.
    """
    ids = set()
    for hf in handoffs:
        if hf.get("agente_origem") == NOME_AGENTE and hf.get("status") in ("pendente", "em_andamento"):
            ref = hf.get("referencia_id", "")
            # prosp_oport_{osm_id}
            if ref.startswith("prosp_oport_"):
                ids.add(ref.replace("prosp_oport_", ""))
    return ids


def _carregar_json(nome: str, padrao):
    caminho = config.PASTA_DADOS / nome
    if not caminho.exists():
        return padrao
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


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
