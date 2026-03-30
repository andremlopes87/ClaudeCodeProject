"""
core/motor_expansao.py

Motor comercial autônomo de expansão — detecta, qualifica e converte
oportunidades de upsell/cross-sell em contas ativas.

Funil: detectada → qualificada → preparada → handoff_criado → convertida → descartada

Responsabilidade:
  - Detectar oportunidades usando catálogo de ofertas
  - Calcular score_expansao (0-100) com 5 fatores objetivos
  - Gerar pitch personalizado via LLM para expansões quentes
  - Criar handoff para agente_comercial com tipo="expansao"
  - Controlar cooldowns e dedup

Arquivos lidos:
  dados/oportunidades_expansao.json
  dados/contas_clientes.json
  dados/pipeline_entrega.json
  dados/recebiveis.json
  dados/nps_respostas.json
  dados/catalogo_ofertas.json

Arquivos escritos:
  dados/oportunidades_expansao.json   — enriquecido com score + classificacao + pitch
  dados/handoffs_agentes.json         — handoffs para agente_comercial
  dados/propostas_expansao.json       — pitches estruturados para expansões quentes
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_EXPANSAO   = config.PASTA_DADOS / "oportunidades_expansao.json"
_ARQ_CONTAS     = config.PASTA_DADOS / "contas_clientes.json"
_ARQ_ENTREGA    = config.PASTA_DADOS / "pipeline_entrega.json"
_ARQ_RECEBIVEIS = config.PASTA_DADOS / "recebiveis.json"
_ARQ_NPS        = config.PASTA_DADOS / "nps_respostas.json"
_ARQ_CATALOGO   = config.PASTA_DADOS / "catalogo_ofertas.json"
_ARQ_HANDOFFS   = config.PASTA_DADOS / "handoffs_agentes.json"
_ARQ_PITCHES    = config.PASTA_DADOS / "propostas_expansao.json"

# Thresholds de classificação
_SCORE_QUENTE  = 70
_SCORE_MORNA   = 50

# Cooldowns
_COOLDOWN_DESCARTADA_DIAS = 90
_INTERVALO_MINIMO_DIAS    = 30

# Status do funil
_STATUS_ATIVOS = {"detectada", "qualificada", "preparada"}
_STATUS_FINAIS = {"convertida", "convertida_em_oportunidade", "descartada", "arquivada"}


# ─── I/O helpers ──────────────────────────────────────────────────────────────

def _ler(arq: Path, padrao):
    try:
        if arq.exists():
            return json.loads(arq.read_text(encoding="utf-8")) or padrao
    except Exception as _err:
        log.warning("erro ignorado: %s", _err)
    return padrao


def _salvar(arq: Path, dados) -> None:
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


def _dias_desde(ts: str) -> int:
    if not ts:
        return 9999
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).days
    except Exception:
        return 9999


# ─── API pública ──────────────────────────────────────────────────────────────

def processar_expansoes_ciclo(contas_ativas: list, saudes: dict,
                               pipeline_entrega: list, router, log_externo) -> int:
    """
    Ponto de entrada do motor para uso pelo agente_customer_success.

    Para cada conta elegível:
      1. Detecta oportunidades (via catálogo + lacunas)
      2. Pontua cada oportunidade (score_expansao)
      3. Gera pitch para expansões quentes (LLM)
      4. Cria handoff para comercial (expansões quentes)

    Regras:
      - Nunca sugerir para contas em risco/critico
      - Máximo 1 oportunidade ativa por conta
      - Cooldown: 30 dias desde última oferta, 90 dias após descartada

    Retorna quantidade de expansões novas criadas.
    """
    expansoes  = _ler(_ARQ_EXPANSAO, [])
    n_criadas  = 0

    for conta in contas_ativas:
        conta_id = conta["id"]
        saude    = saudes.get(conta_id, {})

        # Nunca expandir contas em risco
        if saude.get("status_saude") in ("atencao", "critica"):
            continue
        if saude.get("risco_churn"):
            continue

        # Montar contexto de score para esta conta
        contexto = _montar_contexto_expansao(conta, saude, pipeline_entrega)

        # Detectar oportunidades via catálogo
        sugestoes = detectar_oportunidades_expansao(conta_id, contexto, pipeline_entrega, expansoes)
        if not sugestoes:
            continue

        log_externo.info(
            f"  [expansao] conta={conta.get('nome_empresa','?')[:25]!r} "
            f"— {len(sugestoes)} oportunidade(s) detectada(s)"
        )

        # LLM: analisar perfil completo para enriquecer sugestões
        try:
            res = router.analisar({
                "agente": "agente_customer_success",
                "tarefa": "analise_perfil_expansao",
                "dados": {
                    "conta":          conta.get("nome_empresa", ""),
                    "score_saude":    saude.get("score_saude", 0),
                    "ofertas_ativas": contexto.get("linhas_ativas", []),
                    "oportunidades":  [s.get("oferta_sugerida") for s in sugestoes],
                    "dias_cliente":   contexto.get("dias_cliente", 0),
                    "nps_promotor":   contexto.get("nps_promotor", False),
                },
                "empresa_id": conta_id,
            })
            if res.get("sucesso") and not res.get("fallback_usado"):
                log_externo.info(f"  [llm] analise de expansao para conta={conta_id}")
        except Exception as exc:
            log_externo.warning(f"  [llm] falha na analise de expansao {conta_id}: {exc}")

        # Processar cada sugestão
        for sug in sugestoes:
            score_info = calcular_score_expansao(conta_id, sug, contexto)
            score      = score_info["score_expansao"]
            classif    = score_info["classificacao"]

            # Gerar pitch personalizado para expansões quentes
            pitch = ""
            if score >= _SCORE_QUENTE:
                pitch = _preparar_pitch(conta, sug, contexto, router, log_externo)

            exp_id = f"exp_{uuid.uuid4().hex[:8]}"
            expansao = {
                "id":                    exp_id,
                "conta_id":              conta_id,
                "conta_nome":            conta.get("nome_empresa", ""),
                "entrega_id":            contexto.get("ultima_entrega_id", ""),
                "tipo_oportunidade":     sug.get("tipo_oportunidade", ""),
                "origem":                "motor_expansao",
                "oferta_sugerida":       sug.get("oferta_sugerida", ""),
                "pacote_sugerido":       sug.get("pacote_sugerido", ""),
                "motivo":                sug.get("motivo", ""),
                "prioridade":            sug.get("prioridade", "media"),
                # Campos novos do motor
                "score_expansao":        score,
                "score_breakdown":       score_info["breakdown"],
                "classificacao":         classif,
                "pitch_personalizado":   pitch,
                "status":                "qualificada",
                "requer_deliberacao":    score >= _SCORE_QUENTE,
                "oportunidade_id_gerada": None,
                "handoff_id":            None,
                "criado_em":             _agora(),
                "atualizado_em":         _agora(),
            }
            expansoes.append(expansao)
            n_criadas += 1

            log_externo.info(
                f"  [expansao] criada: {exp_id} | {sug.get('oferta_sugerida','?')} "
                f"| score={score} class={classif}"
            )

            # Para expansões quentes: criar handoff imediato para comercial
            if score >= _SCORE_QUENTE:
                handoff = _criar_handoff_expansao(exp_id, conta, sug, score)
                if handoff:
                    expansao["handoff_id"] = handoff["id"]
                    expansao["status"]     = "handoff_criado"
                    log_externo.info(
                        f"  [expansao] handoff criado: {handoff['id']} | conta={conta_id}"
                    )

                # Registrar pitch em propostas_expansao.json
                if pitch:
                    _salvar_pitch(exp_id, conta_id, sug, pitch, score)

    _salvar(_ARQ_EXPANSAO, expansoes)
    return n_criadas


def detectar_oportunidades_expansao(conta_id: str, contexto: dict,
                                     pipeline_entrega: list,
                                     expansoes_existentes: list) -> list:
    """
    Detecta oportunidades de expansão para uma conta baseado em:
      - Lacunas de oferta (serviços do catálogo não contratados)
      - Histórico de entregas concluídas
      - Score de saúde >= 60

    Bloqueia por:
      - Expansão ativa já existente para esta conta
      - Cooldown de 30 dias desde última oferta
      - Cooldown de 90 dias para expansões descartadas recentemente

    Retorna lista de sugestões enriquecidas.
    """
    score_saude = contexto.get("score_saude", 0)
    if score_saude < 60:
        return []

    # Verificar expansões ativas (max 1 por conta)
    ativas = [
        x for x in expansoes_existentes
        if x.get("conta_id") == conta_id
        and x.get("status") not in _STATUS_FINAIS
    ]
    if ativas:
        return []  # já tem expansão ativa

    # Cooldown: expansão descartada nos últimos 90 dias?
    descartadas_recentes = [
        x for x in expansoes_existentes
        if x.get("conta_id") == conta_id
        and x.get("status") == "descartada"
        and _dias_desde(x.get("atualizado_em", "")) < _COOLDOWN_DESCARTADA_DIAS
    ]
    if descartadas_recentes:
        return []

    # Cooldown: qualquer oferta nos últimos 30 dias?
    recentes = [
        x for x in expansoes_existentes
        if x.get("conta_id") == conta_id
        and _dias_desde(x.get("criado_em", "")) < _INTERVALO_MINIMO_DIAS
    ]
    if recentes:
        return []

    linhas_ativas = set(contexto.get("linhas_ativas", []))
    linhas_conc   = set(contexto.get("linhas_concluidas", []))
    sugestoes     = []

    # Cross-sell: presença digital → automação
    if ("marketing_presenca_digital" in linhas_conc
            and "automacao_atendimento" not in linhas_ativas):
        sugestoes.append({
            "tipo_oportunidade": "cross_sell",
            "oferta_sugerida":   "automacao_atendimento",
            "motivo":            "Presenca digital concluida — automacao de atendimento e o proximo passo natural",
            "prioridade":        "alta",
            "match_gap":         True,
        })

    # Cross-sell: automação → presença digital
    if ("automacao_atendimento" in linhas_conc
            and "marketing_presenca_digital" not in linhas_ativas):
        sugestoes.append({
            "tipo_oportunidade": "cross_sell",
            "oferta_sugerida":   "marketing_presenca_digital",
            "motivo":            "Automacao concluida — presenca digital complementa o resultado obtido",
            "prioridade":        "media",
            "match_gap":         True,
        })

    # Upsell: conta saudável com serviço único há > 30 dias
    if (score_saude >= 75
            and len(linhas_ativas) == 1
            and linhas_conc
            and contexto.get("dias_cliente", 0) >= 30):
        sugestoes.append({
            "tipo_oportunidade": "upsell",
            "oferta_sugerida":   next(iter(linhas_conc), ""),
            "motivo":            "Conta saudavel com servico unico — avaliar expansao de escopo",
            "prioridade":        "media",
            "match_gap":         False,
        })

    # Renovação: entrega concluída há > 60 dias
    ultima_conc_ts = contexto.get("ultima_entrega_conc_ts", "")
    if ultima_conc_ts and _dias_desde(ultima_conc_ts) > 60:
        sugestoes.append({
            "tipo_oportunidade": "renovacao",
            "oferta_sugerida":   contexto.get("ultima_linha_conc", ""),
            "motivo":            f"Entrega concluida ha {_dias_desde(ultima_conc_ts)} dias — avaliar renovacao",
            "prioridade":        "baixa",
            "match_gap":         False,
        })

    return sugestoes[:1]  # máximo 1 oportunidade por ciclo por conta


def calcular_score_expansao(conta_id: str, sugestao: dict, contexto: dict) -> dict:
    """
    Calcula score_expansao (0-100) com 5 fatores objetivos.

    Fatores:
      +30  Saúde >= 80
      +20  NPS promotor (score >= 9)
      +15  Tempo de cliente > 60 dias
      +15  Pagamentos em dia
      +20  Match de oferta (preenche lacuna real)

    Classificação:
      >= 70 → expansao_quente
      50-69 → expansao_morna
      <  50 → expansao_fria
    """
    score     = 0
    breakdown = {}

    # Fator 1: Saúde da conta (max 30)
    score_saude = contexto.get("score_saude", 0)
    pts_saude   = 30 if score_saude >= 80 else (15 if score_saude >= 65 else 0)
    score       += pts_saude
    breakdown["saude"] = {"pontos": pts_saude, "score_saude": score_saude}

    # Fator 2: NPS promotor (max 20)
    nps_prom   = contexto.get("nps_promotor", False)
    pts_nps    = 20 if nps_prom else 0
    score      += pts_nps
    breakdown["nps_promotor"] = {"pontos": pts_nps, "promotor": nps_prom}

    # Fator 3: Tempo de cliente (max 15)
    dias_cli  = contexto.get("dias_cliente", 0)
    pts_tempo = 15 if dias_cli > 60 else (8 if dias_cli > 30 else 0)
    score     += pts_tempo
    breakdown["tempo_cliente"] = {"pontos": pts_tempo, "dias": dias_cli}

    # Fator 4: Pagamentos em dia (max 15)
    pag_ok   = contexto.get("pagamentos_em_dia", True)
    pts_pag  = 15 if pag_ok else 0
    score    += pts_pag
    breakdown["pagamentos"] = {"pontos": pts_pag, "em_dia": pag_ok}

    # Fator 5: Match de oferta (max 20)
    match_gap = sugestao.get("match_gap", False)
    pts_match = 20 if match_gap else 8
    score     += pts_match
    breakdown["match_oferta"] = {"pontos": pts_match, "match_gap": match_gap}

    score = min(score, 100)

    if score >= _SCORE_QUENTE:
        classificacao = "expansao_quente"
    elif score >= _SCORE_MORNA:
        classificacao = "expansao_morna"
    else:
        classificacao = "expansao_fria"

    return {
        "score_expansao": score,
        "classificacao":  classificacao,
        "breakdown":      breakdown,
    }


def resumir_para_painel() -> dict:
    """Retorna métricas de expansão para uso no painel."""
    expansoes = _ler(_ARQ_EXPANSAO, [])

    ativas     = [x for x in expansoes if x.get("status") not in _STATUS_FINAIS]
    quentes    = [x for x in ativas if x.get("classificacao") == "expansao_quente"]
    mornas     = [x for x in ativas if x.get("classificacao") == "expansao_morna"]
    frias      = [x for x in ativas if x.get("classificacao") == "expansao_fria"]
    handoffs   = [x for x in ativas if x.get("status") == "handoff_criado"]
    convertidas = [x for x in expansoes if x.get("status") in ("convertida", "convertida_em_oportunidade")]

    total = len(expansoes)
    taxa_conv = round(len(convertidas) / total * 100, 1) if total else 0

    # Top 5 por score
    top5 = sorted(ativas, key=lambda x: x.get("score_expansao", 0), reverse=True)[:5]

    contas   = _ler(_ARQ_CONTAS, [])
    mapa_nomes = {c["id"]: c.get("nome_empresa", "—") for c in contas}
    for exp in top5:
        exp["_nome"] = mapa_nomes.get(exp.get("conta_id", ""), "—")

    return {
        "total":           total,
        "ativas":          len(ativas),
        "quentes":         len(quentes),
        "mornas":          len(mornas),
        "frias":           len(frias),
        "handoffs":        len(handoffs),
        "convertidas":     len(convertidas),
        "taxa_conversao":  taxa_conv,
        "top5":            top5,
    }


# ─── Funções internas ─────────────────────────────────────────────────────────

def _montar_contexto_expansao(conta: dict, saude: dict,
                               pipeline_entrega: list) -> dict:
    """
    Monta contexto de scoring e detecção para uma conta.
    """
    conta_id = conta["id"]
    hoje     = datetime.now()

    # Tempo de cliente
    dias_cliente = _dias_desde(conta.get("criado_em", ""))

    # Linhas de serviço ativas e concluídas
    _conc_status = {"concluida", "entregue", "finalizada"}
    _ativas_status = {"onboarding", "em_execucao", "aguardando_insumo",
                      "concluida", "entregue", "finalizada"}
    entregas = [e for e in pipeline_entrega if e.get("conta_id") == conta_id]
    linhas_ativas    = list({e.get("linha_servico","") for e in entregas})
    linhas_concluidas = list({e.get("linha_servico","") for e in entregas
                               if e.get("status_entrega") in _conc_status})

    # Última entrega concluída
    concs = [e for e in entregas if e.get("status_entrega") in _conc_status]
    ult_conc = max(concs, key=lambda e: e.get("registrado_em",""), default={}) if concs else {}

    # Pagamentos em dia (sem parcelas atrasadas)
    pagamentos_em_dia = True
    try:
        rec = _ler(_ARQ_RECEBIVEIS, [])
        if isinstance(rec, dict):
            rec = rec.get("recebiveis", [])
        for r in rec:
            if r.get("conta_id") != conta_id:
                continue
            if r.get("status") not in ("em_aberto", "atrasado", "pendente"):
                continue
            venc = r.get("data_vencimento", "")
            if not venc:
                continue
            try:
                if (hoje - datetime.fromisoformat(venc)).days > 0:
                    pagamentos_em_dia = False
                    break
            except Exception as _err:
                log.warning("erro ignorado: %s", _err)
    except Exception as _err:
        log.warning("erro ignorado: %s", _err)

    # NPS promotor (score >= 9 nos últimos 90 dias)
    nps_promotor = False
    try:
        respostas = _ler(_ARQ_NPS, [])
        for r in respostas:
            if r.get("conta_id") == conta_id and r.get("score", 0) >= 9:
                if _dias_desde(r.get("respondido_em", "")) <= 90:
                    nps_promotor = True
                    break
    except Exception as _err:
        log.warning("erro ignorado: %s", _err)

    return {
        "score_saude":            saude.get("score_saude", 0),
        "status_saude":           saude.get("status_saude", ""),
        "dias_cliente":           dias_cliente,
        "linhas_ativas":          linhas_ativas,
        "linhas_concluidas":      linhas_concluidas,
        "ultima_entrega_id":      ult_conc.get("id", ""),
        "ultima_linha_conc":      ult_conc.get("linha_servico", ""),
        "ultima_entrega_conc_ts": ult_conc.get("registrado_em", ""),
        "pagamentos_em_dia":      pagamentos_em_dia,
        "nps_promotor":           nps_promotor,
    }


def _preparar_pitch(conta: dict, sugestao: dict, contexto: dict,
                     router, log_externo) -> str:
    """
    Gera pitch personalizado via LLM redigir().
    Fallback: template genérico.
    """
    # Template fallback
    oferta     = sugestao.get("oferta_sugerida", "nosso próximo serviço")
    nome_conta = conta.get("nome_empresa", "Cliente")
    servicos   = ", ".join(contexto.get("linhas_concluidas", ["serviços anteriores"])) or "serviços anteriores"
    pitch_base = (
        f"Olá, equipe {nome_conta}.\n\n"
        f"Com base nos resultados obtidos com {servicos}, "
        f"identificamos uma oportunidade de {sugestao.get('motivo','expandir nossa parceria')}.\n\n"
        f"A proposta é avançar com {oferta}, que complementa diretamente o que já construímos juntos.\n\n"
        f"Podemos agendar uma conversa rápida para apresentar os detalhes?"
    )

    try:
        res = router.redigir({
            "agente": "agente_customer_success",
            "tarefa": "redigir_pitch_expansao",
            "dados": {
                "conta":           nome_conta,
                "categoria":       conta.get("categoria", ""),
                "servicos_ativos": contexto.get("linhas_concluidas", []),
                "oferta_nova":     oferta,
                "motivo":          sugestao.get("motivo", ""),
                "score_saude":     contexto.get("score_saude", 0),
                "nps_promotor":    contexto.get("nps_promotor", False),
            },
            "empresa_id": conta["id"],
        })
        if res.get("sucesso") and not res.get("fallback_usado"):
            resultado = res.get("resultado", "")
            if isinstance(resultado, str) and len(resultado) > 30:
                log_externo.info(f"  [llm] pitch personalizado gerado para conta={conta['id']}")
                return resultado
    except Exception as exc:
        log_externo.warning(f"  [llm] falha no pitch para {conta['id']}: {exc}")

    return pitch_base


def _criar_handoff_expansao(exp_id: str, conta: dict,
                              sugestao: dict, score: int) -> "dict | None":
    """Cria handoff para agente_comercial em handoffs_agentes.json."""
    handoffs = _ler(_ARQ_HANDOFFS, [])

    # Dedup: já existe handoff para este exp_id?
    if any(h.get("referencia_id") == exp_id for h in handoffs):
        return None

    agora   = _agora()
    hf_id   = f"hf_exp_{uuid.uuid4().hex[:8]}"
    handoff = {
        "id":             hf_id,
        "agente_origem":  "agente_customer_success",
        "agente_destino": "agente_comercial",
        "tipo":           "expansao",
        "referencia_id":  exp_id,
        "contraparte":    conta.get("nome_empresa", ""),
        "conta_id":       conta["id"],
        "origem_oportunidade": "expansao_cs",
        "descricao": (
            f"Expansao detectada: {sugestao.get('oferta_sugerida','?')} | "
            f"score={score} | {sugestao.get('motivo','')[:60]}"
        ),
        "status":         "pendente",
        "urgencia":       "alta" if score >= 80 else "normal",
        "registrado_em":  agora,
        "atualizado_em":  agora,
    }
    handoffs.append(handoff)
    _salvar(_ARQ_HANDOFFS, handoffs)
    return handoff


def _salvar_pitch(exp_id: str, conta_id: str, sugestao: dict,
                  pitch: str, score: int) -> None:
    """Persiste pitch em propostas_expansao.json."""
    pitches = _ler(_ARQ_PITCHES, [])

    # Dedup
    if any(p.get("expansao_id") == exp_id for p in pitches):
        return

    pitches.append({
        "id":               f"pexp_{uuid.uuid4().hex[:8]}",
        "expansao_id":      exp_id,
        "conta_id":         conta_id,
        "oferta_sugerida":  sugestao.get("oferta_sugerida", ""),
        "tipo_oportunidade": sugestao.get("tipo_oportunidade", ""),
        "pitch":            pitch,
        "score_expansao":   score,
        "status":           "rascunho",
        "criado_em":        _agora(),
    })
    _salvar(_ARQ_PITCHES, pitches)
