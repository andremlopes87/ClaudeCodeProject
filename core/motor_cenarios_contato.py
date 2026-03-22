"""
core/motor_cenarios_contato.py — Motor de cenários determinístico para dry-run.

Gera resultados simulados de contato com base em regras explícitas e seed fixa.
Sem aleatoriedade solta. Sem LLM. Sem heurística obscura.

Garantias:
  - Mesma execucao_id + seed_global → mesmo resultado sempre (reprodutível)
  - Resultado controlado por config_cenarios_contato.json (auditável)
  - Nenhum resultado fora das políticas configuradas

Fluxo:
  1. montar_contexto_execucao() — extrai canal, prioridade, categoria, tentativa
  2. _lookup_pesos()            — encontra regra mais específica que se aplica
  3. _hash_float()              — hash(execucao_id + seed) → float [0, 1)
  4. _selecionar_tipo()         — percorre pesos cumulativos até o float cair
  5. _montar_resultado()        — monta dict padronizado com templates
"""

import json
import logging
from datetime import datetime
from hashlib import md5
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_ARQ_CONFIG   = "config_cenarios_contato.json"
_ARQ_PIPELINE = "pipeline_comercial.json"

# ─── Templates de resultado ───────────────────────────────────────────────────

_TEMPLATES = {
    "sem_resposta": {
        "resumo":  "Ligação não atendida — {empresa} não atendeu o telefone",
        "detalhes": "Tentativa #{tentativa} realizada. Telefone chamou mas não foi atendido. Sem caixa postal.",
        "proxima":  "Tentar novamente em 2 dias em horário diferente",
    },
    "respondeu_interesse": {
        "resumo":  "{empresa} atendeu e demonstrou interesse pela solução proposta",
        "detalhes": "Responsável atendeu na tentativa #{tentativa}. Ouviu a proposta e pediu mais informações.",
        "proxima":  "Enviar apresentação de serviços e agendar visita ou videochamada",
    },
    "respondeu_sem_interesse": {
        "resumo":  "{empresa} atendeu mas não tem interesse no momento",
        "detalhes": "Responsável atendeu na tentativa #{tentativa}. Disse não ter interesse agora.",
        "proxima":  "Registrar como perdido. Pode reabordar em 3-6 meses se perfil mudar.",
    },
    "pediu_proposta": {
        "resumo":  "{empresa} quer proposta formal com valores e escopo",
        "detalhes": "Responsável atendeu na tentativa #{tentativa}. Demonstrou interesse e pediu proposta escrita.",
        "proxima":  "Preparar proposta comercial e enviar em até 3 dias úteis",
    },
    "pediu_retorno_futuro": {
        "resumo":  "Responsável pediu para ligar em outro momento",
        "detalhes": "Atendeu na tentativa #{tentativa} mas estava ocupado. Pediu retorno em dias.",
        "proxima":  "Ligar novamente em 5-7 dias no período da manhã",
    },
    "contato_invalido": {
        "resumo":  "Número de contato inválido ou fora de serviço",
        "detalhes": "Tentativa #{tentativa}: número não existe, fora de área ou sem sinal.",
        "proxima":  "Verificar dados de contato em outras fontes antes de nova tentativa",
    },
    "erro_execucao": {
        "resumo":  "Erro técnico na tentativa de contato",
        "detalhes": "Tentativa #{tentativa} falhou por problema técnico.",
        "proxima":  "Tentar novamente na próxima janela",
    },
}


# ─── API pública ──────────────────────────────────────────────────────────────

def carregar_config_cenarios() -> dict | None:
    """Carrega config_cenarios_contato.json. Retorna None se não existir."""
    caminho = config.PASTA_DADOS / _ARQ_CONFIG
    if not caminho.exists():
        logger.warning(f"config_cenarios_contato.json não encontrado — motor desativado")
        return None
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def carregar_pipeline_idx() -> dict:
    """Carrega pipeline_comercial.json e retorna índice por oportunidade_id."""
    caminho = config.PASTA_DADOS / _ARQ_PIPELINE
    if not caminho.exists():
        return {}
    with open(caminho, "r", encoding="utf-8") as f:
        pipeline = json.load(f)
    return {o["id"]: o for o in pipeline}


