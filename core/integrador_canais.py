"""
core/integrador_canais.py — Camada de integração de canais.

Converte execuções prontas (fila_execucao_contato.json) em resultados
padronizados (resultados_contato.json) para consumo pelo agente_comercial.

Responsabilidade única:
  transformar execucao_pronta → resultado_contato (status_aplicacao=pendente)

Não toma decisão comercial. Não altera pipeline. Não interpreta negócio.

No modo dry-run (atual):
  Usa respostas_simuladas_contato.json como fonte controlada.
  Se não houver resposta simulada para uma execução → nada é gerado → sem invenção.

No modo real (futuro):
  Substituir CanalDryRun por conector real (Twilio, WhatsApp Cloud, etc.).
  Esta camada não muda. Apenas o conector muda.
"""

import json
import logging
from datetime import datetime
from hashlib import md5

import config
from conectores.canal_dry_run import CanalDryRun

_ARQ_FILA_EXEC = "fila_execucao_contato.json"
_ARQ_RESULTADOS = "resultados_contato.json"
_ARQ_SIMULADAS  = "respostas_simuladas_contato.json"
_ARQ_ESTADO     = "estado_integrador_canais.json"
_ARQ_HIST_EXEC  = "historico_execucao_contato.json"

_STATUS_PRONTO = "aguardando_integracao_canal"
_STATUS_GERADO = "resultado_gerado"

_PASTA_LOGS = config.PASTA_LOGS / "empresa"


# ─── Ponto de entrada público ─────────────────────────────────────────────────

def executar() -> dict:
    """
    Ponto de entrada para o orquestrador.
    Carrega o canal dry-run, processa execuções prontas, persiste resultados.
    Retorna resumo da integração.
    """
    ts  = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log = _configurar_log(ts)

    log.info("=" * 60)
    log.info(f"INTEGRADOR CANAIS [dry_run] — {ts}")
    log.info("=" * 60)

    estado     = _carregar_estado()
    execucoes  = carregar_execucoes_prontas()
    simuladas  = carregar_respostas_simuladas()
    resultados = _carregar_json(_ARQ_RESULTADOS, [])
    hist_exec  = _carregar_json(_ARQ_HIST_EXEC, [])

    canal = CanalDryRun(simuladas)

    n_disponiveis = sum(1 for r in simuladas if not r.get("consumido"))
    log.info(
        f"Execucoes prontas: {len(execucoes)} | "
        f"Respostas simuladas disponiveis: {n_disponiveis}"
    )

    n_gerados    = 0
    n_sem_resp   = 0

    for execucao in execucoes:
        exec_id      = execucao["id"]
        resultado_raw = canal.processar_execucao(execucao)

        if resultado_raw is None:
            log.info(f"  [sem_simulada] {exec_id} — sem resposta disponivel, aguardando")
            n_sem_resp += 1
            continue

        # Gerar resultado padronizado para resultados_contato.json
        resultado = gerar_resultado_contato(resultado_raw, execucao)
        resultados.append(resultado)

        # Marcar resposta simulada como consumida (in-place na lista compartilhada com canal)
        _marcar_simulada_consumida(simuladas, resultado_raw.get("_resposta_id"))

        # Atualizar status da execução in-place
        atualizar_execucao_apos_resultado(execucao)

        # Histórico de execução
        registrar_historico_integracao(hist_exec, execucao, resultado)

        log.info(
            f"  [resultado_gerado] {exec_id} | "
            f"{execucao.get('contraparte', '?')[:30]} | "
            f"tipo={resultado['tipo_resultado']}"
        )
        n_gerados += 1

    # Persistir tudo
    _salvar_json(_ARQ_RESULTADOS, resultados)
    _salvar_json(_ARQ_SIMULADAS, simuladas)
    _salvar_fila_exec(execucoes)
    _salvar_json(_ARQ_HIST_EXEC, hist_exec)

    estado = _atualizar_estado(estado, n_gerados, n_sem_resp, simuladas)
    salvar_estado_integrador(estado)

    log.info(f"Resultados gerados: {n_gerados} | Sem resposta simulada: {n_sem_resp}")
    log.info("=" * 60)

    return {
        "modo":                  "dry_run",
        "canal":                 "dry_run",
        "execucoes_lidas":       len(execucoes),
        "resultados_gerados":    n_gerados,
        "sem_resposta_simulada": n_sem_resp,
    }


# ─── Funções públicas ─────────────────────────────────────────────────────────

def carregar_execucoes_prontas() -> list:
    """Carrega execuções com pronto_para_integracao=True e status aguardando."""
    todas = _carregar_json(_ARQ_FILA_EXEC, [])
    return [
        e for e in todas
        if e.get("pronto_para_integracao") and e.get("status") == _STATUS_PRONTO
    ]


def carregar_respostas_simuladas() -> list:
    """Carrega todas as respostas simuladas (incluindo consumidas para preservar histórico)."""
    return _carregar_json(_ARQ_SIMULADAS, [])


