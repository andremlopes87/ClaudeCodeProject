"""
core/nps_feedback.py

Coleta automatizada de NPS e feedback com análise LLM e ações derivadas.

Responsabilidade:
  Programar pesquisas NPS nos momentos certos, preparar envios personalizados,
  registrar respostas, analisar sentimento via LLM e derivar ações automáticas.

Sem envio real — NPS fica em fila. Respostas simuladas em dry-run para validação.

Arquivos gerenciados:
  dados/nps_pendentes.json        — pesquisas aguardando envio
  dados/nps_respostas.json        — respostas recebidas
  dados/historico_nps.json        — log de todas as atividades NPS
"""

import json
import logging
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_PENDENTES  = config.PASTA_DADOS / "nps_pendentes.json"
_ARQ_RESPOSTAS  = config.PASTA_DADOS / "nps_respostas.json"
_ARQ_HISTORICO  = config.PASTA_DADOS / "historico_nps.json"
_ARQ_CONTAS     = config.PASTA_DADOS / "contas_clientes.json"
_ARQ_CONTATOS   = config.PASTA_DADOS / "contatos_contas.json"
_ARQ_ENTREGA    = config.PASTA_DADOS / "pipeline_entrega.json"
_ARQ_ACOES_CS   = config.PASTA_DADOS / "acoes_customer_success.json"
_ARQ_EXPANSAO   = config.PASTA_DADOS / "oportunidades_expansao.json"
_ARQ_ACOMPS     = config.PASTA_DADOS / "acompanhamentos_contas.json"

# Momentos de disparo configuráveis
GATILHOS_NPS = {
    "pos_entrega":  {"dias_apos": 7,  "descricao": "7 dias apos conclusao de entrega"},
    "primeiro_mes": {"dias_apos": 30, "descricao": "30 dias de cliente ativo"},
    "trimestral":   {"dias_apos": 90, "recorrente": True, "descricao": "A cada 90 dias"},
}

_STATUS_ATIVOS     = {"cliente_ativo", "cliente_em_implantacao"}
_STATUS_ENTREGA_OK = {"concluida", "entregue", "finalizada"}

# Janela mínima entre NPS para a mesma conta (qualquer gatilho)
_JANELA_MINIMA_DIAS = 30


# ─── I/O helpers ──────────────────────────────────────────────────────────────

def _ler(arq: Path, padrao):
    try:
        if arq.exists():
            return json.loads(arq.read_text(encoding="utf-8")) or padrao
    except Exception:
        pass
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


def _hoje() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _dias_desde(ts: str) -> int:
    """Retorna dias desde um timestamp ISO. Retorna 9999 se inválido."""
    if not ts:
        return 9999
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).days
    except Exception:
        return 9999


# ─── API pública ──────────────────────────────────────────────────────────────

def programar_nps(conta_id: str, gatilho: str,
                   contato_id: str = "") -> "dict | None":
    """
    Cria entrada em nps_pendentes.json para envio futuro.

    Regras:
    - Não duplica se já existe NPS pendente do mesmo gatilho para a conta.
    - Não envia se conta teve qualquer NPS nos últimos 30 dias.
    - Busca contato_principal automaticamente se contato_id não fornecido.

    Retorna o NPS criado, ou None se pulado.
    """
    pendentes  = _ler(_ARQ_PENDENTES, [])
    respostas  = _ler(_ARQ_RESPOSTAS, [])

    # Dedup: já existe pendente com mesmo gatilho?
    ja_pendente = any(
        p.get("conta_id") == conta_id
        and p.get("gatilho") == gatilho
        and p.get("status") == "pendente"
        for p in pendentes
    )
    if ja_pendente:
        log.debug(f"  [nps] dedup pendente: conta={conta_id} gatilho={gatilho}")
        return None

    # Janela mínima: algum NPS (pendente ou respondido) nos últimos 30 dias?
    todos_nps = pendentes + respostas
    for nps in todos_nps:
        if nps.get("conta_id") != conta_id:
            continue
        ts = nps.get("criado_em", nps.get("respondido_em", ""))
        if _dias_desde(ts) < _JANELA_MINIMA_DIAS:
            log.debug(f"  [nps] janela minima: conta={conta_id} — NPS recente")
            return None

    # Resolver contato
    if not contato_id:
        contato_id = _buscar_contato_principal(conta_id)

    cfg_gatilho    = GATILHOS_NPS.get(gatilho, {})
    data_programada = (datetime.now() + timedelta(days=0)).strftime("%Y-%m-%d")

    nps_id = f"nps_{uuid.uuid4().hex[:8]}"
    entrada = {
        "nps_id":           nps_id,
        "conta_id":         conta_id,
        "contato_id":       contato_id,
        "gatilho":          gatilho,
        "gatilho_descricao": cfg_gatilho.get("descricao", gatilho),
        "data_programada":  data_programada,
        "status":           "pendente",
        "criado_em":        _agora(),
    }
    pendentes.append(entrada)
    _salvar(_ARQ_PENDENTES, pendentes)

    _registrar_historico(conta_id, nps_id, "programado", f"gatilho={gatilho}")
    log.info(f"  [nps] programado {nps_id} | conta={conta_id} gatilho={gatilho}")
    return entrada


