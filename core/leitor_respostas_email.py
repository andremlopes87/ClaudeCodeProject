"""
core/leitor_respostas_email.py — Lê, classifica e processa respostas de email.

Fecha o loop: email enviado → resposta recebida → classificação → ação automática.

Modos de operação:
  simulado  — gera respostas fictícias realistas para testar o fluxo completo
  assistido — lê dados/respostas_email_manual.json (preenchido via painel ou manual)
  real      — conecta via IMAP e lê respostas reais (futuro)

Configuração em dados/config_leitor_respostas.json.
Respostas processadas em dados/respostas_email.json.
Ações executadas em dados/acoes_respostas.json.

Funções públicas:
  processar_respostas()                   → dict  (resumo do ciclo)
  classificar_resposta(texto, contexto)   → dict  (classificacao + confianca + acoes)
  executar_acoes(resposta)                → list  (acoes executadas)
  simular_lote(n)                         → dict  (N respostas geradas)
  executar()                              → dict  (compatível com orquestrador)
"""

from __future__ import annotations

import json
import logging
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import config

log = logging.getLogger(__name__)

# ─── Caminhos ─────────────────────────────────────────────────────────────────

_ARQ_FILA_EMAIL      = "fila_envio_email.json"
_ARQ_RESPOSTAS       = "respostas_email.json"
_ARQ_ACOES           = "acoes_respostas.json"
_ARQ_MANUAL          = "respostas_email_manual.json"
_ARQ_CONFIG          = "config_leitor_respostas.json"
_ARQ_PIPELINE        = "pipeline_comercial.json"
_ARQ_FOLLOWUPS       = "fila_followups.json"
_ARQ_DELIBERACOES    = "deliberacoes_conselho.json"
_ARQ_RECEBER         = "contas_a_receber.json"


# ─── Probabilidades de resposta por tipo de email ─────────────────────────────

_PROB_RESPOSTA: dict[str, float] = {
    "abordagem_inicial":     0.15,
    "followup_sem_resposta": 0.10,
    "proposta_comercial":    0.60,
    "documento_oficial":     0.60,
    "envio_proposta":        0.60,
    "nps_pesquisa":          0.30,
    "cobranca_gentil":       0.50,
    "boas_vindas_cliente":   0.40,
}
_PROB_RESPOSTA_PADRAO = 0.15


# ─── Distribuição de classificações por tipo ──────────────────────────────────

_DIST_CLASSIFICACAO: dict[str, list[tuple[str, float]]] = {
    "abordagem_inicial": [
        ("interessado",  0.40),
        ("nao_agora",    0.30),
        ("recusa",       0.20),
        ("pedido_info",  0.10),
    ],
    "followup_sem_resposta": [
        ("interessado",  0.30),
        ("nao_agora",    0.35),
        ("recusa",       0.25),
        ("pedido_info",  0.10),
    ],
    "proposta_comercial": [
        ("aceite",         0.50),
        ("duvida",         0.20),
        ("negocia_valor",  0.20),
        ("recusa",         0.10),
    ],
    "documento_oficial": [
        ("aceite",         0.50),
        ("duvida",         0.20),
        ("negocia_valor",  0.20),
        ("recusa",         0.10),
    ],
    "envio_proposta": [
        ("aceite",         0.50),
        ("duvida",         0.20),
        ("negocia_valor",  0.20),
        ("recusa",         0.10),
    ],
    "nps_pesquisa": [
        ("nps_alta",  0.50),
        ("nps_media", 0.30),
        ("nps_baixa", 0.20),
    ],
    "cobranca_gentil": [
        ("confirma_pagamento", 0.60),
        ("pede_prazo",         0.30),
        ("fora_contexto",      0.10),
    ],
    "boas_vindas_cliente": [
        ("fora_contexto", 0.60),
        ("pedido_info",   0.25),
        ("interessado",   0.15),
    ],
}
_DIST_PADRAO = [
    ("interessado", 0.30),
    ("nao_agora",   0.30),
    ("recusa",      0.25),
    ("pedido_info", 0.15),
]


# ─── Textos simulados por classificação ───────────────────────────────────────