def decidir_resultado_para_execucao(
    execucao: dict,
    config_cenarios: dict,
    pipeline_idx: dict,
    hist_cenarios: list,
) -> dict | None:
    """
    Decide o resultado para uma execução via regras + seed determinística.
    Retorna dict padronizado compatível com canal_dry_run ou None se sem decisão.
    """
    contexto  = montar_contexto_execucao(execucao, pipeline_idx)
    pesos, regra_nome = _lookup_pesos(config_cenarios, contexto)

    if not pesos:
        registrar_decisao_cenario(hist_cenarios, execucao, contexto, None, "sem_decisao", regra_nome)
        return None

    seed   = config_cenarios.get("seed_global", "default")
    hf     = _hash_float(execucao["id"], seed)
    tipo   = _selecionar_tipo(pesos, hf)

    if not tipo:
        registrar_decisao_cenario(hist_cenarios, execucao, contexto, None, "sem_decisao", regra_nome)
        return None

    resultado = _montar_resultado(tipo, execucao, contexto, regra_nome)
    registrar_decisao_cenario(hist_cenarios, execucao, contexto, tipo, "motor_cenarios", regra_nome)
    return resultado


def montar_contexto_execucao(execucao: dict, pipeline_idx: dict) -> dict:
    """
    Extrai contexto relevante para seleção de regra.
    Usa pipeline para enrichment (prioridade, categoria, estagio).
    """
    opp_id  = execucao.get("oportunidade_id", "")
    opp     = pipeline_idx.get(opp_id, {})
    tentativa = execucao.get("tentativa_numero", 1)

    return {
        "canal":              execucao.get("canal", "telefone"),
        "prioridade":         opp.get("prioridade", "media") or "media",
        "categoria":          opp.get("categoria", ""),
        "estagio":            opp.get("estagio", "qualificado"),
        "status_operacional": opp.get("status_operacional", ""),
        "tentativa_numero":   tentativa,
        "oportunidade_id":    opp_id,
        "empresa":            execucao.get("contraparte", "empresa"),
    }


def calcular_resultado_deterministico(contexto: dict, config_cenarios: dict) -> str | None:
    """Calcula tipo_resultado a partir do contexto e config. Wrapper público."""
    pesos, _ = _lookup_pesos(config_cenarios, contexto)
    if not pesos:
        return None
    seed = config_cenarios.get("seed_global", "default")
    hf   = _hash_float(contexto.get("oportunidade_id", "?"), seed)
    return _selecionar_tipo(pesos, hf)


def registrar_decisao_cenario(
    hist_cenarios: list,
    execucao: dict,
    contexto: dict,
    tipo_resultado: str | None,
    origem_decisao: str,
    regra_aplicada: str = "",
) -> None:
    """Registra evento de decisão no historico_cenarios_contato.json (in-place)."""
    agora = datetime.now().isoformat(timespec="seconds")
    chave = f"{execucao['id']}|{origem_decisao}|{agora}"
    ev_id = "ev_cen_" + md5(chave.encode()).hexdigest()[:10]

    hist_cenarios.append({
        "id":                  ev_id,
        "execucao_id":         execucao.get("id", ""),
        "oportunidade_id":     execucao.get("oportunidade_id", ""),
        "empresa":             execucao.get("contraparte", ""),
        "regra_aplicada":      regra_aplicada,
        "contexto_usado": {
            "canal":      contexto.get("canal"),
            "prioridade": contexto.get("prioridade"),
            "tentativa":  contexto.get("tentativa_numero"),
            "estagio":    contexto.get("estagio"),
        },
        "tipo_resultado_gerado": tipo_resultado,
        "origem_decisao":      origem_decisao,
        "registrado_em":       agora,
    })


def validar_pesos_configurados(config_cenarios: dict) -> list[str]:
    """
    Valida que todos os blocos de pesos somam ~1.0.
    Retorna lista de avisos (vazia se tudo OK).
    """
    avisos = []
    _validar_bloco(config_cenarios.get("fallback", {}), "fallback", avisos)
    _validar_canal(config_cenarios.get("regras_por_canal", {}), avisos)
    return avisos


# ─── Internos ─────────────────────────────────────────────────────────────────