def verificar_nps_devidos() -> list:
    """
    Lê contas ativas e verifica quais precisam de NPS agora.

    Regras por gatilho:
    - pos_entrega:  conta tem entrega concluída, sem NPS com este gatilho ainda
    - primeiro_mes: conta é cliente há >= 30 dias, sem NPS com este gatilho ainda
    - trimestral:   cliente há >= 90 dias, último NPS há >= 90 dias (ou nunca teve)

    Nunca envia para contas em risco/critico (já tratadas por playbooks).
    Retorna lista de {conta_id, gatilho, motivo}.
    """
    contas    = _ler(_ARQ_CONTAS, [])
    pendentes = _ler(_ARQ_PENDENTES, [])
    respostas = _ler(_ARQ_RESPOSTAS, [])
    pipeline  = _ler(_ARQ_ENTREGA, [])

    todos_nps = pendentes + respostas
    devidos   = []

    for conta in contas:
        if conta.get("status_relacionamento") not in _STATUS_ATIVOS:
            continue

        conta_id = conta["id"]

        # Não enviar para contas em risco/critico
        if conta.get("status_saude") in ("atencao", "critica"):
            continue
        if conta.get("cliente_em_risco"):
            continue

        # Calcular dias de cliente
        dias_cliente = _dias_desde(conta.get("criado_em", ""))

        # NPS desta conta por gatilho (pendente ou respondido)
        nps_conta    = [n for n in todos_nps if n.get("conta_id") == conta_id]
        gatilhos_ok  = {n.get("gatilho") for n in nps_conta}
        ultimo_nps_ts = max(
            (n.get("criado_em", n.get("respondido_em", "")) for n in nps_conta),
            default="",
        )
        dias_ultimo_nps = _dias_desde(ultimo_nps_ts) if ultimo_nps_ts else 9999

        # Janela mínima global: não agendar se há NPS recente
        if dias_ultimo_nps < _JANELA_MINIMA_DIAS:
            continue

        # ── Gatilho: pos_entrega ───────────────────────────────────────────────
        if "pos_entrega" not in gatilhos_ok:
            entrega_concluida = any(
                e.get("conta_id") == conta_id
                and e.get("status_entrega") in _STATUS_ENTREGA_OK
                for e in pipeline
            )
            if entrega_concluida:
                devidos.append({
                    "conta_id": conta_id,
                    "gatilho":  "pos_entrega",
                    "motivo":   "Entrega concluida — NPS pos-entrega devido",
                })
                continue  # um gatilho por ciclo por conta

        # ── Gatilho: primeiro_mes ──────────────────────────────────────────────
        if "primeiro_mes" not in gatilhos_ok and dias_cliente >= 30:
            devidos.append({
                "conta_id": conta_id,
                "gatilho":  "primeiro_mes",
                "motivo":   f"Cliente ha {dias_cliente} dias — NPS do primeiro mes devido",
            })
            continue

        # ── Gatilho: trimestral ────────────────────────────────────────────────
        if dias_cliente >= 90 and dias_ultimo_nps >= 90:
            devidos.append({
                "conta_id": conta_id,
                "gatilho":  "trimestral",
                "motivo":   f"Cliente ha {dias_cliente} dias — NPS trimestral devido",
            })

    log.info(f"  [nps] devidos encontrados: {len(devidos)}")
    return devidos


