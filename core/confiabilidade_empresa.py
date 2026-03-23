"""
core/confiabilidade_empresa.py — Camada de confiabilidade operacional da empresa.

Responsabilidades:
  - Lock exclusivo de ciclo (impede dois ciclos simultâneos)
  - Checkpoints por etapa (rastreabilidade + diagnóstico de falha)
  - Registro de incidentes operacionais (log estruturado de falhas)
  - Cálculo de saúde da empresa (score 0-100)
  - Recovery simples (detectar + limpar ciclo interrompido)

Filosofia:
  - Sem banco. Sem event sourcing. Sem replay sofisticado.
  - Arquivos JSON simples, atômicos por sobrescrita.
  - Conservador: em caso de dúvida, não reprocessa.
  - Auditável: toda decisão de recovery vira um incidente.
"""

import json
import os
import socket
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import config

# ─── Arquivos ──────────────────────────────────────────────────────────────────

_ARQ_LOCK        = config.PASTA_DADOS / "lock_ciclo_empresa.json"
_ARQ_CHECKPOINTS = config.PASTA_DADOS / "checkpoints_ciclo.json"
_ARQ_INCIDENTES  = config.PASTA_DADOS / "incidentes_operacionais.json"
_ARQ_SAUDE       = config.PASTA_DADOS / "saude_empresa.json"
_ARQ_RECOVERY    = config.PASTA_DADOS / "recovery_ciclo.json"

# Tempo máximo que um lock pode ficar ativo antes de ser considerado stale
_LOCK_TIMEOUT_MIN = 30

# Máximo de incidentes mantidos
_MAX_INCIDENTES = 500


# ─── Lock de ciclo ────────────────────────────────────────────────────────────

def adquirir_lock_ciclo(ciclo_id: str) -> bool:
    """
    Tenta adquirir o lock de execução de ciclo.

    Retorna True se o lock foi adquirido.
    Retorna False se já existe lock ativo válido (outro ciclo em curso).

    Se houver lock stale, registra incidente e limpa automaticamente.
    """
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)

    stale = detectar_lock_stale()
    if stale:
        registrar_incidente_operacional(
            tipo_incidente="lock_stale",
            severidade="alta",
            area="operacao",
            agente="orquestrador",
            titulo=f"Lock stale detectado do ciclo {stale.get('ciclo_id','?')}",
            descricao=(
                f"Lock ativo desde {stale.get('iniciado_em','?')} "
                f"(>{_LOCK_TIMEOUT_MIN} min) — ciclo anterior pode ter falhado sem limpar o lock. "
                f"Lock foi removido automaticamente para permitir novo ciclo."
            ),
            ciclo_id=stale.get("ciclo_id", "?"),
            referencia_id=stale.get("ciclo_id", "?"),
            acao_tomada="lock_stale_removido_automaticamente",
        )
        preparar_recovery_simples(
            ciclo_id_interrompido=stale.get("ciclo_id", "?"),
            etapa_interrompida=stale.get("etapa_atual", "desconhecida"),
            motivo="lock_stale",
        )
        _limpar_lock()

    if _lock_exists():
        return False

    lock = {
        "lock_ativo":           True,
        "ciclo_id":             ciclo_id,
        "iniciado_em":          datetime.now().isoformat(timespec="seconds"),
        "hostname_ou_origem":   _hostname(),
        "pid_ou_identificador": os.getpid(),
        "etapa_atual":          "iniciando",
        "atualizado_em":        datetime.now().isoformat(timespec="seconds"),
    }
    _salvar(_ARQ_LOCK, lock)
    return True


def liberar_lock_ciclo(ciclo_id: str) -> None:
    """
    Libera o lock de ciclo.
    Chamado em finally para garantir liberação mesmo em caso de erro.
    Só remove o lock se pertence ao ciclo_id informado.
    """
    lock = _ler(_ARQ_LOCK, {})
    if lock.get("ciclo_id") == ciclo_id:
        _limpar_lock()


