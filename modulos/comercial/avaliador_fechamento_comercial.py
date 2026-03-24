"""
modulos/comercial/avaliador_fechamento_comercial.py

Avalia sinais de fechamento nas oportunidades do pipeline comercial e
promove conservadoramente para 'ganho' ou 'pronto_para_entrega'.
Nao inventa fatos. Nao usa LLM. Todas as decisoes sao auditaveis.

Fontes permitidas:
  dados/pipeline_comercial.json
  dados/resultados_contato.json
  dados/insumos_entrega.json

Saidas:
  dados/pipeline_comercial.json    (modificado in-place)
  dados/historico_fechamento_comercial.json

Sistema de pontuacao:
  +3  pediu_proposta (resultado)
  +2  escopo_confirmado (insumo aplicado)
  +1  respondeu_interesse (resultado)
  +1  contato_confirmado (insumo aplicado)
  +1  objetivo_confirmado (insumo aplicado)
  +1  contexto_origem presente na oportunidade
  +1  ultimo resultado positivo (pediu_proposta ou respondeu_interesse)

Decisoes:
  GANHO              score >= 8 + linha definida + sem bloqueios criticos
  PRONTO_PARA_ENTREGA score 5-7 + linha definida + sem bloqueios
  ESCALAR            score >= 2 + marketing + pediu_proposta + sem escopo + sem objetivo
  MANTER             demais casos

Bloqueios criticos:
  - sem contato_confirmado e sem respondeu_interesse
  - linha_servico_sugerida vazia ou "indefinida"
  - estagio ja "ganho", "perdido" ou "encerrado"
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import config
from core.politicas_empresa import carregar_politicas

logger = logging.getLogger(__name__)

_TIPOS_RESULTADO_POSITIVO = {"pediu_proposta", "respondeu_interesse"}
_TIPOS_RESULTADO_NEGATIVO = {"sem_resposta", "nao_respondeu", "contato_invalido"}
_ESTAGIOS_FINAIS          = {"ganho", "perdido", "encerrado"}

# Thresholds padrão — sobrescritos pelas políticas operacionais em cada execução
_SCORE_GANHO_PADRAO       = 8
_SCORE_PRONTO_PADRAO      = 5


# ─── Ponto de entrada ─────────────────────────────────────────────────────────

def executar() -> dict:
    # Carregar políticas operacionais
    politicas   = carregar_politicas()
    score_ganho = politicas.get("fechamento_comercial", {}).get("score_ganho", _SCORE_GANHO_PADRAO)
    score_pronto = politicas.get("fechamento_comercial", {}).get("score_pronto", _SCORE_PRONTO_PADRAO)
    exigir_escopo = politicas.get("fechamento_comercial", {}).get("exigir_escopo_para_ganho", False)
    modo_empresa  = politicas.get("modo_empresa", "normal")
    logger.info(
        f"[avaliador] politicas: modo={modo_empresa} "
        f"score_ganho={score_ganho} score_pronto={score_pronto} exigir_escopo={exigir_escopo}"
    )

    pipeline   = _carregar_json("pipeline_comercial.json",              padrao=[])
    resultados = _carregar_json("resultados_contato.json",              padrao=[])
    insumos    = _carregar_json("insumos_entrega.json",                 padrao=[])
    historico  = _carregar_json("historico_fechamento_comercial.json",  padrao=[])

    # Indexar por oportunidade_id
    res_por_opp    = _agrupar_por_opp(resultados, "oportunidade_id")
    ins_por_opp    = _agrupar_por_opp(insumos,    "oportunidade_id")

    ganhos          = 0
    prontos         = 0
    escalados       = 0
    mantidos        = 0
    candidatas      = [o for o in pipeline if o.get("estagio") not in _ESTAGIOS_FINAIS]

    for opp in candidatas:
        opp_id    = opp.get("id", "")
        res_opp   = res_por_opp.get(opp_id, [])
        ins_opp   = ins_por_opp.get(opp_id, [])

        bloqueios = detectar_bloqueios_fechamento(opp, res_opp)
        if bloqueios:
            logger.info(f"  [avaliador] {opp_id} bloqueada: {bloqueios}")
            mantidos += 1
            continue

        score, sinais = avaliar_sinais_de_fechamento(opp, res_opp, ins_opp)
        decisao       = decidir_promocao(opp, score, sinais, ins_opp,
                                         score_ganho=score_ganho,
                                         score_pronto=score_pronto,
                                         exigir_escopo=exigir_escopo)

        logger.info(
            f"  [avaliador] {opp_id} score={score} "
            f"decisao={decisao['acao']} estagio={opp.get('estagio')}"
        )

        if decisao["acao"] == "ganho":
            atualizar_pipeline_para_entrega(opp, "ganho", "aprovado")
            ganhos += 1
        elif decisao["acao"] == "pronto_para_entrega":
            atualizar_pipeline_para_entrega(opp, "pronto_para_entrega", "pronto_para_entrega")
            prontos += 1
        elif decisao["acao"] == "escalar":
            _registrar_escalonamento(opp, score, sinais, decisao)
            escalados += 1
        else:
            mantidos += 1

        registrar_historico_fechamento(opp_id, score, sinais, decisao, historico)

    _salvar_json("pipeline_comercial.json",             pipeline)
    _salvar_json("historico_fechamento_comercial.json", historico)

    logger.info(
        f"[avaliador_fechamento] candidatas={len(candidatas)} "
        f"ganhos={ganhos} prontos={prontos} escalados={escalados} mantidos={mantidos}"
    )

    return {
        "agente":               "avaliador_fechamento_comercial",
        "candidatas_avaliadas": len(candidatas),
        "promovidos_ganho":     ganhos,
        "promovidos_pronto":    prontos,
        "escalados":            escalados,
        "mantidos":             mantidos,
        "modo_empresa":         modo_empresa,
        "score_ganho_usado":    score_ganho,
        "score_pronto_usado":   score_pronto,
    }


# ─── Avaliacao ────────────────────────────────────────────────────────────────

def avaliar_sinais_de_fechamento(opp: dict, resultados_opp: list, insumos_opp: list) -> tuple:
    """
    Calcula score de fechamento e lista de sinais detectados.
    Retorna (score: int, sinais: list[str]).
    """
    score  = 0
    sinais = []

    tipos_res = [r.get("tipo_resultado", "") for r in resultados_opp]

    # +3 pediu_proposta
    if "pediu_proposta" in tipos_res:
        score += 3
        sinais.append("pediu_proposta")

    # +1 respondeu_interesse
    if "respondeu_interesse" in tipos_res:
        score += 1
        sinais.append("respondeu_interesse")

    # +1 contexto_origem presente
    if opp.get("contexto_origem", "").strip():
        score += 1
        sinais.append("contexto_origem")

    # +1 ultimo resultado positivo
    if resultados_opp:
        res_ordenados = sorted(
            resultados_opp,
            key=lambda r: r.get("data_resultado", ""),
            reverse=True,
        )
        ultimo = res_ordenados[0].get("tipo_resultado", "")
        if ultimo in _TIPOS_RESULTADO_POSITIVO:
            score += 1
            sinais.append("ultimo_positivo")

    # Sinais de insumos aplicados (ou pendentes — ja foram gerados = sinal forte)
    tipos_ins = {i.get("tipo_insumo", "") for i in insumos_opp}

    if "escopo_confirmado" in tipos_ins:
        score += 2
        sinais.append("escopo_confirmado")

    if "contato_confirmado" in tipos_ins:
        score += 1
        sinais.append("contato_confirmado")

    if "objetivo_confirmado" in tipos_ins:
        score += 1
        sinais.append("objetivo_confirmado")

    # Sinais de proposta formal (melhor esforço — não bloqueia se módulo ausente)
    try:
        from core.propostas_empresa import sinais_proposta_para_opp
        sinais_prop = sinais_proposta_para_opp(opp.get("id", ""))
        if "proposta_aceita" in sinais_prop:
            score += 4
            sinais.append("proposta_aceita")
        elif "proposta_aprovada" in sinais_prop:
            score += 3
            sinais.append("proposta_aprovada")
        elif "proposta_gerada" in sinais_prop:
            score += 2
            sinais.append("proposta_gerada")
    except Exception:
        pass

    # Sinal de proposta enviada (sem resposta ainda — menos forte que aprovada)
    proposta_enviada = opp.get("proposta_status") in {"enviada", "em_fila_assistida"}
    if proposta_enviada and "proposta_aprovada" not in sinais and "proposta_aceita" not in sinais:
        score += 1
        sinais.append("proposta_enviada_sem_resposta")

    return score, sinais


def detectar_bloqueios_fechamento(opp: dict, resultados_opp: list) -> list:
    """
    Retorna lista de strings descrevendo bloqueios criticos.
    Vazia = sem bloqueios.
    """
    bloqueios = []

    # Ja em estado final
    if opp.get("estagio") in _ESTAGIOS_FINAIS:
        bloqueios.append(f"estagio_final:{opp['estagio']}")

    # Linha de servico indefinida
    linha = opp.get("linha_servico_sugerida", "")
    if not linha or linha.strip().lower() in ("", "indefinida", "nao_definida"):
        bloqueios.append("linha_servico_indefinida")

    # Sem nenhum contato positivo
    tipos = {r.get("tipo_resultado", "") for r in resultados_opp}
    tem_positivo = bool(tipos & _TIPOS_RESULTADO_POSITIVO)
    if not tem_positivo:
        bloqueios.append("sem_resposta_positiva")

    # Predominancia de negativas (>= 3 negativas e 0 positivas)
    n_neg = sum(1 for r in resultados_opp if r.get("tipo_resultado") in _TIPOS_RESULTADO_NEGATIVO)
    if n_neg >= 3 and not tem_positivo:
        bloqueios.append("predominio_negativas")

    return bloqueios


def decidir_promocao(opp: dict, score: int, sinais: list, insumos_opp: list,
                     score_ganho: int = None, score_pronto: int = None,
                     exigir_escopo: bool = False) -> dict:
    """
    Retorna dict com 'acao' (ganho|pronto_para_entrega|escalar|manter) e 'motivo'.

    score_ganho / score_pronto: thresholds dinâmicos das políticas operacionais.
    exigir_escopo: sob modo conservador/manutencao, não promover a ganho sem escopo_confirmado.
    """
    if score_ganho is None:
        score_ganho = _SCORE_GANHO_PADRAO
    if score_pronto is None:
        score_pronto = _SCORE_PRONTO_PADRAO

    linha     = opp.get("linha_servico_sugerida", "")
    tipos_ins = {i.get("tipo_insumo", "") for i in insumos_opp}
    e_mkt     = "marketing" in linha.lower()

    sem_escopo   = "escopo_confirmado"   not in tipos_ins
    sem_objetivo = "objetivo_confirmado" not in tipos_ins

    # ESCALAR tem prioridade sobre PRONTO: mkt + pediu_proposta + sem escopo/objetivo
    if (score >= 2 and e_mkt and "pediu_proposta" in sinais
            and sem_escopo and sem_objetivo):
        return {
            "acao":   "escalar",
            "motivo": (
                f"score={score}; mkt sem escopo/objetivo — "
                "requer validacao humana antes de promover"
            ),
        }

    # ESCALAR por oferta: customização alta ou sem oferta mapeada (melhor esforço)
    try:
        from core.ofertas_empresa import verificar_gatilho_deliberacao_oferta
        _delib, _motivo_of = verificar_gatilho_deliberacao_oferta(opp)
        if _delib and score >= 2:
            return {
                "acao":   "escalar",
                "motivo": f"gatilho_oferta: {_motivo_of}",
            }
    except Exception:
        pass

    # GANHO: score alto + linha + sem bloqueios (ja filtrados antes)
    # Com exigir_escopo ativado: bloquear ganho se sem escopo
    if score >= score_ganho:
        if exigir_escopo and sem_escopo:
            return {
                "acao":   "escalar",
                "motivo": (
                    f"score={score} >= {score_ganho} mas exigir_escopo=True e sem escopo_confirmado; "
                    "requer validacao"
                ),
            }
        return {
            "acao":   "ganho",
            "motivo": f"score={score} >= {score_ganho}; sinais={sinais}",
        }

    # PRONTO_PARA_ENTREGA: score intermediario
    if score >= score_pronto:
        return {
            "acao":   "pronto_para_entrega",
            "motivo": f"score={score} [{score_pronto},{score_ganho-1}]; sinais={sinais}",
        }

    return {
        "acao":   "manter",
        "motivo": f"score={score}; sinais insuficientes ou incompletos",
    }


# ─── Atualizacao de pipeline ──────────────────────────────────────────────────

def atualizar_pipeline_para_entrega(opp: dict, estagio: str, status_operacional: str) -> None:
    """
    Promove a oportunidade in-place.
    Registra estagio_anterior e data_promocao para auditoria.
    """
    opp["estagio_anterior"]    = opp.get("estagio", "")
    opp["estagio"]             = estagio
    opp["status_operacional"]  = status_operacional
    opp["data_promocao"]       = datetime.now().isoformat(timespec="seconds")
    opp["promovido_por"]       = "avaliador_fechamento_comercial"


# ─── Historico ────────────────────────────────────────────────────────────────

def registrar_historico_fechamento(
    opp_id: str,
    score: int,
    sinais: list,
    decisao: dict,
    historico: list,
) -> None:
    historico.append({
        "id":           f"hfech_{len(historico)}_{opp_id}",
        "oportunidade_id": opp_id,
        "score":        score,
        "sinais":       sinais,
        "acao":         decisao["acao"],
        "motivo":       decisao["motivo"],
        "registrado_em": datetime.now().isoformat(timespec="seconds"),
    })


def _registrar_escalonamento(opp: dict, score: int, sinais: list, decisao: dict) -> None:
    """
    Marca a oportunidade para revisao humana sem alterar estagio.
    """
    opp["flag_escalar"]       = True
    opp["motivo_escalonamento"] = decisao["motivo"]
    opp["score_fechamento"]   = score


# ─── Auxiliares ───────────────────────────────────────────────────────────────

def _agrupar_por_opp(itens: list, campo: str) -> dict:
    grupos: dict = {}
    for item in itens:
        chave = item.get(campo, "")
        grupos.setdefault(chave, []).append(item)
    return grupos


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