def preparar_envio_nps(nps_id: str) -> "dict | None":
    """
    Monta payload para envio via email.

    LLM redigir() para personalizar mensagem.
    Fallback: template fixo.

    Retorna payload pronto para fila, ou None se NPS não encontrado.
    """
    pendentes = _ler(_ARQ_PENDENTES, [])
    nps       = next((n for n in pendentes if n.get("nps_id") == nps_id), None)
    if not nps:
        log.warning(f"  [nps] preparar: NPS nao encontrado {nps_id}")
        return None

    conta_id   = nps.get("conta_id", "")
    contato_id = nps.get("contato_id", "")

    contas    = _ler(_ARQ_CONTAS, [])
    conta     = next((c for c in contas if c["id"] == conta_id), {})
    contato   = _buscar_dados_contato(contato_id, conta_id)
    nome_cont = contato.get("nome", conta.get("nome_empresa", "Cliente"))

    # Último serviço entregue
    pipeline    = _ler(_ARQ_ENTREGA, [])
    ult_entrega = next(
        (e for e in reversed(pipeline)
         if e.get("conta_id") == conta_id
         and e.get("status_entrega") in _STATUS_ENTREGA_OK),
        {},
    )
    servico = ult_entrega.get("linha_servico", "nosso serviço")

    # Gerar email via sistema de templates
    corpo   = _template_nps_fixo(nome_cont, servico, nps.get("gatilho", ""))
    assunto = "Sua opinião importa — avalie a Vetor (1 min)"
    try:
        from core.templates_email import gerar_email as _gerar_tmpl
        _dias_ent = str(_dias_desde(
            ult_entrega.get("finalizado_em", "")
            or ult_entrega.get("atualizado_em", "")
        ))
        _email = _gerar_tmpl("nps_pesquisa", {
            "nome_contato":      nome_cont,
            "nome_empresa":      conta.get("nome_empresa", ""),
            "servico_entregue":  servico,
            "dias_desde_entrega": _dias_ent,
        }, empresa_id=conta_id)
        if _email.get("corpo"):
            corpo = _email["corpo"]
        if _email.get("assunto"):
            assunto = _email["assunto"]
        log.info(f"  [nps] email gerado — fonte={_email.get('fonte','?')}")
    except Exception as exc:
        log.warning(f"  [nps] template_email falhou: {exc}")

    payload = {
        "nps_id":           nps_id,
        "conta_id":         conta_id,
        "contato_id":       contato_id,
        "contato_nome":     nome_cont,
        "contato_email":    contato.get("email", conta.get("email_principal", "")),
        "assunto":          assunto,
        "corpo_email":      corpo,
        "canal":            "email",
        "tipo":             "nps",
        "template_usado":   "nps_pesquisa",
        "pronto_para_envio": True,
        "criado_em":        _agora(),
    }

    # Atualizar status do NPS para "preparado"
    for n in pendentes:
        if n.get("nps_id") == nps_id:
            n["status"]      = "preparado"
            n["preparado_em"] = _agora()
            n["payload"]     = payload
            break
    _salvar(_ARQ_PENDENTES, pendentes)
    _registrar_historico(conta_id, nps_id, "preparado", f"email para {nome_cont}")
    return payload