_TEXTOS_SIMULADOS: dict[str, list[str]] = {
    "interessado":         [
        "Opa, quanto tempo demora pra ficar pronto?",
        "Achei interessante! Como funciona exatamente?",
        "Pode me contar mais detalhes sobre isso?",
        "Faz sentido sim. Quando podemos conversar?",
    ],
    "nao_agora":           [
        "No momento não temos budget disponível, mas pode entrar em contato no próximo trimestre.",
        "Obrigado! O momento não é o melhor agora, mas guardo o contato.",
        "Talvez mais pra frente. Obrigado.",
    ],
    "recusa":              [
        "Obrigado mas no momento não tenho interesse.",
        "Já temos uma solução para isso, obrigado.",
        "Não é o que estou buscando no momento. Obrigado.",
    ],
    "pedido_info":         [
        "Quanto custa exatamente? Tem algum material que posso ver?",
        "Pode me explicar melhor como funciona na prática?",
        "Qual a diferença entre os pacotes disponíveis?",
    ],
    "aceite":              [
        "Pode fechar! Como faço para assinar o contrato?",
        "Gostei da proposta, de acordo. Pode prosseguir.",
        "Fechado! Quando podemos começar?",
    ],
    "duvida":              [
        "Não entendi bem o prazo. Pode explicar melhor?",
        "Como funciona a parte de suporte depois da entrega?",
        "O que está incluído exatamente no pacote?",
    ],
    "negocia_valor":       [
        "O valor está um pouco acima do que estava pensando. Tem como reduzir?",
        "Tem desconto pra pagamento à vista?",
        "Posso pagar em mais parcelas? O valor mensal ficaria mais viável.",
    ],
    "confirma_pagamento":  [
        "Já realizei a transferência esta manhã. Obrigado!",
        "Paguei hoje. O comprovante segue em anexo.",
        "Feito! Pagamento realizado.",
    ],
    "pede_prazo":          [
        "Posso pagar semana que vem? Estou com o fluxo apertado agora.",
        "Você poderia me dar mais 15 dias?",
        "Posso quitar até o final do mês?",
    ],
    "nps_alta":            [
        "Nota 9. O serviço superou as expectativas!",
        "Nota 10! Muito satisfeito com o resultado.",
        "9 de 10. Recomendo para outros negócios.",
    ],
    "nps_media":           [
        "Nota 7. Bom, mas poderia ter sido mais rápido.",
        "7. O resultado foi bom, só achei que poderia ter mais suporte durante.",
        "Nota 8. Gostei no geral.",
    ],
    "nps_baixa":           [
        "Nota 5. O resultado não foi bem o que esperava.",
        "4. Demorou mais do que o combinado.",
        "Nota 6. Cumpriu o básico mas esperava mais.",
    ],
    "fora_contexto":       [
        "Ok, obrigado.",
        "Certo.",
        "Tá bom.",
    ],
    "spam":                [],
}


# ─── Ações derivadas por classificação ───────────────────────────────────────

_ACOES_POR_CLASSIFICACAO: dict[str, list[str]] = {
    "interessado":         ["mover_pipeline_negociacao", "gerar_followup_resposta"],
    "nao_agora":           ["mover_pipeline_esfriar", "agendar_recontato_30d"],
    "recusa":              ["mover_pipeline_perdido", "registrar_motivo"],
    "pedido_info":         ["gerar_followup_com_info", "manter_pipeline"],
    "aceite":              ["mover_pipeline_ganho", "gerar_contrato"],
    "duvida":              ["gerar_followup_esclarecimento"],
    "negocia_valor":       ["escalar_conselho_se_desconto_alto", "gerar_followup_negociacao"],
    "confirma_pagamento":  ["marcar_parcela_paga", "atualizar_financeiro"],
    "pede_prazo":          ["registrar_novo_prazo", "atualizar_financeiro"],
    "nps_alta":            ["registrar_nps"],
    "nps_media":           ["registrar_nps"],
    "nps_baixa":           ["registrar_nps", "escalar_conselho_nps_baixo"],
    "spam":                [],
    "fora_contexto":       [],
}

# Mapeamento: classificação NPS → nota aproximada (para registrar_nps)
_NPS_NOTA: dict[str, int] = {
    "nps_alta":  9,
    "nps_media": 7,
    "nps_baixa": 5,
}

