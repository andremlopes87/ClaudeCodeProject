"""
core/acompanhamento_contas.py

Camada de acompanhamento pós-entrega e expansão de conta da Vetor.

Fecha o ciclo da relação com cada cliente:
  entrega concluída → saúde da conta → satisfação → potencial de expansão
  → sugestão de upsell/cross-sell/renovação → nova oportunidade comercial

Não envia nada. Não cria agente. Apenas classifica, registra e sugere.

Arquivos gerenciados:
  dados/acompanhamentos_contas.json
  dados/saude_contas.json
  dados/oportunidades_expansao.json
  dados/historico_acompanhamento_contas.json
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_ACOMP   = config.PASTA_DADOS / "acompanhamentos_contas.json"
_ARQ_SAUDE   = config.PASTA_DADOS / "saude_contas.json"
_ARQ_EXPANSAO = config.PASTA_DADOS / "oportunidades_expansao.json"
_ARQ_HIST    = config.PASTA_DADOS / "historico_acompanhamento_contas.json"

# Referências (leitura ou update mínimo)
_ARQ_PIPELINE  = config.PASTA_DADOS / "pipeline_comercial.json"
_ARQ_ENTREGA   = config.PASTA_DADOS / "pipeline_entrega.json"
_ARQ_PROPOSTAS = config.PASTA_DADOS / "propostas_comerciais.json"
_ARQ_CONTAS    = config.PASTA_DADOS / "contas_clientes.json"

_STATUS_ENTREGA_ELEGIVEL = {"onboarding", "em_execucao", "aguardando_insumo",
                             "concluida", "entregue", "finalizada"}
_STATUS_ENTREGA_CONCLUIDA = {"concluida", "entregue", "finalizada"}


# ─── I/O ──────────────────────────────────────────────────────────────────────

def _ler(arq: Path, padrao):
    try:
        if arq.exists():
            return json.loads(arq.read_text(encoding="utf-8")) or padrao
    except Exception:
        pass
    return padrao


def _salvar(arq: Path, dados) -> None:
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ─── Cálculo de saúde ─────────────────────────────────────────────────────────

def calcular_saude_conta(conta_id: str,
                          pipeline_entrega: "list | None" = None) -> dict:
    """
    Calcula score de saúde da conta com regras explícitas e auditáveis.
    Score base: 60. Ajustes determinísticos a seguir.

    Retorna dict com score_saude, status_saude, motivos, e flags.
    """
    contas    = _ler(_ARQ_CONTAS, [])
    conta     = next((c for c in contas if c["id"] == conta_id), None)
    if not conta:
        return {"score_saude": 50, "status_saude": "boa", "motivos": [], "risco_churn": False}

    if pipeline_entrega is None:
        pipeline_entrega = _ler(_ARQ_ENTREGA, [])
    propostas   = _ler(_ARQ_PROPOSTAS, [])
    acomps      = _ler(_ARQ_ACOMP, [])

    entregas    = [e for e in pipeline_entrega if e.get("conta_id") == conta_id]
    concluidas  = [e for e in entregas if e.get("status_entrega") in _STATUS_ENTREGA_CONCLUIDA]
    em_exec     = [e for e in entregas if e.get("status_entrega") in ("onboarding", "em_execucao")]
    bloqueadas  = [e for e in entregas if e.get("status_entrega") == "aguardando_insumo"]

    score   = 60
    motivos = []

    if not entregas:
        return {
            "score_saude":       60,
            "status_saude":      "boa",
            "motivos":           ["sem entregas — score neutro"],
            "entregas_concluidas": 0,
            "entregas_bloqueadas": 0,
            "satisfacao_detectada": None,
            "risco_churn":       False,
            "potencial_expansao": False,
        }

    # Entregas concluídas
    if concluidas:
        delta = min(len(concluidas) * 15, 25)
        score += delta
        motivos.append(f"{len(concluidas)} concluída(s) +{delta}")

    # Entregas em andamento
    if em_exec:
        score += 5
        motivos.append(f"{len(em_exec)} em execução +5")

    # Bloqueios
    if bloqueadas:
        delta = min(len(bloqueadas) * 10, 20)
        score -= delta
        motivos.append(f"{len(bloqueadas)} bloqueada(s) -{delta}")

    # Proposta aceita
    props_aceitas = [p for p in propostas
                     if p.get("conta_id") == conta_id and p.get("status") == "aceita"]
    if props_aceitas:
        score += 10
        motivos.append("proposta aceita +10")

    # Risco de relacionamento
    if conta.get("risco_relacionamento"):
        score -= 25
        motivos.append("risco_relacionamento -25")

    # Satisfação e NPS dos acompanhamentos
    acomps_conta = [a for a in acomps
                    if a.get("conta_id") == conta_id
                    and a.get("status") not in ("arquivado",)]
    satisfacao_detectada = None
    for acomp in acomps_conta:
        sat = acomp.get("satisfacao", "")
        if sat == "alta" and satisfacao_detectada != "baixa":
            score += 15
            satisfacao_detectada = "alta"
            motivos.append("satisfacao=alta +15")
        elif sat == "baixa":
            score -= 20
            satisfacao_detectada = "baixa"
            motivos.append("satisfacao=baixa -20")
        elif sat == "media" and not satisfacao_detectada:
            satisfacao_detectada = "media"

        nps = acomp.get("nps_opcional")
        if nps is not None:
            try:
                nps_int = int(nps)
                if nps_int >= 8:
                    score += 10
                    motivos.append(f"nps={nps_int} +10")
                elif nps_int <= 5:
                    score -= 15
                    motivos.append(f"nps={nps_int} -15")
            except (ValueError, TypeError):
                pass

    # Ausência longa de acompanhamento com entrega concluída
    if concluidas and acomps_conta:
        mais_recente = max(
            (a.get("atualizado_em", a.get("registrado_em", "")) for a in acomps_conta),
            default="",
        )
        if mais_recente:
            try:
                dias = (datetime.now() - datetime.fromisoformat(mais_recente)).days
                if dias > 90:
                    score -= 10
                    motivos.append(f"sem acompanhamento há {dias} dias -10")
                elif dias <= 14:
                    score += 5
                    motivos.append("acompanhamento recente +5")
            except ValueError:
                pass

    score = max(0, min(100, score))

    if score >= 80:
        status = "excelente"
    elif score >= 60:
        status = "boa"
    elif score >= 40:
        status = "atencao"
    else:
        status = "critica"

    risco_churn = score < 40 or bool(conta.get("risco_relacionamento"))

    return {
        "score_saude":          score,
        "status_saude":         status,
        "motivos":              motivos,
        "entregas_concluidas":  len(concluidas),
        "entregas_bloqueadas":  len(bloqueadas),
        "satisfacao_detectada": satisfacao_detectada,
        "risco_churn":          risco_churn,
        "potencial_expansao":   score >= 65 and len(concluidas) > 0,
    }


# ─── Atualização de saúde na conta ────────────────────────────────────────────

def atualizar_saude_conta(conta_id: str, saude: "dict | None" = None) -> dict:
    """
    Persiste saúde em saude_contas.json e enriquece contas_clientes.json.
    Se saude=None, recalcula automaticamente.
    """
    if saude is None:
        saude = calcular_saude_conta(conta_id)

    agora     = _agora()
    registro  = {
        "conta_id":              conta_id,
        "status_saude":          saude["status_saude"],
        "score_saude":           saude["score_saude"],
        "satisfacao_atual":      saude.get("satisfacao_detectada"),
        "entregas_concluidas":   saude.get("entregas_concluidas", 0),
        "entregas_bloqueadas":   saude.get("entregas_bloqueadas", 0),
        "ultima_interacao_relevante": agora,
        "risco_churn":           saude.get("risco_churn", False),
        "potencial_expansao":    saude.get("potencial_expansao", False),
        "recomendacao_sistema":  _recomendar_acao(saude),
        "motivos":               saude.get("motivos", []),
        "atualizado_em":         agora,
    }

    saudes = _ler(_ARQ_SAUDE, [])
    idx = next((i for i, s in enumerate(saudes) if s.get("conta_id") == conta_id), None)
    if idx is not None:
        saudes[idx] = registro
    else:
        saudes.append(registro)
    _salvar(_ARQ_SAUDE, saudes)

    # Enriquecer conta
    contas = _ler(_ARQ_CONTAS, [])
    conta  = next((c for c in contas if c["id"] == conta_id), None)
    if conta:
        conta["status_saude"]          = saude["status_saude"]
        conta["score_saude"]           = saude["score_saude"]
        conta["potencial_expansao"]    = saude.get("potencial_expansao", False)
        conta["cliente_em_risco"]      = saude.get("risco_churn", False)
        conta["risco_relacionamento"]  = saude.get("risco_churn", False) or conta.get("risco_relacionamento", False)
        conta["ultimo_acompanhamento_em"] = agora
        conta["atualizado_em"]         = agora
        _salvar(_ARQ_CONTAS, contas)

    _registrar_historico(conta_id, "", "saude_recalculada",
                         f"score={saude['score_saude']} status={saude['status_saude']}", "acompanhamento_contas")

    return registro


def _recomendar_acao(saude: dict) -> str:
    if saude.get("risco_churn"):
        return "Contato de relacionamento urgente — conta em risco"
    if saude.get("potencial_expansao"):
        return "Avaliar oportunidade de expansão — conta saudável"
    if saude.get("entregas_bloqueadas", 0) > 0:
        return "Resolver bloqueios de entrega antes de qualquer expansão"
    if saude["status_saude"] == "excelente":
        return "Conta em excelente estado — ideal para upsell ou renovação"
    return "Manter acompanhamento periódico"


# ─── Criação de acompanhamento ────────────────────────────────────────────────

def criar_acompanhamento(entrega: dict, conta_id: str,
                          tipo: str, origem: str = "") -> dict:
    """Cria um registro de acompanhamento para a entrega/conta."""
    agora    = _agora()
    acomp_id = f"acomp_{uuid.uuid4().hex[:8]}"
    objetivo = {
        "validacao_resultado":      "Validar resultado entregue e registrar satisfação do cliente",
        "checkin_pos_entrega":      "Check-in leve para verificar adaptação e novas necessidades",
        "onboarding_concluido":     "Confirmar conclusão do onboarding e alinhar próximos passos",
        "acompanhamento_recorrente": "Manutenção de relacionamento ativo com o cliente",
        "risco_relacionamento":     "Entender causa do risco e definir plano de recuperação",
        "expansao_comercial":       "Apresentar nova oportunidade de serviço ao cliente",
    }.get(tipo, "Acompanhamento do cliente")

    acomp = {
        "id":                   acomp_id,
        "conta_id":             conta_id,
        "entrega_id":           entrega.get("id", ""),
        "oportunidade_id":      entrega.get("oportunidade_id", ""),
        "proposta_id":          entrega.get("proposta_id", ""),
        "tipo_acompanhamento":  tipo,
        "status":               "novo",
        "objetivo":             objetivo,
        "resumo":               "",
        "satisfacao":           "",
        "nps_opcional":         None,
        "risco_percebido":      False,
        "potencial_expansao":   False,
        "proxima_acao_sugerida": "",
        "linha_servico":        entrega.get("linha_servico", ""),
        "origem":               origem,
        "registrado_em":        agora,
        "atualizado_em":        agora,
        "concluido_em":         None,
    }

    _registrar_historico(conta_id, acomp_id, "acompanhamento_criado",
                         f"Tipo={tipo} para entrega {entrega.get('id','')}", origem)
    log.info(f"[acompanhamento] criado {acomp_id} | conta={conta_id} | tipo={tipo}")
    return acomp


# ─── Registro de satisfação ───────────────────────────────────────────────────

def registrar_satisfacao(acomp_id: str, satisfacao: str,
                          nps: "int | None" = None,
                          resumo: str = "", origem: str = "") -> bool:
    """
    Registra satisfação em um acompanhamento existente.
    satisfacao: alta | media | baixa
    """
    acomps = _ler(_ARQ_ACOMP, [])
    acomp  = next((a for a in acomps if a["id"] == acomp_id), None)
    if not acomp:
        return False

    agora = _agora()
    acomp["satisfacao"]     = satisfacao
    acomp["nps_opcional"]   = nps
    if resumo:
        acomp["resumo"]     = resumo
    acomp["status"]         = "em_andamento"
    acomp["atualizado_em"]  = agora
    _salvar(_ARQ_ACOMP, acomps)

    conta_id = acomp.get("conta_id", "")
    _registrar_historico(conta_id, acomp_id, "satisfacao_registrada",
                         f"satisfacao={satisfacao} nps={nps}", origem)
    if conta_id:
        atualizar_saude_conta(conta_id)
    return True


# ─── Sugestão de expansão ─────────────────────────────────────────────────────

def sugerir_expansao_para_conta(conta_id: str,
                                 pipeline_entrega: "list | None" = None) -> list:
    """
    Retorna lista de sugestões de expansão com base em sinais concretos.
    Conservador: só sugere quando há evidência real.
    Score mínimo para sugerir: 50.
    """
    saude = calcular_saude_conta(conta_id, pipeline_entrega)
    if saude["score_saude"] < 50:
        return []  # conta em problema — não expandir agora

    contas  = _ler(_ARQ_CONTAS, [])
    conta   = next((c for c in contas if c["id"] == conta_id), None)
    if not conta:
        return []

    if pipeline_entrega is None:
        pipeline_entrega = _ler(_ARQ_ENTREGA, [])

    expansoes_existentes = _ler(_ARQ_EXPANSAO, [])
    # Expansões ativas (não descartadas/arquivadas/convertidas)
    ativas = [x for x in expansoes_existentes
              if x.get("conta_id") == conta_id
              and x.get("status") not in ("descartada", "arquivada", "convertida_em_oportunidade")]
    tipos_ativos   = {x.get("tipo_oportunidade") for x in ativas}
    ofertas_ativas = {x.get("oferta_sugerida") for x in ativas}

    entregas      = [e for e in pipeline_entrega if e.get("conta_id") == conta_id]
    concluidas    = [e for e in entregas if e.get("status_entrega") in _STATUS_ENTREGA_CONCLUIDA]
    linhas_ativas = {e.get("linha_servico", "") for e in entregas}
    linhas_conc   = {e.get("linha_servico", "") for e in concluidas}

    sugestoes = []

    # Cross-sell: marketing → automacao
    if ("marketing_presenca_digital" in linhas_conc
            and "automacao_atendimento" not in linhas_ativas
            and "automacao_atendimento" not in ofertas_ativas):
        sugestoes.append({
            "tipo_oportunidade": "cross_sell",
            "oferta_sugerida":   "automacao_atendimento",
            "motivo":            "Presença digital concluída — automação de atendimento é o próximo passo natural",
            "prioridade":        "media",
        })

    # Cross-sell: automacao → marketing
    if ("automacao_atendimento" in linhas_conc
            and "marketing_presenca_digital" not in linhas_ativas
            and "marketing_presenca_digital" not in ofertas_ativas):
        sugestoes.append({
            "tipo_oportunidade": "cross_sell",
            "oferta_sugerida":   "marketing_presenca_digital",
            "motivo":            "Automação concluída — presença digital complementa o resultado obtido",
            "prioridade":        "media",
        })

    # Renovação: entrega concluída há > 60 dias
    if "renovacao" not in tipos_ativos:
        for ent in concluidas:
            reg = ent.get("registrado_em", "")
            if not reg:
                continue
            try:
                dias = (datetime.now() - datetime.fromisoformat(reg)).days
                if dias > 60:
                    sugestoes.append({
                        "tipo_oportunidade": "renovacao",
                        "oferta_sugerida":   ent.get("linha_servico", ""),
                        "motivo":            f"Entrega concluída há {dias} dias — avaliar renovação do serviço",
                        "prioridade":        "baixa",
                    })
                    break  # só uma renovação por vez
            except ValueError:
                pass

    # Reativação: cliente inativo com saúde razoável
    if (conta.get("status_relacionamento") == "cliente_inativo"
            and saude["score_saude"] >= 55
            and "reativacao" not in tipos_ativos):
        sugestoes.append({
            "tipo_oportunidade": "reativacao",
            "oferta_sugerida":   "",
            "motivo":            "Conta inativa com histórico positivo — potencial para reativação",
            "prioridade":        "alta",
        })

    # Upsell: conta ativa com apenas 1 linha e score alto
    if (saude["score_saude"] >= 75
            and len(linhas_ativas) == 1
            and "upsell" not in tipos_ativos
            and concluidas):
        sugestoes.append({
            "tipo_oportunidade": "upsell",
            "oferta_sugerida":   next(iter(linhas_conc), ""),
            "motivo":            "Conta saudável com serviço único — avaliar expansão de escopo",
            "prioridade":        "baixa",
        })

    return sugestoes


def criar_oportunidade_expansao(conta_id: str, entrega_id: str,
                                 sugestao: dict, origem: str = "") -> dict:
    """Cria entrada em oportunidades_expansao.json."""
    agora = _agora()
    exp_id = f"exp_{uuid.uuid4().hex[:8]}"
    expansao = {
        "id":                exp_id,
        "conta_id":          conta_id,
        "entrega_id":        entrega_id,
        "tipo_oportunidade": sugestao.get("tipo_oportunidade", ""),
        "origem":            origem,
        "oferta_sugerida":   sugestao.get("oferta_sugerida", ""),
        "pacote_sugerido":   sugestao.get("pacote_sugerido", ""),
        "motivo":            sugestao.get("motivo", ""),
        "prioridade":        sugestao.get("prioridade", "media"),
        "status":            "sugerida",
        "requer_deliberacao": sugestao.get("prioridade") == "alta",
        "oportunidade_id_gerada": None,
        "criado_em":         agora,
        "atualizado_em":     agora,
    }
    expansoes = _ler(_ARQ_EXPANSAO, [])
    expansoes.append(expansao)
    _salvar(_ARQ_EXPANSAO, expansoes)

    _registrar_historico(conta_id, "", "oportunidade_expansao_sugerida",
                         f"{sugestao.get('tipo_oportunidade')} — {sugestao.get('motivo','')[:60]}",
                         origem)
    log.info(f"[expansao] sugerida {exp_id} | {sugestao.get('tipo_oportunidade')} | conta={conta_id}")
    return expansao


# ─── Processamento em lote (chamado pelos agentes) ────────────────────────────

def processar_acompanhamentos_entrega(pipeline_entrega: list,
                                       origem: str = "agente_operacao_entrega") -> dict:
    """
    Para cada entrega elegível com conta_id:
    1. Cria acompanhamento se não existir
    2. Recalcula saúde da conta
    3. Sugere expansão se aplicável

    Chamado pelo agente_operacao_entrega após processar entregas.
    """
    acomps = _ler(_ARQ_ACOMP, [])
    n_criados   = 0
    n_saudes    = 0
    n_expansoes = 0

    # Contas já processadas nesta execução (para não recalcular saúde múltiplas vezes)
    contas_processadas: set = set()

    for entrega in pipeline_entrega:
        conta_id = entrega.get("conta_id", "")
        status   = entrega.get("status_entrega", "")

        if not conta_id or status not in _STATUS_ENTREGA_ELEGIVEL:
            continue

        ent_id = entrega.get("id", "")

        # Verificar se já existe acompanhamento para esta entrega
        ja_tem = any(a.get("entrega_id") == ent_id and a.get("status") != "arquivado"
                     for a in acomps)
        if not ja_tem:
            tipo = ("validacao_resultado"
                    if status in _STATUS_ENTREGA_CONCLUIDA
                    else "checkin_pos_entrega")
            acomp = criar_acompanhamento(entrega, conta_id, tipo, origem)
            acomps.append(acomp)
            n_criados += 1

        # Saúde — apenas uma vez por conta
        if conta_id not in contas_processadas:
            saude = calcular_saude_conta(conta_id, pipeline_entrega)
            atualizar_saude_conta(conta_id, saude)
            n_saudes += 1
            contas_processadas.add(conta_id)

            # Sugerir expansão se aplicável
            if saude.get("potencial_expansao"):
                sugestoes = sugerir_expansao_para_conta(conta_id, pipeline_entrega)
                for sug in sugestoes:
                    criar_oportunidade_expansao(conta_id, ent_id, sug, origem)
                    n_expansoes += 1

    _salvar(_ARQ_ACOMP, acomps)
    log.info(f"[acompanhamento] criados={n_criados} saudes={n_saudes} expansoes={n_expansoes}")
    return {"criados": n_criados, "saudes_recalculadas": n_saudes, "expansoes_sugeridas": n_expansoes}


def processar_expansoes_para_handoff(pipeline: list,
                                      origem: str = "agente_comercial") -> dict:
    """
    Lê expansões com status=pronta_para_handoff e cria nova oportunidade
    no pipeline_comercial para cada uma.
    Não duplica se já existir opp de expansao para a mesma conta/oferta.
    """
    expansoes = _ler(_ARQ_EXPANSAO, [])
    prontas   = [x for x in expansoes if x.get("status") == "pronta_para_handoff"]
    contas    = _ler(_ARQ_CONTAS, [])
    n_conv    = 0
    agora     = _agora()

    for exp in prontas:
        conta_id      = exp.get("conta_id", "")
        oferta        = exp.get("oferta_sugerida", "")
        conta         = next((c for c in contas if c["id"] == conta_id), None)
        if not conta:
            continue

        # Dedup: não criar se já existe opp de expansao ativa para mesma conta+oferta
        ja_existe = any(
            o.get("conta_id") == conta_id
            and o.get("origem_oportunidade") == "expansao_conta"
            and o.get("linha_servico_sugerida") == oferta
            and o.get("estagio") not in ("ganho", "perdido", "encerrado")
            for o in pipeline
        )
        if ja_existe:
            exp["status"]       = "convertida_em_oportunidade"
            exp["atualizado_em"] = agora
            continue

        # Criar nova oportunidade
        opp_id = f"opp_exp_{uuid.uuid4().hex[:8]}"
        opp = {
            "id":                     opp_id,
            "contraparte":            conta.get("nome_empresa", ""),
            "nome":                   conta.get("nome_empresa", ""),
            "categoria":              conta.get("categoria", ""),
            "cidade":                 conta.get("cidade", ""),
            "email":                  conta.get("email_principal", ""),
            "telefone":               conta.get("telefone_principal", ""),
            "whatsapp":               conta.get("whatsapp", ""),
            "conta_id":               conta_id,
            "estagio":                "qualificado",
            "status_operacional":     "em_qualificacao",
            "origem_oportunidade":    "expansao_conta",
            "linha_servico_sugerida": oferta,
            "prioridade":             exp.get("prioridade", "media"),
            "observacoes_expansao":   exp.get("motivo", ""),
            "expansao_id":            exp["id"],
            "criado_em":              agora,
            "atualizado_em":          agora,
        }
        pipeline.append(opp)
        exp["status"]               = "convertida_em_oportunidade"
        exp["oportunidade_id_gerada"] = opp_id
        exp["atualizado_em"]        = agora
        n_conv += 1

        _registrar_historico(conta_id, "", "oportunidade_expansao_convertida",
                             f"Opp {opp_id} criada via expansao {exp['id']}", origem)
        log.info(f"[expansao] convertida {exp['id']} → opp {opp_id} | conta={conta_id}")

    _salvar(_ARQ_EXPANSAO, expansoes)
    return {"convertidas": n_conv}


# ─── Consultas para o painel ─────────────────────────────────────────────────

def carregar_acompanhamentos() -> list:
    return _ler(_ARQ_ACOMP, [])


def carregar_saude_contas() -> list:
    return _ler(_ARQ_SAUDE, [])


def carregar_expansoes() -> list:
    return _ler(_ARQ_EXPANSAO, [])


def obter_acompanhamentos_conta(conta_id: str) -> list:
    return [a for a in _ler(_ARQ_ACOMP, [])
            if a.get("conta_id") == conta_id
            and a.get("status") != "arquivado"]


def obter_expansoes_conta(conta_id: str) -> list:
    return [x for x in _ler(_ARQ_EXPANSAO, [])
            if x.get("conta_id") == conta_id
            and x.get("status") not in ("descartada", "arquivada")]


def obter_saude_conta(conta_id: str) -> "dict | None":
    return next((s for s in _ler(_ARQ_SAUDE, []) if s.get("conta_id") == conta_id), None)


def resumir_para_painel() -> dict:
    acomps   = _ler(_ARQ_ACOMP, [])
    saudes   = _ler(_ARQ_SAUDE, [])
    expansoes = _ler(_ARQ_EXPANSAO, [])

    abertos   = [a for a in acomps if a.get("status") in ("novo", "em_andamento")]
    em_risco  = [s for s in saudes if s.get("status_saude") in ("atencao", "critica")]
    pot_exp   = [s for s in saudes if s.get("potencial_expansao")]
    exp_sug   = [x for x in expansoes if x.get("status") == "sugerida"]
    exp_conv  = [x for x in expansoes if x.get("status") == "convertida_em_oportunidade"]
    exp_hand  = [x for x in expansoes if x.get("status") == "pronta_para_handoff"]

    return {
        "total_acompanhamentos":          len(acomps),
        "acompanhamentos_abertos":        len(abertos),
        "contas_em_risco":                len(em_risco),
        "contas_com_potencial_expansao":  len(pot_exp),
        "oportunidades_expansao_sugeridas": len(exp_sug),
        "oportunidades_expansao_handoff": len(exp_hand),
        "oportunidades_expansao_convertidas": len(exp_conv),
    }


# ─── Histórico interno ────────────────────────────────────────────────────────

def _registrar_historico(conta_id: str, acomp_id: str,
                          evento: str, descricao: str, origem: str = "") -> None:
    hist = _ler(_ARQ_HIST, [])
    hist.append({
        "id":                f"hacomp_{uuid.uuid4().hex[:8]}",
        "conta_id":          conta_id,
        "acompanhamento_id": acomp_id,
        "evento":            evento,
        "descricao":         descricao,
        "origem":            origem,
        "registrado_em":     _agora(),
    })
    _salvar(_ARQ_HIST, hist)