def registrar_resposta_nps(nps_id: str, score: int,
                            comentario: str = "") -> dict:
    """
    Registra resposta de NPS e deriva ações automáticas.

    score <= 6  (detrator): cria ação pb_feedback_negativo + atualiza satisfação
    score 7-8   (neutro):   registra sem ação imediata
    score >= 9  (promotor): cria oportunidade de expansão/indicação

    LLM classificar() analisa sentimento do comentário.
    Fallback: classificação por score numérico.
    """
    from core.llm_router import LLMRouter

    pendentes = _ler(_ARQ_PENDENTES, [])
    respostas = _ler(_ARQ_RESPOSTAS, [])

    # Buscar NPS original
    nps_orig  = next((n for n in pendentes if n.get("nps_id") == nps_id), None)
    conta_id  = nps_orig.get("conta_id", "") if nps_orig else ""

    # Classificar sentimento via LLM
    sentimento     = _classificar_sentimento_por_score(score)
    acoes_derivadas = []
    router = LLMRouter()

    if comentario:
        try:
            res = router.classificar({
                "agente": "agente_customer_success",
                "tarefa": "classificar_sentimento_nps",
                "dados": {
                    "score":      score,
                    "comentario": comentario,
                    "categorias": ["positivo", "positivo_com_ressalva",
                                   "neutro", "negativo", "negativo_grave"],
                },
                "empresa_id": conta_id,
            })
            if res["sucesso"] and not res["fallback_usado"]:
                resultado_llm = res.get("resultado", "")
                _opcoes = ("positivo", "positivo_com_ressalva",
                           "neutro", "negativo", "negativo_grave")
                if isinstance(resultado_llm, str) and resultado_llm in _opcoes:
                    sentimento = resultado_llm
        except Exception as exc:
            log.warning(f"  [nps] classificar sentimento falhou: {exc}")

    # Derivar ações
    if score <= 6:
        acoes_derivadas = _derivar_acao_detrator(conta_id, nps_id, score, comentario)
        log.info(f"  [nps] detrator score={score} conta={conta_id} — playbook ativado")
    elif score >= 9:
        acoes_derivadas = _derivar_acao_promotor(conta_id, nps_id, score)
        log.info(f"  [nps] promotor score={score} conta={conta_id} — expansao/indicacao sugerida")

    # Atualizar acompanhamento
    if conta_id:
        _atualizar_acompanhamento_nps(conta_id, score)

    resposta = {
        "nps_id":          nps_id,
        "conta_id":        conta_id,
        "score":           score,
        "comentario":      comentario,
        "respondido_em":   _agora(),
        "criado_em":       (nps_orig.get("criado_em", _agora()) if nps_orig else _agora()),
        "gatilho":         (nps_orig.get("gatilho", "") if nps_orig else ""),
        "sentimento_llm":  sentimento,
        "acoes_derivadas": acoes_derivadas,
        "tipo_respondente": (
            "promotor" if score >= 9
            else "neutro" if score >= 7
            else "detrator"
        ),
    }
    respostas.append(resposta)
    _salvar(_ARQ_RESPOSTAS, respostas)

    # Marcar NPS como respondido
    for n in pendentes:
        if n.get("nps_id") == nps_id:
            n["status"] = "respondido"
            n["respondido_em"] = _agora()
            break
    _salvar(_ARQ_PENDENTES, pendentes)

    _registrar_historico(conta_id, nps_id, "respondido",
                         f"score={score} sentimento={sentimento}")
    return resposta


def calcular_nps_empresa() -> dict:
    """
    Calcula métricas NPS da empresa a partir de todas as respostas.

    NPS = % promotores (>=9) - % detratores (<=6)
    Retorna dict com score, totais e distribuição.
    """
    respostas = _ler(_ARQ_RESPOSTAS, [])
    if not respostas:
        return {
            "score_nps":    None,
            "total":        0,
            "promotores":   0,
            "neutros":      0,
            "detratores":   0,
            "pct_promotor": 0,
            "pct_detrator": 0,
            "media_score":  0,
            "calculado_em": _agora(),
        }

    total      = len(respostas)
    promotores = sum(1 for r in respostas if r.get("score", 0) >= 9)
    neutros    = sum(1 for r in respostas if 7 <= r.get("score", 0) <= 8)
    detratores = sum(1 for r in respostas if r.get("score", 0) <= 6)
    media      = round(sum(r.get("score", 0) for r in respostas) / total, 1)

    pct_prom = round((promotores / total) * 100, 1)
    pct_det  = round((detratores / total) * 100, 1)
    score_nps = round(pct_prom - pct_det, 1)

    # Por período (últimos 30 e 90 dias)
    agora = datetime.now()
    res_30d = [r for r in respostas
               if _dias_desde(r.get("respondido_em", "")) <= 30]
    res_90d = [r for r in respostas
               if _dias_desde(r.get("respondido_em", "")) <= 90]

    return {
        "score_nps":       score_nps,
        "total":           total,
        "promotores":      promotores,
        "neutros":         neutros,
        "detratores":      detratores,
        "pct_promotor":    pct_prom,
        "pct_detrator":    pct_det,
        "media_score":     media,
        "total_30d":       len(res_30d),
        "total_90d":       len(res_90d),
        "calculado_em":    _agora(),
    }