# Palavras-chave para fallback de classificação
_PALAVRAS_CHAVE: dict[str, list[str]] = {
    "interessado":         ["interesse", "quero", "como funciona", "quando pode", "adorei", "gostei", "gostaria"],
    "nao_agora":           ["depois", "futuramente", "momento não", "agora não", "mais tarde", "próximo trimestre"],
    "recusa":              ["não tenho interesse", "não preciso", "obrigado mas não", "não quero", "dispenso"],
    "pedido_info":         ["quanto custa", "qual o valor", "como funciona", "mais informações", "qual a diferença"],
    "aceite":              ["aceito", "pode ser", "fechado", "feito", "vamos", "de acordo", "pode prosseguir"],
    "duvida":              ["dúvida", "pergunta", "não entendi", "pode explicar", "como assim"],
    "negocia_valor":       ["caro", "muito alto", "desconto", "reduzir", "negociar", "mais parcelas", "à vista"],
    "confirma_pagamento":  ["paguei", "já paguei", "transferência feita", "pagamento realizado", "comprovante"],
    "pede_prazo":          ["prazo", "mais tempo", "estender", "semana que vem", "final do mês", "mais 15 dias"],
}


# ─── I/O ──────────────────────────────────────────────────────────────────────

def _ler(arq: str, padrao=None):
    if padrao is None:
        padrao = []
    p = config.PASTA_DADOS / arq
    if not p.exists():
        return padrao
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return padrao


