"""
core/planos_entrega.py

Carrega planos de execução por oferta e os converte em itens de checklist
enriquecidos (responsavel, duracao, entregavel, ferramentas).

Suporta:
- Adaptação básica por contexto do cliente (sem LLM): pula etapas já cumpridas
- Adaptação via LLM: chama llm_router.analisar() para pular etapas quando
  o cliente já tem o recurso (WhatsApp Business, Google Meu Negócio, etc.)
- Cálculo de métricas: tempo real vs estimado, gargalos, progresso
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQUIVO = config.PASTA_DADOS / "planos_execucao.json"
_cache: dict | None = None


# ─── Carregamento ─────────────────────────────────────────────────────────────

def carregar_planos() -> dict:
    """Carrega planos de execução do JSON. Cache em memória."""
    global _cache
    if _cache is None:
        if _ARQUIVO.exists():
            with open(_ARQUIVO, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        else:
            log.warning(f"[planos_entrega] {_ARQUIVO} não encontrado — planos vazios")
            _cache = {}
    return _cache


def obter_plano(oferta_id: str) -> dict | None:
    """Retorna o plano de execução de uma oferta ou None."""
    return carregar_planos().get(oferta_id)


# ─── Conversão de etapas para itens de checklist ──────────────────────────────

def etapas_para_itens_checklist(
    oferta_id: str,
    contexto_cliente: dict | None = None,
    usar_llm: bool = False,
) -> list:
    """
    Converte etapas do plano de execução em itens de checklist enriquecidos.

    Campos por item:
        id, titulo, descricao, ordem, responsavel, tipo,
        duracao_estimada_horas, ferramentas, insumos_necessarios,
        entregavel, obrigatorio, status, depende_de,
        observacoes, evidencias, iniciado_em, concluido_em,
        tempo_real_horas, atualizado_em

    Adaptação por contexto_cliente:
        tem_whatsapp_business  → pula etapas de "configuracao" que usem WhatsApp Business
        tem_google_meu_negocio → pula etapas de "configuracao" que usem Google Business
    """
    plano = obter_plano(oferta_id)
    if not plano:
        return []

    etapas = plano.get("etapas", [])
    ordens_a_pular: set = set()

    # Adaptação sem LLM — baseada em flags do contexto_cliente
    if contexto_cliente:
        ordens_a_pular = _calcular_etapas_a_pular(etapas, contexto_cliente)

    # Adaptação com LLM — substitui/complementa a anterior
    if usar_llm and contexto_cliente:
        try:
            ordens_llm = _adaptar_com_llm(oferta_id, plano, contexto_cliente)
            if ordens_llm:
                ordens_a_pular = ordens_llm
        except Exception as exc:
            log.warning(f"[planos_entrega] adaptação LLM falhou ({exc}) — usando fallback básico")

    agora = datetime.now().isoformat(timespec="seconds")
    itens = []
    for etapa in etapas:
        ordem = etapa.get("ordem", 0)
        pulada = ordem in ordens_a_pular

        if pulada:
            status = "pulada"
            obs = "Etapa pulada — cliente já tem este recurso configurado."
        elif etapa.get("responsavel", "vetor") == "cliente":
            status = "aguardando_cliente"
            obs = ""
        else:
            status = "pendente"
            obs = ""

        item = {
            "id":                     f"et_{oferta_id}_{ordem:02d}",
            "titulo":                 etapa.get("nome", f"Etapa {ordem}"),
            "descricao":              etapa.get("descricao", ""),
            "ordem":                  ordem,
            "responsavel":            etapa.get("responsavel", "vetor"),
            "tipo":                   etapa.get("tipo", ""),
            "duracao_estimada_horas": etapa.get("duracao_estimada_horas", 0),
            "ferramentas":            etapa.get("ferramentas", []),
            "insumos_necessarios":    etapa.get("insumos_necessarios", []),
            "entregavel":             etapa.get("entregavel", ""),
            "obrigatorio":            True,
            "status":                 status,
            "depende_de":             f"et_{oferta_id}_{(ordem - 1):02d}" if ordem > 1 else None,
            "observacoes":            obs,
            "evidencias":             [],
            "iniciado_em":            None,
            "concluido_em":           None,
            "tempo_real_horas":       None,
            "atualizado_em":          agora,
        }
        itens.append(item)

    return itens


def _calcular_etapas_a_pular(etapas: list, contexto_cliente: dict) -> set:
    """
    Retorna set de ordens de etapas a pular com base em flags do contexto.
    Aplica heurística conservadora: só pula etapas de configuração onde a
    ferramenta já está presente no contexto.
    """
    pular = set()
    tem_wpp  = contexto_cliente.get("tem_whatsapp_business", False)
    tem_gmn  = contexto_cliente.get("tem_google_meu_negocio", False)

    for etapa in etapas:
        if etapa.get("tipo") != "configuracao":
            continue
        ferramentas = [f.lower() for f in etapa.get("ferramentas", [])]
        if tem_wpp and any("whatsapp business" in f for f in ferramentas):
            pular.add(etapa["ordem"])
        if tem_gmn and any("google business" in f or "google meu negócio" in f for f in ferramentas):
            pular.add(etapa["ordem"])

    return pular


def _adaptar_com_llm(oferta_id: str, plano: dict, contexto_cliente: dict) -> set:
    """
    Chama llm_router.analisar() para identificar etapas a pular.
    Retorna set de ordens. Raises em caso de erro (caller trata).
    """
    import re
    from core.llm_router import LLMRouter
    router = LLMRouter()

    etapas_resumo = [
        {
            "ordem":       e["ordem"],
            "nome":        e["nome"],
            "tipo":        e.get("tipo", ""),
            "ferramentas": e.get("ferramentas", []),
        }
        for e in plano.get("etapas", [])
    ]

    resultado = router.analisar(
        agente="agente_operacao_entrega",
        tarefa="adaptar_plano_execucao",
        contexto={
            "plano_nome":       plano.get("nome", oferta_id),
            "etapas":           etapas_resumo,
            "contexto_cliente": contexto_cliente,
            "instrucao": (
                "Analise o plano de execução e o contexto do cliente. "
                "Liste os números de ORDEM das etapas que podem ser puladas "
                "porque o cliente já tem o recurso ou configuração necessária. "
                "Responda APENAS com JSON no formato: {\"etapas_a_pular\": [1, 2]}"
            ),
        },
    )

    # Tentar extrair JSON da resposta
    texto = resultado if isinstance(resultado, str) else json.dumps(resultado)
    match = re.search(r'\{[^}]*"etapas_a_pular"[^}]*\}', texto)
    if match:
        parsed = json.loads(match.group())
        return set(parsed.get("etapas_a_pular", []))

    return set()


# ─── Métricas ─────────────────────────────────────────────────────────────────

def calcular_metricas_checklist(checklist: dict) -> dict:
    """
    Calcula métricas de execução de um checklist baseado em plano de execução.

    Retorna:
        total_etapas, concluidas, puladas, pendentes,
        percentual_conclusao, horas_estimadas, horas_reais,
        desvio_horas, etapas_atrasadas, gargalo_tipo
    """
    itens = checklist.get("itens", [])
    if not itens:
        return {}

    total      = len(itens)
    concluidas = sum(1 for i in itens if i.get("status") == "concluido")
    puladas    = sum(1 for i in itens if i.get("status") == "pulada")
    pendentes  = sum(1 for i in itens if i.get("status") == "pendente")
    em_andamento = sum(1 for i in itens if i.get("status") == "em_andamento")

    ativos = total - puladas
    pct = round((concluidas / ativos * 100) if ativos > 0 else 0, 1)

    h_est  = sum(i.get("duracao_estimada_horas", 0) or 0 for i in itens if i.get("status") != "pulada")
    h_real = sum(i.get("tempo_real_horas", 0) or 0 for i in itens if i.get("tempo_real_horas"))
    desvio = round(h_real - h_est, 2) if h_real else None

    # Gargalo: tipo de etapa com mais horas acumuladas (excluindo puladas/concluídas)
    from collections import Counter
    tipo_pendente = Counter(
        i.get("tipo", "") for i in itens
        if i.get("status") not in ("concluido", "pulada") and i.get("tipo")
    )
    gargalo = tipo_pendente.most_common(1)[0][0] if tipo_pendente else None

    return {
        "total_etapas":       total,
        "concluidas":         concluidas,
        "puladas":            puladas,
        "pendentes":          pendentes,
        "em_andamento":       em_andamento,
        "percentual_conclusao": pct,
        "horas_estimadas":    h_est,
        "horas_reais":        h_real,
        "desvio_horas":       desvio,
        "gargalo_tipo":       gargalo,
    }


def obter_metricas_globais(checklists: list) -> dict:
    """
    Agrega métricas de todos os checklists com plano de execução.
    Útil para painel de acompanhamento.

    Retorna:
        total_entregas, concluidas, em_andamento, media_percentual,
        horas_estimadas_total, horas_reais_total, desvio_medio,
        gargalos_mais_comuns (top 3 tipos)
    """
    from collections import Counter

    metricas_lista = []
    gargalos = Counter()

    for ck in checklists:
        # Só checklists com etapas enriquecidas (campo "ordem" presente em algum item)
        itens = ck.get("itens", [])
        if not itens or "ordem" not in itens[0]:
            continue
        m = calcular_metricas_checklist(ck)
        if not m:
            continue
        metricas_lista.append(m)
        if m.get("gargalo_tipo"):
            gargalos[m["gargalo_tipo"]] += 1

    if not metricas_lista:
        return {}

    n = len(metricas_lista)
    return {
        "total_entregas":       n,
        "media_percentual":     round(sum(m["percentual_conclusao"] for m in metricas_lista) / n, 1),
        "horas_estimadas_total": sum(m["horas_estimadas"] for m in metricas_lista),
        "horas_reais_total":    sum(m["horas_reais"] for m in metricas_lista),
        "desvio_medio":         round(
            sum(m["desvio_horas"] for m in metricas_lista if m["desvio_horas"] is not None)
            / max(1, sum(1 for m in metricas_lista if m["desvio_horas"] is not None)),
            2,
        ) if any(m["desvio_horas"] is not None for m in metricas_lista) else None,
        "gargalos_mais_comuns": [tipo for tipo, _ in gargalos.most_common(3)],
    }