def simular_resposta_nps(nps_id: str) -> dict:
    """
    Simula uma resposta de NPS para testes em dry-run.
    Gera score aleatório com distribuição realista e comentário genérico.
    """
    pesos   = [1, 1, 1, 2, 2, 3, 5, 8, 12, 15, 10]  # scores 0-10
    scores  = list(range(11))
    score   = random.choices(scores, weights=pesos, k=1)[0]

    comentarios = {
        "promotor":  ["Excelente servico!", "Muito satisfeito com o resultado", "Superou expectativas"],
        "neutro":    ["Bom, mas pode melhorar", "Servico ok, prazo um pouco longo", "Razoavel"],
        "detrator":  ["Nao ficou como esperado", "Demora excessiva na entrega", "Comunicacao falhou"],
    }
    tipo = "promotor" if score >= 9 else "neutro" if score >= 7 else "detrator"
    comentario = random.choice(comentarios[tipo])

    log.info(f"  [nps] simulando resposta nps_id={nps_id} score={score} tipo={tipo}")
    return registrar_resposta_nps(nps_id, score, comentario)


# ─── Ações derivadas ──────────────────────────────────────────────────────────

def _derivar_acao_detrator(conta_id: str, nps_id: str,
                            score: int, comentario: str) -> list:
    """Cria ação de playbook pb_feedback_negativo em acoes_customer_success.json."""
    if not conta_id:
        return []
    acoes = _ler(_ARQ_ACOES_CS, [])
    acao  = {
        "id":             f"cs_{uuid.uuid4().hex[:8]}",
        "conta_id":       conta_id,
        "conta_nome":     _nome_conta(conta_id),
        "data":           _hoje(),
        "timestamp":      _agora(),
        "playbook_id":    "pb_feedback_negativo",
        "playbook_nome":  "Feedback negativo recebido",
        "severidade":     "risco",
        "acao_ordem":     1,
        "acao_tipo":      "contato_proativo",
        "acao_canal":     "email",
        "acao_template":  "resposta_feedback_negativo",
        "descricao":      f"Responder ao NPS {nps_id} — score={score}. Comentario: {comentario[:80]}",
        "prazo_dias":     1,
        "status_acao":    "pendente",
        "origem":         "nps_feedback",
        "nps_id":         nps_id,
    }
    acoes.append(acao)
    _salvar(_ARQ_ACOES_CS, acoes)
    return ["registrar_feedback", "ativar_playbook_feedback_negativo"]


def _derivar_acao_promotor(conta_id: str, nps_id: str, score: int) -> list:
    """Cria oportunidade de indicação em oportunidades_expansao.json."""
    if not conta_id:
        return []
    expansoes = _ler(_ARQ_EXPANSAO, [])

    # Dedup: já existe expansao tipo indicacao ativa para esta conta?
    ja_existe = any(
        x.get("conta_id") == conta_id
        and x.get("tipo_oportunidade") == "indicacao"
        and x.get("status") not in ("descartada", "arquivada", "convertida_em_oportunidade")
        for x in expansoes
    )
    if ja_existe:
        return ["promotor_registrado"]

    exp_id = f"exp_{uuid.uuid4().hex[:8]}"
    expansoes.append({
        "id":                exp_id,
        "conta_id":          conta_id,
        "entrega_id":        "",
        "tipo_oportunidade": "indicacao",
        "origem":            "nps_feedback",
        "oferta_sugerida":   "indicacao_de_cliente",
        "motivo":            f"NPS score={score} — promotor identificado. Momento ideal para pedir indicacao.",
        "prioridade":        "media",
        "status":            "sugerida",
        "requer_deliberacao": False,
        "oportunidade_id_gerada": None,
        "nps_id":            nps_id,
        "criado_em":         _agora(),
        "atualizado_em":     _agora(),
    })
    _salvar(_ARQ_EXPANSAO, expansoes)
    return ["registrar_feedback", "expansao_indicacao_sugerida"]


