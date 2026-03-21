"""
modulos/comercial/pipeline_manager.py — Gerenciamento do pipeline comercial.

Funções puras de leitura, transformação e persistência do pipeline.
Sem lógica de agente aqui — o agente chama essas funções e decide o que fazer.

Arquivos gerenciados:
  dados/pipeline_comercial.json
  dados/fila_followups.json
  dados/historico_abordagens.json
"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_ARQ_PIPELINE  = "pipeline_comercial.json"
_ARQ_FOLLOWUPS = "fila_followups.json"
_ARQ_HISTORICO = "historico_abordagens.json"

# Estágios que indicam oportunidade encerrada
_ESTAGIOS_ENCERRADOS = {"ganho", "perdido"}


# ─── Carga ──────────────────────────────────────────────────────────────────

def carregar_pipeline() -> list:
    return _carregar(_ARQ_PIPELINE, padrao=[])


def carregar_followups() -> list:
    return _carregar(_ARQ_FOLLOWUPS, padrao=[])


def carregar_historico() -> list:
    return _carregar(_ARQ_HISTORICO, padrao=[])


# ─── Importação de novas oportunidades ──────────────────────────────────────

def importar_oportunidades_novas(leads: list, pipeline: list) -> list:
    """
    Para cada lead em fila_execucao_comercial.json que ainda não está no pipeline,
    cria um dict de oportunidade com estagio='qualificado'.

    Critérios de importação:
      - lead.abordavel_agora = True
      - ID (oport_{osm_id}) não existe no pipeline atual

    Retorna lista de novas oportunidades criadas (não persiste aqui).
    """
    ids_existentes = {o["id"] for o in pipeline}
    origens_existentes = {o.get("origem_id") for o in pipeline}
    novas = []

    for lead in leads:
        if not lead.get("abordavel_agora", False):
            continue
        osm_id = str(lead.get("osm_id", ""))
        opp_id = f"oport_{osm_id}"
        if opp_id in ids_existentes or osm_id in origens_existentes:
            continue
        novas.append(_lead_para_oportunidade(lead))

    return novas


def criar_followup_inicial(opp: dict, lead: dict, followups_existentes: list) -> dict:
    """
    Cria o follow-up de primeiro_contato para uma oportunidade recém-importada.

    agente_destino = "agente_executor_contato" — agente futuro que enviará o contato real.
    status = "pendente_execucao" — aguardando o executor pegar a tarefa.
    """
    seq = _proxima_seq(opp["id"], followups_existentes)
    fu_id = f"fu_{opp['id']}_{seq}"
    agora = datetime.now().isoformat(timespec="seconds")

    return {
        "id":              fu_id,
        "oportunidade_id": opp["id"],
        "contraparte":     opp["contraparte"],
        "canal":           opp.get("canal_sugerido", ""),
        "tipo_acao":       "primeiro_contato",
        "descricao":       lead.get("proxima_acao_comercial", opp.get("proxima_acao", "")),
        "prazo_sugerido":  None,
        "status":          "pendente_execucao",
        "agente_origem":   "agente_comercial",
        "agente_destino":  "agente_executor_contato",
        "depende_de":      None,
        "registrado_em":   agora,
        "atualizado_em":   agora,
    }


# ─── Métricas e estado do pipeline ──────────────────────────────────────────

def atualizar_metricas_pipeline(pipeline: list) -> list:
    """
    Recalcula dias_sem_atividade para cada oportunidade ativa.
    Não altera estágio. Não toma decisões.
    """
    hoje = date.today()
    for opp in pipeline:
        if opp.get("estagio") in _ESTAGIOS_ENCERRADOS:
            continue
        ultima = opp.get("ultima_atividade")
        if ultima:
            try:
                delta = (hoje - date.fromisoformat(ultima)).days
                opp["dias_sem_atividade"] = delta
            except ValueError:
                opp["dias_sem_atividade"] = 0
        opp["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    return pipeline


# ─── Detecção de casos ──────────────────────────────────────────────────────

def detectar_casos_para_revisao(pipeline: list) -> list:
    """
    Retorna oportunidades que precisam de atenção interna mas não exigem conselho:
      - Ativas há mais de COMERCIAL_DIAS_SEM_ATIVIDADE_REVISAO dias sem atividade
      - Com tentativas_contato >= COMERCIAL_TENTATIVAS_MAXIMAS (sugerir encerramento)

    Retorna lista de dicts com opp + motivo.
    """
    casos = []
    for opp in pipeline:
        if opp.get("estagio") in _ESTAGIOS_ENCERRADOS:
            continue
        dias = opp.get("dias_sem_atividade", 0)
        tent = opp.get("tentativas_contato", 0)

        if tent >= config.COMERCIAL_TENTATIVAS_MAXIMAS:
            casos.append({
                "oportunidade_id": opp["id"],
                "contraparte":     opp["contraparte"],
                "motivo":          f"tentativas_esgotadas ({tent} tentativas sem resposta registrada)",
                "tipo":            "sugerir_perdido",
            })
        elif dias >= config.COMERCIAL_DIAS_SEM_ATIVIDADE_REVISAO:
            casos.append({
                "oportunidade_id": opp["id"],
                "contraparte":     opp["contraparte"],
                "motivo":          f"sem_atividade_ha_{dias}_dias",
                "tipo":            "marcar_revisao",
            })
    return casos


def detectar_casos_para_escalamento(pipeline: list) -> list:
    """
    Retorna oportunidades que devem subir para deliberação do conselho:
      - Travadas em aguardando_decisao além do limite
      - Valor estimado acima do threshold
      - Campo explícito de escopo customizado ou sensibilidade

    Retorna lista de dicts prontos para fila_decisoes_consolidada.
    """
    casos = []
    for opp in pipeline:
        if opp.get("estagio") in _ESTAGIOS_ENCERRADOS:
            continue

        motivos = []

        # Travada em aguardando_decisao
        if (
            opp.get("estagio") == "aguardando_decisao"
            and opp.get("dias_sem_atividade", 0) > config.COMERCIAL_DIAS_LIMITE_DECISAO
        ):
            motivos.append(
                f"aguardando_decisao ha {opp['dias_sem_atividade']} dias "
                f"(limite: {config.COMERCIAL_DIAS_LIMITE_DECISAO})"
            )

        # Valor acima do threshold (quando informado)
        valor = opp.get("valor_estimado")
        if valor and float(valor) > config.COMERCIAL_THRESHOLD_PROPOSTA:
            motivos.append(
                f"valor estimado R$ {valor:,.2f} acima do threshold "
                f"R$ {config.COMERCIAL_THRESHOLD_PROPOSTA:,.2f}"
            )

        if motivos:
            casos.append({
                "item_id":        f"esc_{opp['id']}",
                "agente_origem":  "agente_comercial",
                "tipo":           "deliberacao_comercial",
                "descricao":      f"{opp['contraparte']} — {' | '.join(motivos)}",
                "urgencia":       "alta" if opp.get("estagio") == "aguardando_decisao" else "media",
                "acao_sugerida":  "revisar oportunidade e definir proximo passo ou encerrar",
                "prazo_sugerido": None,
                "status_aprovacao": "pendente",
            })
    return casos


# ─── Histórico ──────────────────────────────────────────────────────────────

def criar_evento_historico(opp_id: str, contraparte: str, tipo_evento: str, descricao: str) -> dict:
    """Cria um evento de histórico. Não persiste — quem chama decide quando salvar."""
    ts = datetime.now().isoformat(timespec="seconds")
    ts_curto = datetime.now().strftime("%Y%m%d%H%M%S")
    return {
        "id":                f"ev_{opp_id}_{ts_curto}",
        "oportunidade_id":   opp_id,
        "contraparte":       contraparte,
        "tipo_evento":       tipo_evento,
        "descricao":         descricao,
        "origem":            "agente_comercial",
        "agente_responsavel": "agente_comercial",
        "registrado_em":     ts,
    }


# ─── Persistência ───────────────────────────────────────────────────────────

def salvar_pipeline(pipeline: list) -> None:
    _salvar(_ARQ_PIPELINE, pipeline)


def salvar_followups(followups: list) -> None:
    _salvar(_ARQ_FOLLOWUPS, followups)


def salvar_historico(historico: list) -> None:
    _salvar(_ARQ_HISTORICO, historico)


def persistir_arquivos_base() -> None:
    """Cria arquivos base se não existirem (primeira execução do agente)."""
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    for nome, padrao in [
        (_ARQ_PIPELINE,  []),
        (_ARQ_FOLLOWUPS, []),
        (_ARQ_HISTORICO, []),
    ]:
        caminho = config.PASTA_DADOS / nome
        if not caminho.exists():
            _salvar(nome, padrao)
            logger.info(f"Arquivo base criado: {caminho}")


# ─── Internos ────────────────────────────────────────────────────────────────

def _lead_para_oportunidade(lead: dict) -> dict:
    osm_id = str(lead.get("osm_id", ""))
    agora  = datetime.now().isoformat(timespec="seconds")
    return {
        "id":                  f"oport_{osm_id}",
        "contraparte":         lead.get("nome", ""),
        "categoria":           lead.get("categoria_id", ""),
        "cidade":              f"{lead.get('cidade', '')}/{lead.get('estado', '')}",
        "estagio":             "qualificado",
        "canal_sugerido":      lead.get("canal_abordagem_sugerido", ""),
        "contato_principal":   lead.get("contato_principal", ""),
        "valor_estimado":      None,
        "prioridade":          lead.get("nivel_prioridade_comercial", "media"),
        "proxima_acao":        lead.get("proxima_acao_comercial", ""),
        "proxima_acao_em":     None,
        "ultima_atividade":    date.today().isoformat(),
        "dias_sem_atividade":  0,
        "tentativas_contato":  0,
        "motivo_perda":        None,
        "origem":              "fila_execucao_comercial",
        "origem_id":           osm_id,
        "observacoes":         lead.get("observacoes_comerciais", ""),
        "status_operacional":  "aguardando_execucao",
        "depende_de":          None,   # preenchido após criar follow-up
        "bloqueios":           [],
        "registrado_em":       agora,
        "atualizado_em":       agora,
    }


def _proxima_seq(opp_id: str, followups: list) -> int:
    """Retorna o próximo número de sequência para follow-ups de uma oportunidade."""
    existentes = [f for f in followups if f.get("oportunidade_id") == opp_id]
    return len(existentes) + 1


def _carregar(nome: str, padrao):
    caminho = config.PASTA_DADOS / nome
    if not caminho.exists():
        return padrao
    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)
    logger.info(f"Carregado: {caminho} ({len(dados)} registros)")
    return dados


def _salvar(nome: str, dados) -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = config.PASTA_DADOS / nome
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    logger.info(f"Salvo: {caminho} ({len(dados)} registros)")
