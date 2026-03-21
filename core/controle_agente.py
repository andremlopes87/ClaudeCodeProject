"""
core/controle_agente.py — Camada de controle reutilizável para agentes.

Fornece:
  - Estado persistente entre execuções (o que foi processado, contexto)
  - Deduplicação de itens (não reprocessar o mesmo item)
  - Fila de decisões consolidada (cross-agentes)
  - Agenda do dia com atualização idempotente por item_id
  - Aprovações humanas (ler e registrar)
  - Log estruturado por agente

Qualquer agente pode usar este módulo. Não há lógica de negócio aqui.
"""

import hashlib
import json
import logging
from datetime import date, datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_PASTA_LOGS_AGENTES = config.PASTA_LOGS / "agentes"

# ─── Estado do agente ────────────────────────────────────────────────────────

def carregar_estado(nome_agente: str) -> dict:
    """
    Carrega o estado persistido do agente. Retorna estado vazio se não existir.

    Campos do estado:
      nome_agente, ultima_execucao, ultimo_saldo, ultimo_resumo,
      itens_pendentes_escalados, itens_processados,
      hash_ultima_execucao, historico_execucoes
    """
    caminho = config.PASTA_DADOS / f"estado_{nome_agente}.json"
    if not caminho.exists():
        return _estado_inicial(nome_agente)
    with open(caminho, "r", encoding="utf-8") as f:
        estado = json.load(f)
    logger.info(f"[{nome_agente}] Estado carregado: {len(estado.get('itens_processados', []))} itens processados")
    return estado


def salvar_estado(nome_agente: str, estado: dict) -> None:
    """Persiste o estado do agente em dados/estado_{nome_agente}.json."""
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = config.PASTA_DADOS / f"estado_{nome_agente}.json"
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)
    logger.info(f"[{nome_agente}] Estado salvo.")


def ja_processado(estado: dict, item_id: str) -> bool:
    """Retorna True se o item já foi processado (autônomo ou escalado resolvido)."""
    return item_id in estado.get("itens_processados", [])


def esta_pendente(estado: dict, item_id: str) -> bool:
    """Retorna True se o item já foi escalado e aguarda aprovação."""
    return item_id in estado.get("itens_pendentes_escalados", [])


def marcar_processado(estado: dict, item_id: str) -> None:
    """Marca item como processado (não será reprocessado em execuções futuras)."""
    processados = estado.setdefault("itens_processados", [])
    if item_id not in processados:
        processados.append(item_id)


def marcar_pendente(estado: dict, item_id: str) -> None:
    """Marca item como escalado e aguardando aprovação humana."""
    pendentes = estado.setdefault("itens_pendentes_escalados", [])
    if item_id not in pendentes:
        pendentes.append(item_id)


def resolver_pendente(estado: dict, item_id: str) -> None:
    """Remove item dos pendentes e marca como processado (aprovação recebida)."""
    pendentes = estado.get("itens_pendentes_escalados", [])
    if item_id in pendentes:
        pendentes.remove(item_id)
    marcar_processado(estado, item_id)


def registrar_execucao(estado: dict, saldo: float, resumo: str, n_escalados: int, n_autonomos: int, hash_exec: str) -> None:
    """Atualiza campos de execução no estado e adiciona ao histórico."""
    agora = datetime.now().isoformat(timespec="seconds")
    estado["ultima_execucao"]     = agora
    estado["ultimo_saldo"]        = round(saldo, 2)
    estado["ultimo_resumo"]       = resumo
    estado["hash_ultima_execucao"] = hash_exec

    historico = estado.setdefault("historico_execucoes", [])
    historico.append({
        "timestamp":   agora,
        "saldo":       round(saldo, 2),
        "escalamentos": n_escalados,
        "autonomos":   n_autonomos,
        "hash":        hash_exec,
    })
    # Manter apenas as últimas 30 execuções
    if len(historico) > 30:
        estado["historico_execucoes"] = historico[-30:]


def gerar_hash_execucao(resultado: dict) -> str:
    """Hash simples do resultado para detectar mudanças entre execuções."""
    chave = json.dumps({
        "saldo":   resultado.get("posicao", {}).get("saldo_atual_estimado"),
        "riscos":  len(resultado.get("fila_riscos", [])),
        "alertas": len(resultado.get("alertas", [])),
        "resumo":  resultado.get("resumo", {}).get("resumo_curto"),
    }, sort_keys=True)
    return hashlib.md5(chave.encode()).hexdigest()[:16]


# ─── Fila de decisões consolidada ───────────────────────────────────────────

def registrar_na_fila_consolidada(itens: list) -> None:
    """
    Adiciona ou atualiza itens em fila_decisoes_consolidada.json.
    Idempotente: merge por item_id.

    Cada item deve ter:
      item_id, agente_origem, tipo, descricao, urgencia,
      acao_sugerida, prazo_sugerido, status_aprovacao
    """
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = config.PASTA_DADOS / "fila_decisoes_consolidada.json"
    fila = _carregar_json(caminho, padrao=[])

    index = {i["item_id"]: idx for idx, i in enumerate(fila)}
    agora = datetime.now().isoformat(timespec="seconds")

    for item in itens:
        item_id = item.get("item_id")
        if not item_id:
            continue
        item.setdefault("status_aprovacao", "pendente")
        item.setdefault("adicionado_em", agora)
        item["atualizado_em"] = agora

        if item_id in index:
            fila[index[item_id]].update(item)
        else:
            fila.append(item)

    _salvar_json(caminho, fila)
    logger.info(f"Fila consolidada: {len(fila)} itens totais ({len(itens)} atualizados/adicionados)")