def _atualizar_acompanhamento_nps(conta_id: str, score: int) -> None:
    """Atualiza o acompanhamento mais recente com o score NPS recebido."""
    try:
        acomps = _ler(_ARQ_ACOMPS, [])
        ativos = [
            a for a in acomps
            if a.get("conta_id") == conta_id
            and a.get("status") in ("novo", "em_andamento")
        ]
        if not ativos:
            return
        alvo = max(ativos, key=lambda a: a.get("registrado_em", ""))
        alvo["nps_opcional"] = score
        alvo["satisfacao"]   = "alta" if score >= 9 else "media" if score >= 7 else "baixa"
        alvo["status"]       = "em_andamento"
        alvo["atualizado_em"] = _agora()
        _salvar(_ARQ_ACOMPS, acomps)
    except Exception as exc:
        log.warning(f"  [nps] falha ao atualizar acompanhamento: {exc}")


# ─── Helpers internos ─────────────────────────────────────────────────────────

def _buscar_contato_principal(conta_id: str) -> str:
    """Retorna contato_id do contato ativo de maior confiança para a conta."""
    dados    = _ler(_ARQ_CONTATOS, {"contatos": []})
    contatos = dados.get("contatos", []) if isinstance(dados, dict) else dados
    ativos   = [c for c in contatos
                if c.get("conta_id") == conta_id and c.get("ativo", True)]
    if not ativos:
        return ""
    # Prioridade: confiança alta > media > baixa; canal preferido = email
    _pesos = {"alta": 0, "media": 1, "baixa": 2}
    ativos.sort(key=lambda c: (_pesos.get(c.get("confianca", "media"), 1),
                                0 if c.get("canal_preferido") == "email" else 1))
    return ativos[0].get("contato_id", "")


def _buscar_dados_contato(contato_id: str, conta_id: str) -> dict:
    """Retorna dados do contato. Fallback para dados da conta."""
    dados    = _ler(_ARQ_CONTATOS, {"contatos": []})
    contatos = dados.get("contatos", []) if isinstance(dados, dict) else dados
    if contato_id:
        cont = next((c for c in contatos if c.get("contato_id") == contato_id), None)
        if cont:
            return cont
    # Fallback: primeiro contato ativo da conta
    ativos = [c for c in contatos if c.get("conta_id") == conta_id and c.get("ativo", True)]
    return ativos[0] if ativos else {}


def _nome_conta(conta_id: str) -> str:
    contas = _ler(_ARQ_CONTAS, [])
    conta  = next((c for c in contas if c["id"] == conta_id), {})
    return conta.get("nome_empresa", "")


def _classificar_sentimento_por_score(score: int) -> str:
    """Classificação fallback por score numérico."""
    if score >= 9:
        return "positivo"
    if score >= 7:
        return "neutro"
    if score >= 5:
        return "negativo"
    return "negativo_grave"


def _template_nps_fixo(nome: str, servico: str, gatilho: str) -> str:
    intro = {
        "pos_entrega":  "Concluimos recentemente um trabalho juntos",
        "primeiro_mes": "Completamos um mes de parceria",
        "trimestral":   "Ja faz um tempo que trabalhamos juntos",
    }.get(gatilho, "Trabalhamos juntos recentemente")

    return (
        f"Ola {nome},\n\n"
        f"{intro} ({servico}) e queremos saber sua opiniao.\n\n"
        f"Em uma escala de 0 a 10, qual a probabilidade de voce recomendar "
        f"a Vetor para um amigo ou colega?\n\n"
        f"0 = Jamais recomendaria | 10 = Com certeza recomendaria\n\n"
        f"Responda a este email com o numero ou deixe um comentario.\n\n"
        f"Obrigado,\nEquipe Vetor"
    )


def _registrar_historico(conta_id: str, nps_id: str,
                          evento: str, descricao: str = "") -> None:
    hist = _ler(_ARQ_HISTORICO, [])
    hist.append({
        "id":            f"hnps_{uuid.uuid4().hex[:8]}",
        "conta_id":      conta_id,
        "nps_id":        nps_id,
        "evento":        evento,
        "descricao":     descricao,
        "registrado_em": _agora(),
    })
    _salvar(_ARQ_HISTORICO, hist)