def gerar_resultado_contato(resultado_raw: dict, execucao: dict) -> dict:
    """
    Monta o item padronizado para resultados_contato.json.
    Mesmo formato que resultados manuais — compatível com processador_resultados_contato.
    """
    agora  = datetime.now().isoformat(timespec="seconds")
    ts_id  = datetime.now().strftime("%Y%m%d%H%M%S")
    res_id = f"res_{execucao['id']}_{ts_id}"

    return {
        "id":                    res_id,
        "execucao_id":           execucao["id"],
        "handoff_id":            execucao.get("handoff_id", ""),
        "followup_id":           execucao.get("followup_id", ""),
        "oportunidade_id":       execucao.get("oportunidade_id", ""),
        "contraparte":           execucao.get("contraparte", ""),
        "canal":                 resultado_raw.get("canal", execucao.get("canal", "")),
        "tipo_resultado":        resultado_raw["tipo_resultado"],
        "resumo_resultado":      resultado_raw["resumo_resultado"],
        "detalhes":              resultado_raw.get("detalhes", ""),
        "proxima_acao_sugerida": resultado_raw.get("proxima_acao_sugerida", ""),
        "data_resultado":        resultado_raw.get("data_resultado") or agora,
        "status_aplicacao":      "pendente",
        "aplicado_em":           None,
        "origem":                resultado_raw.get("origem", "dry_run"),
    }


def registrar_historico_integracao(hist_exec: list, execucao: dict, resultado: dict) -> None:
    """Registra evento no historico_execucao_contato.json (in-place)."""
    agora = datetime.now().isoformat(timespec="seconds")
    chave = f"{execucao['id']}|resultado_gerado|{agora}"
    ev_id = "hev_int_" + md5(chave.encode()).hexdigest()[:10]

    hist_exec.append({
        "id":             ev_id,
        "execucao_id":    execucao["id"],
        "oportunidade_id": execucao.get("oportunidade_id", ""),
        "contraparte":    execucao.get("contraparte", ""),
        "evento":         "resultado_gerado_pelo_integrador",
        "descricao": (
            f"Resultado gerado via {resultado.get('origem', 'dry_run')} | "
            f"tipo={resultado['tipo_resultado']} | "
            f"resultado_id={resultado['id']}"
        ),
        "registrado_em":  agora,
    })


def atualizar_execucao_apos_resultado(execucao: dict) -> None:
    """Atualiza status da execução in-place após geração do resultado."""
    execucao["status"]                = _STATUS_GERADO
    execucao["resultado_gerado"]      = True
    execucao["pronto_para_integracao"] = False
    execucao["atualizado_em"]         = datetime.now().isoformat(timespec="seconds")


def salvar_estado_integrador(estado: dict) -> None:
    _salvar_json(_ARQ_ESTADO, estado)


# ─── Internos ─────────────────────────────────────────────────────────────────

def _marcar_simulada_consumida(simuladas: list, resposta_id: str | None) -> None:
    if not resposta_id:
        return
    agora = datetime.now().isoformat(timespec="seconds")
    for r in simuladas:
        if r["id"] == resposta_id:
            r["consumido"]    = True
            r["consumido_em"] = agora
            break


def _salvar_fila_exec(execucoes_atualizadas: list) -> None:
    """
    Persiste execuções atualizadas na fila completa.
    Carrega o arquivo completo, aplica updates por ID, salva.
    Preserva itens que não foram processados pelo integrador.
    """
    todas = _carregar_json(_ARQ_FILA_EXEC, [])
    idx   = {e["id"]: e for e in execucoes_atualizadas}
    for item in todas:
        if item["id"] in idx:
            item.update(idx[item["id"]])
    _salvar_json(_ARQ_FILA_EXEC, todas)


def _carregar_estado() -> dict:
    estado = _carregar_json(_ARQ_ESTADO, None)
    if estado is None:
        return {
            "ultima_execucao":       None,
            "modo":                  "dry_run",
            "execucoes_processadas": 0,
            "respostas_consumidas":  0,
            "contadores":            {},
            "ultimo_snapshot":       {},
        }
    return estado


def _atualizar_estado(estado: dict, n_gerados: int, n_sem_resp: int, simuladas: list) -> dict:
    agora = datetime.now().isoformat(timespec="seconds")
    estado["ultima_execucao"]       = agora
    estado["execucoes_processadas"] = estado.get("execucoes_processadas", 0) + n_gerados + n_sem_resp
    estado["respostas_consumidas"]  = estado.get("respostas_consumidas", 0) + n_gerados
    estado["contadores"] = {
        "total_simuladas":       len(simuladas),
        "simuladas_consumidas":  sum(1 for r in simuladas if r.get("consumido")),
        "simuladas_disponiveis": sum(1 for r in simuladas if not r.get("consumido")),
    }
    estado["ultimo_snapshot"] = {
        "gerados":       n_gerados,
        "sem_resposta":  n_sem_resp,
        "registrado_em": agora,
    }
    return estado


def _configurar_log(ts: str) -> logging.Logger:
    _PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    caminho = _PASTA_LOGS / f"integrador_canais_{ts}.log"
    nome    = f"integrador_canais_{ts}"
    log     = logging.getLogger(nome)
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        fh = logging.FileHandler(caminho, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        log.addHandler(sh)
    return log


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
