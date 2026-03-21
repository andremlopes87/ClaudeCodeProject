"""
modulos/comercial/processador_resultados_contato.py — Processador de resultados de contato.

Aplica resultados registrados em resultados_contato.json ao pipeline comercial.

Separação de responsabilidades:
  - Canal real (futuro): apenas escreve em resultados_contato.json
  - Este módulo: lê os resultados e aplica as mudanças corretas no estado comercial
  - agente_comercial: chama este módulo, persiste o estado atualizado

Tipos suportados:
  sem_resposta, respondeu_interesse, respondeu_sem_interesse,
  pediu_proposta, pediu_retorno_futuro, contato_invalido, erro_execucao
"""

import json
from datetime import date, datetime
from pathlib import Path

import config

_ARQ_RESULTADOS  = "resultados_contato.json"
_ESTAGIOS_ENCERRADOS = {"ganho", "perdido"}


# ─── Carga e marcação ────────────────────────────────────────────────────────

def carregar_resultados_pendentes() -> list:
    """Carrega resultados com status_aplicacao='pendente'."""
    todos = _carregar_json(_ARQ_RESULTADOS, padrao=[])
    return [r for r in todos if r.get("status_aplicacao") == "pendente"]


def marcar_resultado_como_aplicado(resultado_id: str) -> None:
    """Marca resultado como aplicado em resultados_contato.json."""
    todos = _carregar_json(_ARQ_RESULTADOS, padrao=[])
    agora = datetime.now().isoformat(timespec="seconds")
    for r in todos:
        if r["id"] == resultado_id:
            r["status_aplicacao"] = "aplicado"
            r["aplicado_em"]      = agora
            break
    _salvar_json(_ARQ_RESULTADOS, todos)


# ─── Aplicação principal ─────────────────────────────────────────────────────

def aplicar_resultado_contato(
    resultado: dict,
    pipeline: list,
    followups: list,
    historico: list,
    log,
) -> dict:
    """
    Aplica um resultado de contato no pipeline, followups e historico (in-place).
    Retorna dict com ações tomadas: {opp_atualizada, fu_atualizado, novo_fu}.

    Nunca inventa resposta de cliente.
    Nunca afirma que houve contato real — apenas reflete o que foi registrado.
    """
    tipo        = resultado.get("tipo_resultado", "")
    opp_id      = resultado.get("oportunidade_id", "")
    followup_id = resultado.get("followup_id", "")
    agora       = datetime.now().isoformat(timespec="seconds")

    opp = next((o for o in pipeline if o["id"] == opp_id), None)
    fu  = next((f for f in followups if f["id"] == followup_id), None)

    acoes = {"opp_atualizada": False, "fu_atualizado": False, "novo_fu": None}

    if opp is None:
        log.warning(f"    opp nao encontrada: {opp_id} — resultado ignorado")
        return acoes

    if opp.get("estagio") in _ESTAGIOS_ENCERRADOS:
        log.info(f"    opp ja encerrada (estagio={opp['estagio']}) — resultado ignorado")
        return acoes

    # Marco temporal: primeira interação real registrada
    opp["ultima_interacao_real_em"] = resultado.get("data_resultado", agora)
    opp["ultima_resposta_tipo"]     = tipo
    opp["ultima_atividade"]         = date.today().isoformat()
    opp["atualizado_em"]            = agora

    if tipo == "sem_resposta":
        _aplicar_sem_resposta(resultado, opp, fu, followups, acoes, log)

    elif tipo == "respondeu_interesse":
        _aplicar_respondeu_interesse(resultado, opp, fu, followups, acoes, log)

    elif tipo == "respondeu_sem_interesse":
        _aplicar_respondeu_sem_interesse(resultado, opp, fu, acoes)

    elif tipo == "pediu_proposta":
        _aplicar_pediu_proposta(resultado, opp, fu, acoes)

    elif tipo == "pediu_retorno_futuro":
        _aplicar_pediu_retorno_futuro(resultado, opp, fu, followups, acoes, log)

    elif tipo == "contato_invalido":
        _aplicar_contato_invalido(resultado, opp, fu, acoes)

    elif tipo == "erro_execucao":
        # Sem mudança no pipeline — apenas log e historico
        log.info(f"    erro_execucao registrado | opp mantida inalterada")

    else:
        log.warning(f"    tipo_resultado desconhecido: '{tipo}' — sem aplicacao")
        return acoes

    # Registrar no histórico de abordagens
    ev = registrar_historico_resultado(resultado, opp)
    historico.append(ev)

    acoes["opp_atualizada"] = True
    acoes["fu_atualizado"]  = fu is not None
    return acoes


# ─── Handlers por tipo ───────────────────────────────────────────────────────

def _aplicar_sem_resposta(resultado, opp, fu, followups, acoes, log) -> None:
    opp["tentativas_contato"]  = opp.get("tentativas_contato", 0) + 1
    opp["status_operacional"]  = "sem_resposta"

    atualizar_followup_por_resultado(fu, "executado")

    if opp["tentativas_contato"] < config.COMERCIAL_TENTATIVAS_MAXIMAS:
        novo = criar_novo_followup_se_necessario(resultado, opp, followups, "sem_resposta")
        acoes["novo_fu"] = novo
        log.info(f"    sem_resposta | tentativa {opp['tentativas_contato']} — novo follow-up criado")
    else:
        log.info(
            f"    sem_resposta | tentativas_esgotadas ({opp['tentativas_contato']}) — "
            f"opp ficara em revisao"
        )


def _aplicar_respondeu_interesse(resultado, opp, fu, followups, acoes, log) -> None:
    opp["estagio"]            = "qualificando"
    opp["status_operacional"] = "em_andamento"

    atualizar_followup_por_resultado(fu, "executado")

    novo = criar_novo_followup_se_necessario(resultado, opp, followups, "respondeu_interesse")
    acoes["novo_fu"] = novo
    log.info(f"    respondeu_interesse | estagio -> qualificando | novo follow-up criado")