def atualizar_lock_etapa(ciclo_id: str, etapa: str) -> None:
    """Atualiza a etapa_atual e atualizado_em do lock (heartbeat)."""
    lock = _ler(_ARQ_LOCK, {})
    if lock.get("ciclo_id") == ciclo_id and lock.get("lock_ativo"):
        lock["etapa_atual"]  = etapa
        lock["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
        _salvar(_ARQ_LOCK, lock)


def detectar_lock_stale() -> dict | None:
    """
    Retorna o lock se ele existir e for mais antigo que _LOCK_TIMEOUT_MIN.
    Retorna None se não houver lock ou se o lock for recente (válido).
    """
    lock = _ler(_ARQ_LOCK, {})
    if not lock.get("lock_ativo"):
        return None
    try:
        iniciado = datetime.fromisoformat(lock["iniciado_em"])
        if datetime.now() - iniciado > timedelta(minutes=_LOCK_TIMEOUT_MIN):
            return lock
    except Exception:
        return lock  # lock com timestamp inválido → stale
    return None


def lock_ativo_de_outro_ciclo(ciclo_id: str) -> bool:
    """Retorna True se há lock ativo que NÃO é do ciclo_id informado."""
    lock = _ler(_ARQ_LOCK, {})
    return lock.get("lock_ativo", False) and lock.get("ciclo_id") != ciclo_id


# ─── Checkpoints por etapa ───────────────────────────────────────────────────

def registrar_checkpoint_etapa(
    ciclo_id: str,
    nome_etapa: str,
    posicao: str = "",
) -> None:
    """Marca uma etapa como em_execucao no checkpoint."""
    chk = _ler(_ARQ_CHECKPOINTS, {"ciclo_id": ciclo_id, "etapas": [], "atualizado_em": ""})

    # Se mudou o ciclo, reiniciar checkpoints
    if chk.get("ciclo_id") != ciclo_id:
        chk = {"ciclo_id": ciclo_id, "etapas": [], "atualizado_em": ""}

    # Evitar duplicata na mesma posição do mesmo ciclo
    for etapa in chk["etapas"]:
        if etapa["nome"] == nome_etapa and etapa["posicao"] == posicao and etapa["status"] == "em_execucao":
            return  # já registrado para esta posição

    chk["etapas"].append({
        "nome":         nome_etapa,
        "posicao":      posicao,
        "status":       "em_execucao",
        "iniciado_em":  datetime.now().isoformat(timespec="seconds"),
        "finalizado_em": None,
        "resumo":       {},
        "erro":         None,
    })
    chk["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    _salvar(_ARQ_CHECKPOINTS, chk)

    # Atualizar lock com etapa atual
    atualizar_lock_etapa(ciclo_id, f"{nome_etapa}[{posicao}]")


def finalizar_checkpoint_etapa(
    ciclo_id: str,
    nome_etapa: str,
    posicao: str,
    status: str,
    resumo: dict = None,
    erro: str = None,
) -> None:
    """
    Finaliza uma etapa no checkpoint com status, resumo e erro.
    status: concluida | falhou | pulada | pausada
    """
    chk = _ler(_ARQ_CHECKPOINTS, {"ciclo_id": ciclo_id, "etapas": [], "atualizado_em": ""})

    # Atualizar a última ocorrência de nome_etapa + posicao em_execucao
    for etapa in reversed(chk.get("etapas", [])):
        if etapa["nome"] == nome_etapa and etapa["posicao"] == posicao and etapa["status"] == "em_execucao":
            etapa["status"]       = status
            etapa["finalizado_em"] = datetime.now().isoformat(timespec="seconds")
            etapa["resumo"]       = resumo or {}
            etapa["erro"]         = erro
            break

    chk["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    _salvar(_ARQ_CHECKPOINTS, chk)


def etapa_ja_concluida_neste_ciclo(ciclo_id: str, nome_etapa: str, posicao: str) -> bool:
    """
    Proteção contra reprocessamento indevido.
    Retorna True se a etapa já foi concluída com sucesso neste ciclo.
    """
    chk = _ler(_ARQ_CHECKPOINTS, {})
    if chk.get("ciclo_id") != ciclo_id:
        return False
    for etapa in chk.get("etapas", []):
        if (etapa["nome"] == nome_etapa
                and etapa["posicao"] == posicao
                and etapa["status"] == "concluida"):
            return True
    return False


# ─── Incidentes operacionais ──────────────────────────────────────────────────

def registrar_incidente_operacional(
    tipo_incidente: str,
    severidade: str,
    area: str,
    agente: str,
    titulo: str,
    descricao: str,
    ciclo_id: str = "",
    referencia_id: str = "",
    acao_tomada: str = "",
    status: str = "aberto",
) -> dict:
    """
    Registra incidente em incidentes_operacionais.json.

    tipo_incidente: lock_stale | falha_etapa | arquivo_essencial_ausente |
                    checkpoint_inconsistente | reprocessamento_bloqueado |
                    erro_integracao | governanca_inconsistente |
                    politicas_inconsistentes | estado_corrompido
    severidade: baixa | media | alta | critica
    status: aberto | monitorando | resolvido | ignorado
    """
    incidentes = _ler(_ARQ_INCIDENTES, [])

    inc = {
        "id":             f"inc_{uuid4().hex[:10]}",
        "ciclo_id":       ciclo_id,
        "tipo_incidente": tipo_incidente,
        "severidade":     severidade,
        "area":           area,
        "agente":         agente,
        "titulo":         titulo[:150],
        "descricao":      descricao[:500],
        "referencia_id":  referencia_id,
        "status":         status,
        "detectado_em":   datetime.now().isoformat(timespec="seconds"),
        "resolvido_em":   None,
        "acao_tomada":    acao_tomada[:200],
    }
    incidentes.append(inc)
    incidentes = incidentes[-_MAX_INCIDENTES:]
    _salvar(_ARQ_INCIDENTES, incidentes)
    return inc


def resolver_incidente(incidente_id: str, acao: str = "") -> bool:
    """Marca um incidente como resolvido."""
    incidentes = _ler(_ARQ_INCIDENTES, [])
    for inc in incidentes:
        if inc["id"] == incidente_id:
            inc["status"]      = "resolvido"
            inc["resolvido_em"] = datetime.now().isoformat(timespec="seconds")
            if acao:
                inc["acao_tomada"] = acao
            _salvar(_ARQ_INCIDENTES, incidentes)
            return True
    return False


def contar_incidentes_abertos() -> dict:
    """Retorna contagem de incidentes abertos por severidade."""
    incidentes = _ler(_ARQ_INCIDENTES, [])
    abertos = [i for i in incidentes if i.get("status") in ("aberto", "monitorando")]
    contagem = {"total": len(abertos), "critica": 0, "alta": 0, "media": 0, "baixa": 0}
    for inc in abertos:
        sev = inc.get("severidade", "baixa")
        contagem[sev] = contagem.get(sev, 0) + 1
    return contagem


# ─── Saúde da empresa ────────────────────────────────────────────────────────

def calcular_saude_empresa() -> dict:
    """
    Calcula score de saúde 0-100 com regras explícitas.

    Penalizações:
      -25  último ciclo: falha_estrutural
      -15  último ciclo: falha_parcial
      - 5  último ciclo: concluido_com_alertas
      -15  incidente aberto critico (por incidente, máx -30)
      -10  incidente aberto alta (por incidente, máx -20)
      - 5  incidente aberto media (por incidente, máx -10)
      -15  risco de caixa
      - 8  entregas bloqueadas > 0
      - 5  erros no ciclo > 0
      - 3  deliberacoes_pendentes > 5
      - 5  agentes_pausados > 0
      - 3  areas_pausadas > 0

    Status:
      80-100  saudavel
      60-79   atencao
      40-59   degradada
      <40     critica
    """
    score = 100
    alertas = []
    agentes_degradados = []
    areas_degradadas = []

    ciclo     = _ler_dados("ciclo_operacional.json", {})
    metricas  = _ler_dados("metricas_empresa.json", {})
    gov       = _ler_dados("estado_governanca_conselho.json", {})
    caixa     = _ler_dados("posicao_caixa.json", {})
    incid     = contar_incidentes_abertos()
    incidentes_lista = _ler(_ARQ_INCIDENTES, [])

    # Último ciclo
    status_ciclo = ciclo.get("status_geral", "desconhecido")
    if status_ciclo == "falha_estrutural":
        score -= 25
        alertas.append("Último ciclo: falha estrutural")
    elif status_ciclo == "falha_parcial":
        score -= 15
        alertas.append("Último ciclo: falha parcial")
    elif status_ciclo == "concluido_com_alertas":
        score -= 5
        alertas.append("Último ciclo: concluído com alertas")

    # Incidentes abertos
    penalidade_crit = min(incid["critica"] * 15, 30)
    penalidade_alta = min(incid["alta"] * 10, 20)
    penalidade_med  = min(incid["media"] * 5, 10)
    score -= penalidade_crit + penalidade_alta + penalidade_med
    if incid["critica"] > 0:
        alertas.append(f"{incid['critica']} incidente(s) crítico(s) aberto(s)")
    if incid["alta"] > 0:
        alertas.append(f"{incid['alta']} incidente(s) alta severidade aberto(s)")

    # Risco de caixa
    if caixa.get("risco_caixa") or metricas.get("risco_de_caixa"):
        score -= 15
        alertas.append("Risco de caixa detectado")

    # Entregas bloqueadas
    ent_bloq = metricas.get("entregas_bloqueadas", 0)
    if ent_bloq > 0:
        score -= 8
        alertas.append(f"{ent_bloq} entrega(s) bloqueada(s)")
        areas_degradadas.append("entrega")

    # Erros no ciclo
    erros_ciclo = metricas.get("erros_ciclo_atual", 0)
    if erros_ciclo > 0:
        score -= 5
        alertas.append(f"{erros_ciclo} erro(s) no último ciclo")
        for etapa in ciclo.get("etapas", []):
            if etapa.get("status") == "erro":
                agentes_degradados.append(etapa["nome_agente"])

    # Deliberações acumuladas
    delib_p = metricas.get("deliberacoes_pendentes", 0)
    if delib_p > 5:
        score -= 3
        alertas.append(f"{delib_p} deliberações pendentes acumuladas")

    # Governança: pausas
    ag_pausados = gov.get("agentes_pausados", [])
    ar_pausadas = gov.get("areas_pausadas", [])
    if ag_pausados:
        score -= 5
        alertas.append(f"{len(ag_pausados)} agente(s) pausado(s) pelo conselho")
    if ar_pausadas:
        score -= 3
        alertas.append(f"{len(ar_pausadas)} área(s) pausada(s) pelo conselho")
        areas_degradadas.extend(ar_pausadas)

    score = max(0, min(100, score))

    # Status geral
    if score >= 80:
        status_geral = "saudavel"
    elif score >= 60:
        status_geral = "atencao"
    elif score >= 40:
        status_geral = "degradada"
    else:
        status_geral = "critica"

    # Último incidente relevante (aberto, mais recente)
    incidentes_abertos = sorted(
        [i for i in incidentes_lista if i.get("status") in ("aberto", "monitorando")],
        key=lambda x: x.get("detectado_em", ""),
        reverse=True,
    )
    ultimo_incidente = incidentes_abertos[0] if incidentes_abertos else None

    # Último recovery
    recovery = _ler(_ARQ_RECOVERY, {})

    saude = {
        "atualizado_em":       datetime.now().isoformat(timespec="seconds"),
        "status_geral":        status_geral,
        "score_saude":         score,
        "alertas":             alertas,
        "incidentes_abertos":  incid,
        "gargalos_criticos":   _ler_dados("painel_conselho.json", {}).get("gargalos", [])[:5],
        "agentes_degradados":  list(set(agentes_degradados)),
        "areas_degradadas":    list(set(areas_degradadas)),
        "ultimo_ciclo_status": status_ciclo,
        "ultimo_ciclo_id":     ciclo.get("ciclo_id", "—"),
        "ultimo_incidente":    {
            "id":        ultimo_incidente["id"],
            "titulo":    ultimo_incidente["titulo"],
            "severidade": ultimo_incidente["severidade"],
            "detectado_em": ultimo_incidente["detectado_em"],
        } if ultimo_incidente else None,
        "ultimo_recovery":     {
            "ciclo_interrompido": recovery.get("ultimo_ciclo_interrompido"),
            "etapa":              recovery.get("etapa_interrompida"),
            "detectado_em":       recovery.get("detectado_em"),
            "status":             recovery.get("status"),
        } if recovery.get("ultimo_ciclo_interrompido") else None,
        "observacoes":         "; ".join(alertas[:5]) if alertas else "empresa operando normalmente",
    }

    _salvar(_ARQ_SAUDE, saude)
    return saude


# ─── Recovery simples ────────────────────────────────────────────────────────

def preparar_recovery_simples(
    ciclo_id_interrompido: str,
    etapa_interrompida: str,
    motivo: str = "",
) -> dict:
    """
    Registra estado de recovery para diagnóstico.

    NÃO tenta retomar no meio: apenas documenta e permite novo ciclo limpo.
    O próximo ciclo começa do zero, mas com o contexto do que aconteceu.
    """
    recovery = {
        "ultimo_ciclo_interrompido": ciclo_id_interrompido,
        "etapa_interrompida":        etapa_interrompida,
        "motivo":                    motivo,
        "detectado_em":              datetime.now().isoformat(timespec="seconds"),
        "acao_sugerida":             (
            "Iniciar novo ciclo limpo. "
            "Verificar incidentes_operacionais.json para diagnóstico. "
            "Checkpoints do ciclo anterior disponíveis em checkpoints_ciclo.json."
        ),
        "recovery_executado_em":     None,
        "status":                    "pendente",
    }
    _salvar(_ARQ_RECOVERY, recovery)
    return recovery


def marcar_recovery_executado(ciclo_id_novo: str) -> None:
    """Atualiza recovery_ciclo após iniciar ciclo de recuperação."""
    recovery = _ler(_ARQ_RECOVERY, {})
    if recovery:
        recovery["recovery_executado_em"] = datetime.now().isoformat(timespec="seconds")
        recovery["ciclo_recuperacao_id"]  = ciclo_id_novo
        recovery["status"]                = "executado"
        _salvar(_ARQ_RECOVERY, recovery)


# ─── API de leitura para o painel ────────────────────────────────────────────

def resumir_confiabilidade_para_painel() -> dict:
    """Snapshot consolidado para o Painel do Conselho."""
    saude       = _ler(_ARQ_SAUDE, {})
    lock        = _ler(_ARQ_LOCK, {})
    recovery    = _ler(_ARQ_RECOVERY, {})
    checkpoints = _ler(_ARQ_CHECKPOINTS, {})
    incidentes  = _ler(_ARQ_INCIDENTES, [])

    incidentes_abertos = sorted(
        [i for i in incidentes if i.get("status") in ("aberto", "monitorando")],
        key=lambda x: x.get("detectado_em", ""),
        reverse=True,
    )[:20]

    return {
        "saude":               saude,
        "lock_ativo":          lock.get("lock_ativo", False),
        "lock_ciclo_id":       lock.get("ciclo_id"),
        "lock_etapa":          lock.get("etapa_atual"),
        "lock_iniciado_em":    lock.get("iniciado_em"),
        "recovery":            recovery,
        "checkpoints_ultimo_ciclo": checkpoints,
        "incidentes_abertos":  incidentes_abertos,
        "todos_incidentes":    sorted(incidentes, key=lambda x: x.get("detectado_em",""), reverse=True)[:50],
    }


# ─── Auxiliares internos ──────────────────────────────────────────────────────

def _lock_exists() -> bool:
    lock = _ler(_ARQ_LOCK, {})
    return lock.get("lock_ativo", False)


def _limpar_lock() -> None:
    _salvar(_ARQ_LOCK, {"lock_ativo": False, "ciclo_id": None, "liberado_em": datetime.now().isoformat(timespec="seconds")})


def _hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "desconhecido"


def _ler(caminho: Path, padrao):
    if not caminho.exists():
        return padrao
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return padrao


def _ler_dados(nome: str, padrao):
    return _ler(config.PASTA_DADOS / nome, padrao)


def _salvar(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
