"""
core/llm_memoria.py

Memória compacta por conta/oportunidade que persiste entre ciclos.

Permite que agentes baseados em regras consultem histórico anterior
e, quando o LLM real for ativado, ele receba contexto completo.

Funciona 100% sem API key — a memória é auxiliar, nunca bloqueante.

Arquivo gerenciado: dados/memoria_agentes.json

Estrutura:
  {
    "por_conta": {
      "empresa_123": {
        "resumo": "Barbearia do Zé, semi_digital, 2 tentativas sem resposta",
        "ultima_atualizacao": "2026-03-25T10:00:00",
        "interacoes": 3,
        "contexto_comercial": "proposta enviada, aguardando",
        "canais_tentados": ["email"],
        "notas": []
      }
    },
    "por_agente": {
      "agente_comercial": {
        "resumo_ciclo_anterior": "12 oportunidades, 3 propostas, 1 aceite pendente",
        "ultima_atualizacao": "2026-03-25T10:00:00"
      }
    }
  }
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_MEMORIA = config.PASTA_DADOS / "memoria_agentes.json"
_MAX_RESUMO  = 500  # caracteres máximos por resumo de conta


# ─── I/O ──────────────────────────────────────────────────────────────────────

def _ler() -> dict:
    """Lê o arquivo de memória. Retorna estrutura vazia se ausente ou corrompido."""
    if not _ARQ_MEMORIA.exists():
        return {"por_conta": {}, "por_agente": {}}
    try:
        with open(_ARQ_MEMORIA, encoding="utf-8") as f:
            dados = json.load(f)
        if not isinstance(dados, dict):
            raise ValueError("formato inválido")
        dados.setdefault("por_conta",  {})
        dados.setdefault("por_agente", {})
        return dados
    except Exception as exc:
        log.warning(f"[llm_memoria] arquivo corrompido, recriando: {exc}")
        return {"por_conta": {}, "por_agente": {}}


def _salvar(dados: dict) -> None:
    import os
    try:
        _ARQ_MEMORIA.parent.mkdir(parents=True, exist_ok=True)
        conteudo = json.dumps(dados, ensure_ascii=False, indent=2)
        tmp = _ARQ_MEMORIA.with_suffix(_ARQ_MEMORIA.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(conteudo)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _ARQ_MEMORIA)
    except Exception as exc:
        log.warning(f"[llm_memoria] falha ao salvar: {exc}")


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ─── Memória por conta ────────────────────────────────────────────────────────

def obter_memoria_conta(empresa_id: str) -> "dict | None":
    """
    Retorna a memória de uma conta (empresa) ou None se não existir.

    Campos retornados:
      resumo, ultima_atualizacao, interacoes, contexto_comercial,
      canais_tentados, notas
    """
    if not empresa_id:
        return None
    return _ler()["por_conta"].get(empresa_id)


def atualizar_memoria_conta(empresa_id: str, dados: dict) -> None:
    """
    Atualiza (merge) a memória de uma conta.

    Os campos em dados são mesclados com os existentes:
      - resumo           : str — texto livre sobre o histórico
      - contexto_comercial: str — situação atual no pipeline
      - canais_tentados  : list — adiciona à lista existente
      - notas            : list — adiciona à lista existente
      - interacoes       : int — incremento se não informado explicitamente

    Regra de compactação do resumo:
      - Se resumo <= 500 chars: mantém como está
      - Se resumo > 500 chars + modo real: usa router.resumir() para compactar
      - Se resumo > 500 chars + dry-run: trunca para 497 + "..."
    """
    if not empresa_id:
        return

    memoria = _ler()
    existente = memoria["por_conta"].get(empresa_id, {
        "resumo": "",
        "ultima_atualizacao": "",
        "interacoes": 0,
        "contexto_comercial": "",
        "canais_tentados": [],
        "notas": [],
    })

    # Mesclar campos
    if "resumo" in dados:
        existente["resumo"] = _compactar_resumo(dados["resumo"], empresa_id)

    if "contexto_comercial" in dados:
        existente["contexto_comercial"] = str(dados["contexto_comercial"])[:300]

    if "canais_tentados" in dados:
        canais = existente.get("canais_tentados") or []
        for c in dados["canais_tentados"]:
            if c not in canais:
                canais.append(c)
        existente["canais_tentados"] = canais

    if "notas" in dados:
        notas = existente.get("notas") or []
        for n in dados["notas"]:
            notas.append({"nota": str(n), "em": _agora()})
        existente["notas"] = notas[-20:]  # guarda apenas as últimas 20

    # Incrementar interações
    if "interacoes" in dados:
        existente["interacoes"] = int(dados["interacoes"])
    else:
        existente["interacoes"] = existente.get("interacoes", 0) + 1

    existente["ultima_atualizacao"] = _agora()
    memoria["por_conta"][empresa_id] = existente
    _salvar(memoria)
    log.info(f"[llm_memoria] conta {empresa_id} atualizada ({existente['interacoes']} interações)")


# ─── Memória por agente ───────────────────────────────────────────────────────

def obter_memoria_agente(nome_agente: str) -> "dict | None":
    """
    Retorna a memória de um agente ou None se não existir.

    Campos retornados:
      resumo_ciclo_anterior, ultima_atualizacao
    """
    if not nome_agente:
        return None
    return _ler()["por_agente"].get(nome_agente)


def atualizar_memoria_agente(nome_agente: str, dados: dict) -> None:
    """
    Atualiza a memória de um agente.

    Campos esperados em dados:
      resumo_ciclo_anterior: str — síntese do último ciclo executado
    """
    if not nome_agente:
        return

    memoria   = _ler()
    existente = memoria["por_agente"].get(nome_agente, {
        "resumo_ciclo_anterior": "",
        "ultima_atualizacao": "",
    })

    if "resumo_ciclo_anterior" in dados:
        resumo = str(dados["resumo_ciclo_anterior"])
        if len(resumo) > _MAX_RESUMO:
            resumo = resumo[:497] + "..."
        existente["resumo_ciclo_anterior"] = resumo

    existente["ultima_atualizacao"] = _agora()
    memoria["por_agente"][nome_agente] = existente
    _salvar(memoria)
    log.info(f"[llm_memoria] agente {nome_agente} atualizado")


# ─── Gerador de contexto para LLM ────────────────────────────────────────────

def gerar_contexto_llm(empresa_id: str = None, agente: str = None) -> str:
    """
    Monta texto compacto combinando memória de conta e de agente.

    Útil para:
      - Injetar no LLM real como contexto histórico
      - Debug em dry-run: ver o contexto que seria enviado
      - Agentes baseados em regras: consultar histórico sem LLM

    Retorna string vazia se não houver memória relevante.
    """
    partes: list[str] = []

    if empresa_id:
        mem = obter_memoria_conta(empresa_id)
        if mem:
            if mem.get("resumo"):
                partes.append(f"Histórico: {mem['resumo']}")
            if mem.get("contexto_comercial"):
                partes.append(f"Situação: {mem['contexto_comercial']}")
            if mem.get("canais_tentados"):
                partes.append(f"Canais tentados: {', '.join(mem['canais_tentados'])}")
            if mem.get("interacoes"):
                partes.append(f"Interações: {mem['interacoes']}")
            if mem.get("notas"):
                ultima_nota = mem["notas"][-1].get("nota", "")
                if ultima_nota:
                    partes.append(f"Última nota: {ultima_nota}")

    if agente:
        mem_ag = obter_memoria_agente(agente)
        if mem_ag and mem_ag.get("resumo_ciclo_anterior"):
            partes.append(f"Ciclo anterior ({agente}): {mem_ag['resumo_ciclo_anterior']}")

    return " | ".join(partes)


# ─── Consulta geral ───────────────────────────────────────────────────────────

def listar_contas_com_memoria() -> list:
    """Retorna lista de empresa_ids que têm memória registrada."""
    return list(_ler()["por_conta"].keys())


def listar_agentes_com_memoria() -> list:
    """Retorna lista de nomes de agentes com memória registrada."""
    return list(_ler()["por_agente"].keys())


# ─── Compactação ─────────────────────────────────────────────────────────────

def _compactar_resumo(resumo: str, empresa_id: str) -> str:
    """
    Garante que o resumo não passe de _MAX_RESUMO caracteres.

    Modo real: tenta usar o router para resumir de forma inteligente.
    Dry-run (ou falha): trunca com "..." e loga.
    """
    if len(resumo) <= _MAX_RESUMO:
        return resumo

    modo = getattr(config, "LLM_MODO", "dry-run").strip().lower()

    if modo == "real":
        try:
            # Importação lazy para evitar circular: memoria ← router ← memoria
            from core.llm_router import LLMRouter
            router = LLMRouter()
            if router.modo == "real":
                resp = router.resumir({
                    "agente": "llm_memoria",
                    "tarefa": "compactar_resumo_conta",
                    "dados": {"texto": resumo, "empresa_id": empresa_id},
                })
                if resp.get("sucesso") and resp.get("resultado", {}).get("resumo"):
                    compactado = str(resp["resultado"]["resumo"])
                    if len(compactado) <= _MAX_RESUMO:
                        log.info(
                            f"[llm_memoria] resumo de {empresa_id} compactado via LLM "
                            f"({len(resumo)} → {len(compactado)} chars)"
                        )
                        return compactado
        except Exception as exc:
            log.warning(f"[llm_memoria] falha ao compactar via LLM: {exc}")

    # Fallback: truncar
    truncado = resumo[:497] + "..."
    log.info(
        f"[llm_memoria] resumo de {empresa_id} truncado "
        f"({len(resumo)} → {len(truncado)} chars, modo={modo})"
    )
    return truncado