def _lookup_pesos(config_cenarios: dict, contexto: dict) -> tuple[dict, str]:
    """
    Navega a árvore de regras canal → prioridade → tentativa.
    Retorna (pesos, nome_regra). Pesos = {} se nenhuma regra se aplica.
    """
    canal     = contexto.get("canal", "telefone")
    prioridade = contexto.get("prioridade", "media")
    tentativa  = contexto.get("tentativa_numero", 1)

    regras_canal = config_cenarios.get("regras_por_canal", {})

    # Nível 1: canal
    canal_cfg = regras_canal.get(canal) or regras_canal.get("_default")
    if not canal_cfg:
        fb = config_cenarios.get("fallback", {})
        return (_pesos_limpos(fb), "fallback")

    nome_canal = canal if canal in regras_canal else "_default"

    # Nível 2: prioridade
    prio_cfg = canal_cfg.get(prioridade) or canal_cfg.get("_default")
    if not prio_cfg:
        fb = config_cenarios.get("fallback", {})
        return (_pesos_limpos(fb), "fallback")

    nome_prio = prioridade if prioridade in canal_cfg else "_default"

    # Nível 3: tentativa
    tent_key = str(tentativa)
    if tent_key in prio_cfg:
        bloco = prio_cfg[tent_key]
        nome  = f"{nome_canal}/{nome_prio}/{tent_key}"
    elif tentativa >= 3 and "3+" in prio_cfg:
        bloco = prio_cfg["3+"]
        nome  = f"{nome_canal}/{nome_prio}/3+"
    elif "_default" in prio_cfg:
        bloco = prio_cfg["_default"]
        nome  = f"{nome_canal}/{nome_prio}/_default"
    else:
        # prio_cfg itself might be the pesos dict (no tentativa level)
        bloco = prio_cfg
        nome  = f"{nome_canal}/{nome_prio}"

    return (_pesos_limpos(bloco), nome)


def _pesos_limpos(bloco: dict) -> dict:
    """Remove chaves de metadados (_descricao etc) deixando só os pesos numéricos."""
    return {k: v for k, v in bloco.items() if not k.startswith("_") and isinstance(v, (int, float))}


def _hash_float(execucao_id: str, seed: str) -> float:
    """Gera float determinístico [0, 1) a partir de execucao_id + seed."""
    h = md5(f"{execucao_id}:{seed}".encode()).hexdigest()
    return int(h, 16) / (16 ** 32)


def _selecionar_tipo(pesos: dict, hash_float: float) -> str | None:
    """Seleciona tipo_resultado via distribuição cumulativa dos pesos."""
    if not pesos:
        return None
    cumul = 0.0
    for tipo, peso in pesos.items():
        cumul += peso
        if hash_float < cumul:
            return tipo
    # Segurança: retorna o último tipo se float >= soma dos pesos (rounding)
    return list(pesos.keys())[-1]


def _montar_resultado(tipo: str, execucao: dict, contexto: dict, regra_nome: str) -> dict:
    """Monta dict padronizado compatível com o integrador de canais."""
    agora    = datetime.now().isoformat(timespec="seconds")
    empresa  = execucao.get("contraparte", "empresa")
    tentativa = contexto.get("tentativa_numero", 1)
    template = _TEMPLATES.get(tipo, _TEMPLATES["sem_resposta"])

    resumo  = template["resumo"].format(empresa=empresa, tentativa=tentativa)
    detalhes = template["detalhes"].format(empresa=empresa, tentativa=tentativa)
    proxima  = template["proxima"].format(empresa=empresa, tentativa=tentativa)

    return {
        "tipo_resultado":        tipo,
        "resumo_resultado":      resumo,
        "detalhes":              detalhes,
        "proxima_acao_sugerida": proxima,
        "data_resultado":        agora,
        "canal":                 contexto.get("canal", execucao.get("canal", "telefone")),
        "origem":                "motor_cenarios",
        "_origem":               "motor_cenarios",
        "_regra":                regra_nome,
        "_resposta_id":          None,
    }


def _validar_bloco(bloco: dict, nome: str, avisos: list) -> None:
    pesos = _pesos_limpos(bloco)
    if not pesos:
        return
    total = sum(pesos.values())
    if abs(total - 1.0) > 0.01:
        avisos.append(f"Bloco '{nome}': pesos somam {total:.4f} (esperado 1.0)")


def _validar_canal(regras_canal: dict, avisos: list) -> None:
    for canal, canal_cfg in regras_canal.items():
        if canal == "_default":
            _validar_bloco(canal_cfg, f"canal/{canal}", avisos)
            continue
        for prio, prio_cfg in canal_cfg.items():
            if prio == "_default":
                _validar_bloco(prio_cfg, f"canal/{canal}/{prio}", avisos)
                continue
            for tent, bloco in prio_cfg.items():
                if isinstance(bloco, dict):
                    _validar_bloco(bloco, f"canal/{canal}/{prio}/{tent}", avisos)