def atualizar_status_consolidada(item_id: str, status: str) -> None:
    """Atualiza status_aprovacao de um item na fila consolidada."""
    caminho = config.PASTA_DADOS / "fila_decisoes_consolidada.json"
    fila = _carregar_json(caminho, padrao=[])
    agora = datetime.now().isoformat(timespec="seconds")
    for item in fila:
        if item.get("item_id") == item_id:
            item["status_aprovacao"] = status
            item["atualizado_em"]    = agora
            break
    _salvar_json(caminho, fila)


# ─── Agenda do dia ──────────────────────────────────────────────────────────

def atualizar_agenda(itens: list) -> None:
    """
    Atualiza agenda_do_dia.json de forma idempotente.
    Merge por item_id: insere se novo, atualiza se existe.

    Cada item deve ter: item_id, agente_origem, tipo, descricao,
      urgencia, acao_sugerida, prazo_sugerido, status_aprovacao
    """
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho  = config.PASTA_DADOS / "agenda_do_dia.json"
    hoje     = date.today().isoformat()
    agora    = datetime.now().isoformat(timespec="seconds")
    agenda   = _carregar_json(caminho, padrao={"data": hoje, "itens": [], "gerado_em": agora})

    # Reset da data se a agenda é de outro dia
    if agenda.get("data") != hoje:
        agenda = {"data": hoje, "itens": [], "gerado_em": agora}

    index = {i["item_id"]: idx for idx, i in enumerate(agenda["itens"])}

    for item in itens:
        item_id = item.get("item_id")
        if not item_id:
            continue
        item.setdefault("status_aprovacao", "pendente")
        item.setdefault("adicionado_em", agora)
        item["atualizado_em"] = agora

        if item_id in index:
            agenda["itens"][index[item_id]].update(item)
        else:
            agenda["itens"].append(item)

    agenda["gerado_em"] = agora
    _salvar_json(caminho, agenda)
    logger.info(f"Agenda do dia: {len(agenda['itens'])} itens totais")


# ─── Aprovações ─────────────────────────────────────────────────────────────

def carregar_aprovacoes() -> list:
    """
    Carrega dados/aprovacoes.json. Retorna lista vazia se não existir.

    Cada aprovação tem:
      item_id, agente, tipo, decisao (aprovado|rejeitado|adiado),
      data_decisao, observacao
    """
    caminho = config.PASTA_DADOS / "aprovacoes.json"
    return _carregar_json(caminho, padrao=[])


def registrar_aprovacao(
    item_id: str,
    agente: str,
    tipo: str,
    decisao: str,
    observacao: str = "",
) -> None:
    """
    Registra uma aprovação/rejeição humana em dados/aprovacoes.json.
    Atualiza o registro se item_id já existir.

    decisao: "aprovado" | "rejeitado" | "adiado"
    """
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho     = config.PASTA_DADOS / "aprovacoes.json"
    aprovacoes  = _carregar_json(caminho, padrao=[])
    agora       = datetime.now().isoformat(timespec="seconds")

    nova = {
        "item_id":      item_id,
        "agente":       agente,
        "tipo":         tipo,
        "decisao":      decisao,
        "data_decisao": agora,
        "observacao":   observacao,
    }

    for i, ap in enumerate(aprovacoes):
        if ap.get("item_id") == item_id:
            aprovacoes[i] = nova
            _salvar_json(caminho, aprovacoes)
            return

    aprovacoes.append(nova)
    _salvar_json(caminho, aprovacoes)
    atualizar_status_consolidada(item_id, decisao)


# ─── Log do agente ───────────────────────────────────────────────────────────

def configurar_log_agente(nome_agente: str) -> tuple:
    """
    Configura logger dedicado para o agente.
    Escreve em logs/agentes/{nome_agente}_{timestamp}.log
    Retorna (logger, caminho_do_log).
    """
    _PASTA_LOGS_AGENTES.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y-%m-%d_%H-%M")
    caminho  = _PASTA_LOGS_AGENTES / f"{nome_agente}_{ts}.log"

    log = logging.getLogger(f"agente.{nome_agente}")
    log.setLevel(logging.INFO)

    if not log.handlers:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        fh  = logging.FileHandler(str(caminho), encoding="utf-8")
        fh.setFormatter(fmt)
        sh  = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(fh)
        log.addHandler(sh)

    return log, caminho


# ─── Internos ────────────────────────────────────────────────────────────────

def _estado_inicial(nome_agente: str) -> dict:
    return {
        "nome_agente":              nome_agente,
        "ultima_execucao":          None,
        "ultimo_saldo":             None,
        "ultimo_resumo":            None,
        "itens_pendentes_escalados": [],
        "itens_processados":        [],
        "hash_ultima_execucao":     None,
        "historico_execucoes":      [],
    }


def _carregar_json(caminho: Path, padrao):
    if not caminho.exists():
        return padrao
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def _salvar_json(caminho: Path, dados) -> None:
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