def _salvar(arq: str, dados) -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    (config.PASTA_DADOS / arq).write_text(
        json.dumps(dados, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _detectar_modo() -> str:
    try:
        return _ler(_ARQ_CONFIG, {}).get("modo", "simulado")
    except Exception:
        return "simulado"


# ─── Classificação de respostas ───────────────────────────────────────────────

def classificar_resposta(texto: str, contexto: dict = None) -> dict:
    """
    Classifica o texto de uma resposta de email.

    Tenta LLM (router.classificar) com o texto + contexto do email original.
    Fallback: palavras-chave.
    Classificação ambígua → "fora_contexto" (seguro, não toma ação errada).

    Retorna:
      {classificacao, confianca, acoes_derivadas, classificado_por}
    """
    if contexto is None:
        contexto = {}

    # ── Tentativa via LLM ────────────────────────────────────────────────────
    try:
        from core.llm_router import LLMRouter
        router = LLMRouter()
        res = router.classificar({
            "agente": "leitor_respostas_email",
            "tarefa": "classificar_resposta_email",
            "dados": {
                "texto_resposta":  texto[:500],
                "tipo_email":      contexto.get("tipo_envio", ""),
                "assunto_original": contexto.get("assunto", ""),
                "contraparte":     contexto.get("contraparte", ""),
                "classificacoes_validas": list(_ACOES_POR_CLASSIFICACAO.keys()),
            },
        })

        if res.get("sucesso") and not res.get("fallback_usado"):
            resultado = res.get("resultado", {})
            if isinstance(resultado, str):
                try:
                    resultado = json.loads(resultado)
                except Exception:
                    resultado = {}
            classif = resultado.get("classificacao", "")
            if classif in _ACOES_POR_CLASSIFICACAO:
                return {
                    "classificacao":    classif,
                    "confianca":        "alta",
                    "acoes_derivadas":  _ACOES_POR_CLASSIFICACAO.get(classif, []),
                    "classificado_por": "llm",
                }
    except Exception as exc:
        log.debug(f"[leitor] LLM falhou na classificação: {exc}")

    # ── Fallback: palavras-chave ──────────────────────────────────────────────
    texto_lower = texto.lower()
    for classif, palavras in _PALAVRAS_CHAVE.items():
        if any(p in texto_lower for p in palavras):
            return {
                "classificacao":    classif,
                "confianca":        "media",
                "acoes_derivadas":  _ACOES_POR_CLASSIFICACAO.get(classif, []),
                "classificado_por": "regra",
            }

    return {
        "classificacao":    "fora_contexto",
        "confianca":        "baixa",
        "acoes_derivadas":  [],
        "classificado_por": "regra",
    }


# ─── Executor de ações ────────────────────────────────────────────────────────

def executar_acoes(resposta: dict) -> list:
    """
    Executa as ações derivadas de uma resposta classificada.

    Ações suportadas:
      mover_pipeline_*  → atualiza estagio no pipeline_comercial.json
      gerar_followup_*  → cria follow-up na fila_followups.json
      gerar_contrato    → cria contrato via core/contratos_empresa.py (best-effort)
      marcar_parcela_paga / atualizar_financeiro → atualiza contas_a_receber.json
      escalar_conselho_* → cria deliberação
      registrar_*       → registra sem ação estrutural
      agendar_recontato_* → cria follow-up agendado

    Retorna lista de ações executadas com status.
    """
    classif  = resposta.get("classificacao", "fora_contexto")
    acoes    = resposta.get("acoes_derivadas", _ACOES_POR_CLASSIFICACAO.get(classif, []))
    opp_id   = resposta.get("oportunidade_id", "")
    conta_id = resposta.get("conta_id", "")
    empresa  = resposta.get("contraparte", "")
    modo     = resposta.get("modo", "simulado")

    executadas = []

    for acao in acoes:
        try:
            resultado_acao = _executar_acao_individual(
                acao, resposta, opp_id, conta_id, empresa, modo,
            )
            executadas.append({"acao": acao, "status": "ok", **resultado_acao})
        except Exception as exc:
            log.warning(f"[leitor] ação {acao!r} falhou: {exc}")
            executadas.append({"acao": acao, "status": "erro", "erro": str(exc)})

    # Atualizar memória da conta
    if conta_id or opp_id:
        _atualizar_memoria(resposta, executadas)

    return executadas


def _executar_acao_individual(
    acao: str,
    resposta: dict,
    opp_id: str,
    conta_id: str,
    empresa: str,
    modo: str,
) -> dict:
    agora = _agora()

    # ── Movimentação de pipeline ──────────────────────────────────────────────
    if acao.startswith("mover_pipeline_"):
        destino_map = {
            "mover_pipeline_negociacao": "negociacao",
            "mover_pipeline_esfriar":    "em_pausa",
            "mover_pipeline_perdido":    "perdida",
            "mover_pipeline_ganho":      "ganho",
        }
        novo_estagio = destino_map.get(acao, "qualificando")
        if opp_id:
            _mover_pipeline(opp_id, novo_estagio, resposta, agora)
        return {"estagio_novo": novo_estagio, "opp_id": opp_id}

    # ── Geração de follow-ups ─────────────────────────────────────────────────
    if acao.startswith("gerar_followup") or acao.startswith("agendar_recontato"):
        fu_id = _criar_followup(acao, resposta, opp_id, empresa, agora)
        return {"followup_id": fu_id}

    # ── Gerar contrato ────────────────────────────────────────────────────────
    if acao == "gerar_contrato":
        contrato_id = _tentar_gerar_contrato(resposta, opp_id, agora)
        return {"contrato_id": contrato_id}

    # ── Financeiro ────────────────────────────────────────────────────────────
    if acao in ("marcar_parcela_paga", "atualizar_financeiro", "registrar_novo_prazo"):
        _atualizar_financeiro(acao, resposta, agora)
        return {}

    # ── Escalar para conselho ─────────────────────────────────────────────────
    if acao.startswith("escalar_conselho"):
        delib_id = _criar_deliberacao(acao, resposta, empresa, agora)
        return {"deliberacao_id": delib_id}

    # ── Registrar NPS ─────────────────────────────────────────────────────────
    if acao == "registrar_nps":
        _registrar_nps(resposta, conta_id, agora)
        return {}

    # ── Ações de registro / manutenção ────────────────────────────────────────
    return {}  # registrar_motivo, manter_pipeline, etc. — apenas log


def _mover_pipeline(opp_id: str, novo_estagio: str, resposta: dict, agora: str) -> None:
    pipeline = _ler(_ARQ_PIPELINE, [])
    for opp in pipeline:
        if opp.get("id") == opp_id:
            opp["estagio_anterior"]  = opp.get("estagio", "")
            opp["estagio"]           = novo_estagio
            opp["ultima_atividade"]  = agora[:10]
            opp["atualizado_em"]     = agora
            opp["ultima_resposta_tipo"] = resposta.get("classificacao", "")
            if novo_estagio == "perdida":
                opp["motivo_perda"] = f"resposta: {resposta.get('classificacao','')}"
            break
    _salvar(_ARQ_PIPELINE, pipeline)
    log.info(f"[leitor] pipeline {opp_id} → {novo_estagio}")


def _criar_followup(acao: str, resposta: dict, opp_id: str, empresa: str, agora: str) -> str:
    followups = _ler(_ARQ_FOLLOWUPS, [])
    fu_id = f"fu_resp_{uuid.uuid4().hex[:8]}"

    prazo_sugerido = None
    if "30d" in acao:
        prazo_sugerido = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    elif "recontato" in acao:
        prazo_sugerido = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    descricao_map = {
        "gerar_followup_resposta":        f"Responder ao interesse de {empresa} — continuar conversa",
        "gerar_followup_com_info":        f"Enviar informações adicionais para {empresa} conforme pedido",
        "gerar_followup_esclarecimento":  f"Esclarecer dúvida levantada por {empresa}",
        "gerar_followup_negociacao":      f"Retornar negociação de valor com {empresa}",
        "agendar_recontato_30d":          f"Recontatar {empresa} em 30 dias (interesse futuro)",
    }
    descricao = descricao_map.get(acao, f"Follow-up para {empresa} após resposta ao email")

    followups.append({
        "id":               fu_id,
        "oportunidade_id":  opp_id,
        "contraparte":      empresa,
        "canal":            "email",
        "tipo_acao":        acao,
        "descricao":        descricao,
        "prazo_sugerido":   prazo_sugerido,
        "status":           "pendente",
        "agente_origem":    "leitor_respostas_email",
        "agente_destino":   "agente_executor_contato",
        "depende_de":       None,
        "resposta_id":      resposta.get("resposta_id", ""),
        "registrado_em":    agora,
        "atualizado_em":    agora,
    })
    _salvar(_ARQ_FOLLOWUPS, followups)
    return fu_id


def _tentar_gerar_contrato(resposta: dict, opp_id: str, agora: str) -> str:
    try:
        from core.contratos_empresa import gerar_contrato_para_opp
        resultado = gerar_contrato_para_opp(opp_id)
        return resultado.get("contrato_id", "")
    except Exception:
        pass
    # Fallback: só registrar na deliberação para o conselho aprovar
    return _criar_deliberacao(
        "gerar_contrato",
        resposta,
        resposta.get("contraparte", ""),
        agora,
    )


def _atualizar_financeiro(acao: str, resposta: dict, agora: str) -> None:
    receber = _ler(_ARQ_RECEBER, [])
    opp_id  = resposta.get("oportunidade_id", "")
    empresa = resposta.get("contraparte", "")
    if not receber:
        return
    for r in receber:
        if r.get("oportunidade_id") == opp_id or r.get("empresa") == empresa:
            if acao == "marcar_parcela_paga":
                if r.get("status") not in ("pago", "confirmado"):
                    r["status"]        = "pago_confirmado_resposta"
                    r["atualizado_em"] = agora
                    r["nota"]          = f"Confirmado via resposta email {agora[:10]}"
            elif acao == "registrar_novo_prazo":
                novo_prazo = (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d")
                r["novo_vencimento"]  = novo_prazo
                r["atualizado_em"]    = agora
                r["nota"]             = f"Prazo estendido via resposta email {agora[:10]}"
    _salvar(_ARQ_RECEBER, receber)


def _criar_deliberacao(acao: str, resposta: dict, empresa: str, agora: str) -> str:
    deliberacoes = _ler(_ARQ_DELIBERACOES, [])
    delib_id     = f"delib_resp_{uuid.uuid4().hex[:8]}"

    titulo_map = {
        "escalar_conselho_se_desconto_alto": f"Solicitação de desconto — {empresa}",
        "escalar_conselho_nps_baixo":        f"NPS baixo recebido — {empresa}",
        "gerar_contrato":                    f"Aceite recebido — aprovar geração de contrato para {empresa}",
    }

    deliberacoes.append({
        "id":             delib_id,
        "tipo":           "decisao_necessaria",
        "area":           "comercial",
        "titulo":         titulo_map.get(acao, f"Ação requerida: {acao} — {empresa}"),
        "descricao":      (
            f"Resposta de email classificada como '{resposta.get('classificacao','')}' "
            f"para {empresa}. Ação '{acao}' requer aprovação do conselho."
        ),
        "urgencia":       "media",
        "status":         "pendente",
        "dados":          {"resposta_id": resposta.get("resposta_id", ""), "opp_id": resposta.get("oportunidade_id", "")},
        "criado_por":     "leitor_respostas_email",
        "criado_em":      agora,
        "atualizado_em":  agora,
    })
    _salvar(_ARQ_DELIBERACOES, deliberacoes)
    return delib_id


def _registrar_nps(resposta: dict, conta_id: str, agora: str) -> None:
    if not conta_id:
        return
    nota = _NPS_NOTA.get(resposta.get("classificacao", "nps_media"), 7)
    try:
        from core.nps_feedback import registrar_resposta_nps
        nps_id = resposta.get("nps_id", "")
        if nps_id:
            registrar_resposta_nps(nps_id, nota, resposta.get("texto_resposta", ""))
    except Exception as exc:
        log.debug(f"[leitor] registrar_nps falhou: {exc}")


def _atualizar_memoria(resposta: dict, acoes_executadas: list) -> None:
    conta_id = resposta.get("conta_id", "") or resposta.get("oportunidade_id", "")
    if not conta_id:
        return
    try:
        from core.llm_memoria import atualizar_memoria_conta
        resumo_acoes = ", ".join(a["acao"] for a in acoes_executadas if a.get("status") == "ok")
        atualizar_memoria_conta(conta_id, {
            "contexto_comercial": (
                f"Resposta ao email: {resposta.get('classificacao','')} | "
                f"{resposta.get('data_resposta','')[:10]} | ações: {resumo_acoes or 'nenhuma'}"
            ),
        })
    except Exception:
        pass


# ─── Simulador de respostas ───────────────────────────────────────────────────

def _escolher_classificacao(tipo_email: str) -> str:
    distribuicao = _DIST_CLASSIFICACAO.get(tipo_email, _DIST_PADRAO)
    r = random.random()
    acumulado = 0.0
    for classif, prob in distribuicao:
        acumulado += prob
        if r <= acumulado:
            return classif
    return distribuicao[-1][0]


def _gerar_texto_simulado(classif: str, email: dict) -> str:
    opcoes = _TEXTOS_SIMULADOS.get(classif, ["Ok, obrigado."])
    return random.choice(opcoes) if opcoes else "Ok."


def _simular_resposta_para_email(email: dict) -> Optional[dict]:
    """
    Decide (probabilisticamente) se um email recebe resposta e, em caso positivo,
    gera uma resposta simulada realista.
    Retorna None se não há resposta.
    """
    tipo = email.get("tipo_envio", email.get("abordagem_tipo", ""))
    prob = _PROB_RESPOSTA.get(tipo, _PROB_RESPOSTA_PADRAO)

    if random.random() > prob:
        return None

    classif = _escolher_classificacao(tipo)
    texto   = _gerar_texto_simulado(classif, email)

    # Gerar texto mais realista via LLM (best-effort)
    try:
        from core.llm_router import LLMRouter
        router = LLMRouter()
        res = router.redigir({
            "agente": "leitor_respostas_email",
            "tarefa": "simular_resposta_cliente",
            "dados":  {
                "tipo_email":     tipo,
                "classificacao":  classif,
                "empresa":        email.get("contraparte", ""),
                "assunto":        email.get("assunto", ""),
            },
        })
        if res.get("sucesso") and not res.get("fallback_usado"):
            resultado = res.get("resultado", "")
            if isinstance(resultado, dict):
                resultado = resultado.get("texto", "")
            if isinstance(resultado, str) and len(resultado) > 5:
                texto = resultado
    except Exception:
        pass

    resposta_id  = f"resp_{uuid.uuid4().hex[:8]}"
    data_resposta = (
        datetime.now() - timedelta(hours=random.randint(1, 48))
    ).isoformat(timespec="seconds")

    result = {
        "resposta_id":              resposta_id,
        "email_origem_id":          email.get("id", ""),
        "oportunidade_id":          email.get("oportunidade_id", ""),
        "conta_id":                 email.get("conta_id", ""),
        "contato_id":               email.get("contato_id", ""),
        "contraparte":              email.get("contraparte", ""),
        "email_destino":            email.get("email_destino", ""),
        "tipo_email_original":      tipo,
        "data_resposta":            data_resposta,
        "texto_resposta":           texto,
        "classificacao":            classif,
        "confianca_classificacao":  "simulada",
        "classificado_por":         "simulador",
        "acoes_derivadas":          _ACOES_POR_CLASSIFICACAO.get(classif, []),
        "processado":               False,
        "modo":                     "simulado",
        "criado_em":                _agora(),
    }

    # Enriquecer com classificação LLM/regra
    classif_result = classificar_resposta(texto, email)
    result["classificacao"]           = classif_result["classificacao"]
    result["confianca_classificacao"] = classif_result["confianca"]
    result["classificado_por"]        = classif_result["classificado_por"]
    result["acoes_derivadas"]         = classif_result["acoes_derivadas"]

    return result


# ─── Funções públicas ─────────────────────────────────────────────────────────

def processar_respostas() -> dict:
    """
    Ciclo completo: ler → classificar → executar ações.

    Modo simulado:  gera respostas fictícias para emails "preparado"/"enviado"
    Modo assistido: lê respostas_email_manual.json
    Modo real:      IMAP (não implementado, retorna resumo vazio)

    Retorna:
      {respostas_processadas, por_classificacao, acoes_geradas, modo}
    """
    modo = _detectar_modo()
    log.info(f"[leitor] processar_respostas | modo={modo}")

    respostas_novas: list[dict] = []

    if modo == "simulado":
        respostas_novas = _simular_respostas_em_lote()

    elif modo == "assistido":
        manuais = _ler(_ARQ_MANUAL, [])
        for resp in manuais:
            if not resp.get("processado"):
                if "classificacao" not in resp:
                    c = classificar_resposta(resp.get("texto_resposta", ""), resp)
                    resp.update(c)
                resp["modo"] = "assistido"
                respostas_novas.append(resp)

    else:  # real
        log.info("[leitor] modo real: IMAP não implementado — nada a processar")
        return {"respostas_processadas": 0, "por_classificacao": {}, "acoes_geradas": 0, "modo": modo}

    # Persistir respostas novas
    existentes  = _ler(_ARQ_RESPOSTAS, [])
    ids_existentes = {r["resposta_id"] for r in existentes}

    acoes_log   = _ler(_ARQ_ACOES, [])
    total_acoes = 0

    por_classificacao: dict[str, int] = {}

    for resp in respostas_novas:
        if resp["resposta_id"] in ids_existentes:
            continue

        # Executar ações
        acoes_exec = executar_acoes(resp)
        resp["acoes_executadas"] = acoes_exec
        resp["processado"]       = True

        existentes.append(resp)
        ids_existentes.add(resp["resposta_id"])

        classif = resp.get("classificacao", "fora_contexto")
        por_classificacao[classif] = por_classificacao.get(classif, 0) + 1
        total_acoes += len([a for a in acoes_exec if a.get("status") == "ok"])

        acoes_log.append({
            "resposta_id":  resp["resposta_id"],
            "opp_id":       resp.get("oportunidade_id", ""),
            "empresa":      resp.get("contraparte", ""),
            "classificacao": classif,
            "acoes":        acoes_exec,
            "registrado_em": _agora(),
        })

    _salvar(_ARQ_RESPOSTAS, existentes)
    _salvar(_ARQ_ACOES, acoes_log)

    resumo = {
        "respostas_processadas": len(respostas_novas),
        "por_classificacao":     por_classificacao,
        "acoes_geradas":         total_acoes,
        "modo":                  modo,
    }
    log.info(
        f"[leitor] ciclo concluído: {resumo['respostas_processadas']} respostas | "
        f"{resumo['acoes_geradas']} ações | {por_classificacao}"
    )
    return resumo


def _simular_respostas_em_lote() -> list[dict]:
    """Gera respostas simuladas para emails elegíveis da fila."""
    fila    = _ler(_ARQ_FILA_EMAIL, [])
    existentes = {r["email_origem_id"] for r in _ler(_ARQ_RESPOSTAS, [])}

    novas = []
    for email in fila:
        eid    = email.get("id", "")
        status = email.get("status", "")
        # Elegível: email preparado/enviado e ainda sem resposta
        if eid in existentes:
            continue
        if status not in ("preparado", "enviado", "enviado_simulado"):
            continue

        resp = _simular_resposta_para_email(email)
        if resp:
            novas.append(resp)

    log.info(f"[leitor] simulados: {len(novas)}/{len(fila)} emails geraram resposta")
    return novas


def simular_lote(n: int = 5) -> dict:
    """
    Gera N respostas simuladas (independente da fila real).
    Útil para popular o sistema e testar o fluxo completo.

    Retorna resumo com respostas geradas e ações executadas.
    """
    log.info(f"[leitor] simular_lote({n})")

    # Tipos de email para simular
    tipos = list(_PROB_RESPOSTA.keys())
    empresas_mock = [
        ("Barbearia Central", "oport_mock_001"),
        ("Clínica Bem Estar", "oport_mock_002"),
        ("Padaria Pão Quente", "oport_mock_003"),
        ("Oficina Silva",     "oport_mock_004"),
        ("Salão Studio Bela", "oport_mock_005"),
    ]

    respostas_geradas = []
    for i in range(n):
        empresa, opp_id = random.choice(empresas_mock)
        tipo            = random.choice(tipos)
        classif         = _escolher_classificacao(tipo)
        texto           = _gerar_texto_simulado(classif, {})

        resp = {
            "resposta_id":             f"resp_mock_{uuid.uuid4().hex[:8]}",
            "email_origem_id":         f"email_mock_{i}",
            "oportunidade_id":         opp_id,
            "conta_id":                "",
            "contato_id":              "",
            "contraparte":             empresa,
            "email_destino":           f"contato@{empresa.lower().replace(' ', '')}.com.br",
            "tipo_email_original":     tipo,
            "data_resposta":           (datetime.now() - timedelta(hours=i * 3)).isoformat(timespec="seconds"),
            "texto_resposta":          texto,
            "classificacao":           classif,
            "confianca_classificacao": "simulada",
            "classificado_por":        "simulador_lote",
            "acoes_derivadas":         _ACOES_POR_CLASSIFICACAO.get(classif, []),
            "processado":              False,
            "modo":                    "simulado",
            "criado_em":               _agora(),
        }
        respostas_geradas.append(resp)

    # Persistir e executar ações
    existentes  = _ler(_ARQ_RESPOSTAS, [])
    acoes_log   = _ler(_ARQ_ACOES, [])
    total_acoes = 0
    por_classif: dict[str, int] = {}

    for resp in respostas_geradas:
        acoes_exec = executar_acoes(resp)
        resp["acoes_executadas"] = acoes_exec
        resp["processado"]       = True
        existentes.append(resp)
        total_acoes += len([a for a in acoes_exec if a.get("status") == "ok"])
        c = resp["classificacao"]
        por_classif[c] = por_classif.get(c, 0) + 1
        acoes_log.append({
            "resposta_id":  resp["resposta_id"],
            "opp_id":       resp.get("oportunidade_id", ""),
            "empresa":      resp.get("contraparte", ""),
            "classificacao": c,
            "acoes":        acoes_exec,
            "registrado_em": _agora(),
        })

    _salvar(_ARQ_RESPOSTAS, existentes)
    _salvar(_ARQ_ACOES, acoes_log)

    return {
        "respostas_geradas": len(respostas_geradas),
        "por_classificacao": por_classif,
        "acoes_geradas":     total_acoes,
        "modo":              "simulado_lote",
    }


def executar() -> dict:
    """
    Ponto de entrada compatível com o orquestrador.
    Chama processar_respostas() e retorna resumo no formato padrão de agente.
    """
    resultado = processar_respostas()
    return {
        "respostas_processadas": resultado.get("respostas_processadas", 0),
        "por_classificacao":     resultado.get("por_classificacao", {}),
        "acoes_geradas":         resultado.get("acoes_geradas", 0),
        "modo":                  resultado.get("modo", "simulado"),
    }
