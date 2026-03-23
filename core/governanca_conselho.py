"""
core/governanca_conselho.py

Camada de governança do Conselho. Centraliza tudo que o conselho pode
decidir ou orientar: deliberações, pausas de agentes/áreas, modo da
empresa, diretrizes e ajustes estratégicos de alto nível.

Nao manipula registros operacionais finos. Atua por estado e configuração.
Toda ação gera trilha auditável em historico_comandos_conselho.json.

Arquivos gerenciados:
  dados/comandos_conselho.json
  dados/historico_comandos_conselho.json
  dados/diretrizes_conselho.json
  dados/estado_governanca_conselho.json

Efeitos absorbidos pelo orquestrador:
  - agentes_pausados → agente não roda no ciclo
  - areas_pausadas   → agentes da área não rodam
  - modo_empresa     → registrado no ciclo para auditoria

Efeitos absorbidos pela camada de deliberação:
  - deliberacao:aprovar/rejeitar/adiar → atualiza deliberacoes_conselho.json
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_MODOS_VALIDOS = {"normal", "conservador", "foco_caixa", "foco_crescimento", "manutencao"}
_STATUS_TERMINAIS = {"aplicado", "rejeitado", "expirado"}


# ─── Estado da governança ─────────────────────────────────────────────────────

def carregar_estado_governanca() -> dict:
    return _ler("estado_governanca_conselho.json", _estado_inicial())


def salvar_estado_governanca(estado: dict) -> None:
    _salvar("estado_governanca_conselho.json", estado)


def _estado_inicial() -> dict:
    return {
        "ultima_execucao":    None,
        "modo_empresa":       "normal",
        "agentes_pausados":   [],
        "areas_pausadas":     [],
        "linhas_priorizadas": [],
        "thresholds_ativos":  {},
        "comandos_pendentes": 0,
        "comandos_aplicados": 0,
        "diretrizes_ativas":  0,
        "ultimo_snapshot":    None,
    }


# ─── Comandos ─────────────────────────────────────────────────────────────────

def carregar_comandos_conselho() -> list:
    return _ler("comandos_conselho.json", [])


def salvar_comandos_conselho(comandos: list) -> None:
    _salvar("comandos_conselho.json", comandos)


def registrar_comando_conselho(
    tipo_comando: str,
    alvo_tipo: str,
    alvo_id: str,
    valor: str,
    justificativa: str,
    origem: str = "painel_conselho",
    observacoes: str = "",
) -> dict:
    """
    Cria, persiste e aplica imediatamente um comando do conselho.
    Retorna o comando criado.
    """
    comandos = carregar_comandos_conselho()
    historico = _ler("historico_comandos_conselho.json", [])
    estado    = carregar_estado_governanca()

    cmd = {
        "id":            f"cmd_{len(comandos):04d}_{datetime.now().strftime('%H%M%S')}",
        "tipo_comando":  tipo_comando,
        "alvo_tipo":     alvo_tipo,
        "alvo_id":       alvo_id,
        "valor":         valor,
        "justificativa": justificativa,
        "status":        "pendente",
        "criado_em":     datetime.now().isoformat(timespec="seconds"),
        "aplicado_em":   None,
        "origem":        origem,
        "observacoes":   observacoes,
    }

    # Aplicar imediatamente
    sucesso, mensagem = _aplicar_comando(cmd, estado)
    cmd["status"]     = "aplicado" if sucesso else "bloqueado"
    cmd["aplicado_em"] = datetime.now().isoformat(timespec="seconds")
    cmd["observacoes"] = mensagem

    comandos.append(cmd)
    salvar_comandos_conselho(comandos)

    # Atualizar estado
    estado["ultima_execucao"]    = datetime.now().isoformat(timespec="seconds")
    estado["comandos_aplicados"] = sum(1 for c in comandos if c["status"] == "aplicado")
    estado["comandos_pendentes"] = sum(1 for c in comandos if c["status"] == "pendente")
    estado["diretrizes_ativas"]  = sum(1 for d in _ler("diretrizes_conselho.json", []) if d.get("ativa"))
    salvar_estado_governanca(estado)

    # Registrar no histórico
    registrar_evento_comando(cmd["id"], "comando_aplicado" if sucesso else "comando_bloqueado",
                             mensagem, origem, historico)
    _salvar("historico_comandos_conselho.json", historico)

    logger.info(f"[governanca] {tipo_comando}/{alvo_id} → {cmd['status']}: {mensagem}")
    return cmd


def aplicar_comandos_conselho() -> list:
    """Reaplica comandos pendentes. Útil para reprocessamento."""
    comandos = carregar_comandos_conselho()
    estado   = carregar_estado_governanca()
    aplicados = []
    for cmd in comandos:
        if cmd["status"] == "pendente":
            sucesso, msg = _aplicar_comando(cmd, estado)
            cmd["status"]     = "aplicado" if sucesso else "bloqueado"
            cmd["aplicado_em"] = datetime.now().isoformat(timespec="seconds")
            cmd["observacoes"] = msg
            if sucesso:
                aplicados.append(cmd)
    salvar_comandos_conselho(comandos)
    salvar_estado_governanca(estado)
    return aplicados


def _aplicar_comando(cmd: dict, estado: dict) -> tuple:
    """
    Aplica um comando ao estado de governança (in-place).
    Para deliberações, aplica diretamente em deliberacoes_conselho.json.
    Retorna (sucesso: bool, mensagem: str).
    """
    tipo   = cmd["tipo_comando"]
    alvo   = cmd["alvo_id"]
    valor  = cmd["valor"]
    justif = cmd["justificativa"]

    # ── Deliberações ──────────────────────────────────────────────────────────
    if tipo == "deliberacao":
        delibs = _ler("deliberacoes_conselho.json", [])
        delib  = next((d for d in delibs if d.get("id") == alvo), None)
        if not delib:
            return False, f"Deliberação '{alvo}' não encontrada"
        if delib.get("status") in ("resolvida", "aplicada"):
            return False, f"Deliberação já {delib['status']}"

        if valor == "aprovado":
            delib["status"]             = "resolvida"
            delib["decisao_conselho"]   = "aprovado"
        elif valor == "rejeitado":
            delib["status"]             = "resolvida"
            delib["decisao_conselho"]   = "rejeitado"
        elif valor == "adiado":
            delib["status"]             = "pendente"
            delib["decisao_conselho"]   = "adiado"
            delib["urgencia"]           = "media"
        else:
            return False, f"Valor inválido para deliberação: '{valor}'"

        delib["observacao_conselho"] = justif
        delib["resolvido_em"]        = datetime.now().isoformat(timespec="seconds")
        delib["atualizado_em"]       = datetime.now().isoformat(timespec="seconds")
        _salvar("deliberacoes_conselho.json", delibs)
        return True, f"Deliberação '{alvo[:30]}' → {valor}"

    # ── Pausar/retomar agente ─────────────────────────────────────────────────
    elif tipo == "pausar_agente":
        pausados = estado.setdefault("agentes_pausados", [])
        if alvo not in pausados:
            pausados.append(alvo)
        return True, f"Agente '{alvo}' pausado"

    elif tipo == "retomar_agente":
        pausados = estado.setdefault("agentes_pausados", [])
        if alvo in pausados:
            pausados.remove(alvo)
        return True, f"Agente '{alvo}' retomado"

    # ── Pausar/retomar área ───────────────────────────────────────────────────
    elif tipo == "pausar_area":
        pausadas = estado.setdefault("areas_pausadas", [])
        if alvo not in pausadas:
            pausadas.append(alvo)
        return True, f"Área '{alvo}' pausada"

    elif tipo == "retomar_area":
        pausadas = estado.setdefault("areas_pausadas", [])
        if alvo in pausadas:
            pausadas.remove(alvo)
        return True, f"Área '{alvo}' retomada"

    # ── Modo da empresa ───────────────────────────────────────────────────────
    elif tipo == "definir_modo_empresa":
        if valor not in _MODOS_VALIDOS:
            return False, f"Modo inválido: '{valor}'. Válidos: {_MODOS_VALIDOS}"
        modo_anterior = estado.get("modo_empresa", "normal")
        estado["modo_empresa"] = valor
        return True, f"Modo: {modo_anterior} → {valor}"

    # ── Threshold ─────────────────────────────────────────────────────────────
    elif tipo == "alterar_threshold":
        thresholds = estado.setdefault("thresholds_ativos", {})
        anterior   = thresholds.get(alvo, "—")
        thresholds[alvo] = valor
        return True, f"Threshold '{alvo}': {anterior} → {valor}"

    # ── Priorizar linha de serviço ────────────────────────────────────────────
    elif tipo in ("priorizar_linha_servico", "alterar_prioridade_linha"):
        linhas = estado.setdefault("linhas_priorizadas", [])
        if valor == "remover":
            if alvo in linhas:
                linhas.remove(alvo)
            return True, f"Linha '{alvo}' removida das priorizadas"
        if alvo not in linhas:
            linhas.append(alvo)
        return True, f"Linha '{alvo}' priorizada"

    # ── Foco temporário em área ───────────────────────────────────────────────
    elif tipo == "foco_temporario_area":
        areas_foco = estado.setdefault("areas_foco", [])
        if alvo not in areas_foco:
            areas_foco.append(alvo)
        return True, f"Foco temporário em '{alvo}' ativado"

    # ── Diretriz (apenas registra no arquivo de diretrizes) ───────────────────
    elif tipo == "registrar_diretriz":
        # O alvo_id é a categoria, valor é o título, justificativa é a descrição
        return True, f"Diretriz registrada via registrar_diretriz_conselho()"

    else:
        return False, f"Tipo de comando desconhecido: '{tipo}'"


# ─── Diretrizes ───────────────────────────────────────────────────────────────

def carregar_diretrizes_conselho() -> list:
    return _ler("diretrizes_conselho.json", [])


def salvar_diretrizes_conselho(diretrizes: list) -> None:
    _salvar("diretrizes_conselho.json", diretrizes)


def registrar_diretriz_conselho(
    categoria: str,
    titulo: str,
    descricao: str,
    prioridade: str = "media",
    origem: str = "painel_conselho",
) -> dict:
    """Cria uma nova diretriz ativa do conselho."""
    diretrizes = carregar_diretrizes_conselho()
    historico  = _ler("historico_comandos_conselho.json", [])

    diretriz = {
        "id":           f"dir_{len(diretrizes):04d}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "categoria":    categoria,
        "titulo":       titulo,
        "descricao":    descricao,
        "ativa":        True,
        "prioridade":   prioridade,
        "criado_em":    datetime.now().isoformat(timespec="seconds"),
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
    }

    diretrizes.append(diretriz)
    salvar_diretrizes_conselho(diretrizes)

    # Atualizar contagem no estado
    estado = carregar_estado_governanca()
    estado["diretrizes_ativas"] = sum(1 for d in diretrizes if d.get("ativa"))
    salvar_estado_governanca(estado)

    registrar_evento_comando(
        diretriz["id"], "diretriz_registrada",
        f"{categoria} | {titulo}", origem, historico,
    )
    _salvar("historico_comandos_conselho.json", historico)

    logger.info(f"[governanca] diretriz: {titulo}")
    return diretriz


def desativar_diretriz_conselho(diretriz_id: str) -> bool:
    """Desativa uma diretriz pelo id."""
    diretrizes = carregar_diretrizes_conselho()
    for d in diretrizes:
        if d.get("id") == diretriz_id:
            d["ativa"] = False
            d["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
            salvar_diretrizes_conselho(diretrizes)
            estado = carregar_estado_governanca()
            estado["diretrizes_ativas"] = sum(1 for x in diretrizes if x.get("ativa"))
            salvar_estado_governanca(estado)
            return True
    return False


# ─── Histórico ────────────────────────────────────────────────────────────────

def registrar_evento_comando(
    cmd_id: str,
    evento: str,
    descricao: str,
    origem: str,
    historico: list,
) -> None:
    historico.append({
        "id":           f"hcmd_{len(historico):04d}_{datetime.now().strftime('%H%M%S')}",
        "comando_id":   cmd_id,
        "evento":       evento,
        "descricao":    descricao,
        "origem":       origem,
        "registrado_em": datetime.now().isoformat(timespec="seconds"),
    })


# ─── Resumo para o painel ─────────────────────────────────────────────────────

def resumir_governanca_ativa() -> dict:
    """Retorna snapshot do estado de governança para exibição no painel."""
    estado    = carregar_estado_governanca()
    diretrizes = carregar_diretrizes_conselho()
    comandos  = carregar_comandos_conselho()
    recentes  = sorted(
        [c for c in comandos if c.get("status") == "aplicado"],
        key=lambda x: x.get("criado_em", ""),
        reverse=True,
    )[:8]

    return {
        "modo_empresa":       estado.get("modo_empresa", "normal"),
        "agentes_pausados":   estado.get("agentes_pausados", []),
        "areas_pausadas":     estado.get("areas_pausadas", []),
        "linhas_priorizadas": estado.get("linhas_priorizadas", []),
        "thresholds_ativos":  estado.get("thresholds_ativos", {}),
        "diretrizes_ativas":  [d for d in diretrizes if d.get("ativa")],
        "comandos_recentes":  recentes,
        "total_comandos":     len(comandos),
        "atualizado_em":      estado.get("ultima_execucao", "—"),
    }


# ─── Auxiliares ───────────────────────────────────────────────────────────────

def _ler(nome: str, padrao):
    caminho = config.PASTA_DADOS / nome
    if not caminho.exists():
        return padrao
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return padrao


def _salvar(nome: str, dados) -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = config.PASTA_DADOS / nome
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