def _aplicar_respondeu_sem_interesse(resultado, opp, fu, acoes) -> None:
    opp["estagio"]            = "perdido"
    opp["status_operacional"] = "encerrado"
    opp["motivo_perda"]       = resultado.get("resumo_resultado", "sem_interesse declarado pelo contato")

    atualizar_followup_por_resultado(fu, "cancelado")


def _aplicar_pediu_proposta(resultado, opp, fu, acoes) -> None:
    opp["estagio"]            = "aguardando_proposta"
    opp["status_operacional"] = "aguardando_proposta"

    atualizar_followup_por_resultado(fu, "executado")
    # Escalamento por valor fica para detectar_casos_para_escalamento na próxima rodada


def _aplicar_pediu_retorno_futuro(resultado, opp, fu, followups, acoes, log) -> None:
    opp["status_operacional"] = "aguardando_retorno"

    atualizar_followup_por_resultado(fu, "executado")

    novo = criar_novo_followup_se_necessario(resultado, opp, followups, "pediu_retorno_futuro")
    acoes["novo_fu"] = novo
    log.info(f"    pediu_retorno_futuro | novo follow-up com prazo futuro criado")


def _aplicar_contato_invalido(resultado, opp, fu, acoes) -> None:
    opp["status_operacional"] = "bloqueado"
    agora = datetime.now().isoformat(timespec="seconds")
    bloqueios = opp.get("bloqueios", [])
    bloqueios.append({
        "motivo":       "contato_invalido",
        "detalhe":      resultado.get("resumo_resultado", ""),
        "registrado_em": agora,
    })
    opp["bloqueios"] = bloqueios

    atualizar_followup_por_resultado(fu, "bloqueado")


# ─── Operações em follow-ups ─────────────────────────────────────────────────

def atualizar_followup_por_resultado(fu, novo_status: str) -> None:
    """Atualiza status do follow-up relacionado (in-place). Aceita None silenciosamente."""
    if fu is None:
        return
    agora = datetime.now().isoformat(timespec="seconds")
    fu["status"]        = novo_status
    fu["atualizado_em"] = agora


def criar_novo_followup_se_necessario(
    resultado: dict,
    opp: dict,
    followups: list,
    tipo: str,
) -> dict:
    """
    Cria um novo follow-up de continuidade baseado no resultado.
    Retorna o dict do follow-up criado (não persiste — quem chama persiste).
    """
    agora  = datetime.now().isoformat(timespec="seconds")
    opp_id = opp["id"]
    seq    = _proxima_seq_followup(opp_id, followups)
    fu_id  = f"fu_{opp_id}_{seq}"

    proxima_acao = resultado.get("proxima_acao_sugerida", "") or _acao_padrao_por_tipo(tipo, opp)

    tipo_acao_mapa = {
        "sem_resposta":        "retentativa_contato",
        "respondeu_interesse": "qualificacao",
        "pediu_retorno_futuro": "retorno_agendado",
    }
    tipo_acao = tipo_acao_mapa.get(tipo, "continuidade")

    return {
        "id":              fu_id,
        "oportunidade_id": opp_id,
        "contraparte":     opp.get("contraparte", ""),
        "canal":           opp.get("canal_sugerido", resultado.get("canal", "")),
        "tipo_acao":       tipo_acao,
        "descricao":       proxima_acao,
        "prazo_sugerido":  None,
        "status":          "pendente_execucao",
        "agente_origem":   "agente_comercial",
        "agente_destino":  "agente_executor_contato",
        "depende_de":      resultado.get("followup_id"),
        "registrado_em":   agora,
        "atualizado_em":   agora,
    }


# ─── Histórico ───────────────────────────────────────────────────────────────

def registrar_historico_resultado(resultado: dict, opp: dict) -> dict:
    """Cria evento de historico_abordagens para o resultado aplicado."""
    ts      = datetime.now().isoformat(timespec="seconds")
    ts_id   = datetime.now().strftime("%Y%m%d%H%M%S")
    opp_id  = opp["id"]
    tipo    = resultado.get("tipo_resultado", "?")
    resumo  = resultado.get("resumo_resultado", "")
    return {
        "id":                f"ev_{opp_id}_{ts_id}",
        "oportunidade_id":   opp_id,
        "contraparte":       opp.get("contraparte", ""),
        "tipo_evento":       f"resultado_contato_{tipo}",
        "descricao":         (
            f"Resultado registrado: {tipo} | {resumo[:100]} | "
            f"execucao_id={resultado.get('execucao_id','?')}"
        ),
        "origem":            resultado.get("origem", "canal_externo"),
        "agente_responsavel": "agente_comercial",
        "registrado_em":     ts,
    }


# ─── Internos ─────────────────────────────────────────────────────────────────

def _proxima_seq_followup(opp_id: str, followups: list) -> int:
    existentes = [f for f in followups if f.get("oportunidade_id") == opp_id]
    return len(existentes) + 1


def _acao_padrao_por_tipo(tipo: str, opp: dict) -> str:
    contato = opp.get("contato_principal", "?")
    canal   = opp.get("canal_sugerido", "telefone")
    mapa = {
        "sem_resposta":        f"Nova tentativa de contato via {canal} para {contato}",
        "respondeu_interesse": f"Dar continuidade a conversa — qualificar necessidade e apresentar servicos",
        "pediu_retorno_futuro": f"Retornar contato via {canal} para {contato} conforme combinado",
    }
    return mapa.get(tipo, f"Dar continuidade ao contato com {opp.get('contraparte','?')}")


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
