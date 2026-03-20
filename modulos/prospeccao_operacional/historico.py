"""
agents/prospeccao/historico.py — Memória persistente da prospecção.

Responsabilidades:
- Manter registro histórico de todas as empresas encontradas ao longo do tempo
- Detectar mudanças entre execuções (nova empresa, classificação mudou, contato ganho/perdido etc.)
- Calcular status interno de cada empresa
- Gerar fila de revisão ordenada por relevância
- Gerar resumo da execução atual

empresa_id:
  Estável entre execuções. Usa osm_{osm_id} quando disponível (OSM IDs são persistentes).
  Fallback: hash de categoria+nome+cidade para casos sem osm_id.

Status interno:
  novo                → apareceu pela primeira vez nesta execução
  pronto_para_abordagem → abordavel + classificação útil (não novo)
  revisar             → mudança relevante detectada, ou empresa sumiu entre execuções
  baixa_prioridade    → digital_basica, analogica sem contato, ou sem mudanças relevantes
  descartar           → pouco_util ou dados insuficientes
"""

import hashlib
import logging

logger = logging.getLogger(__name__)

# Ordem numérica para sorting (menor = mais urgente na fila)
_ORDEM_STATUS = {
    "novo": 0,
    "pronto_para_abordagem": 1,
    "revisar": 2,
    "baixa_prioridade": 3,
    "descartar": 4,
}

_ORDEM_PRIORIDADE = {"alta": 0, "media": 1, "baixa": 2, "nula": 3}

# Tipos de mudança que disparam status "revisar"
_MUDANCAS_RELEVANTES = {"classificacao_mudou", "ganhou_contato", "perdeu_contato"}


# ---------------------------------------------------------------------------
# ID estável
# ---------------------------------------------------------------------------


def gerar_empresa_id(empresa: dict) -> str:
    """
    Gera identificador estável para a empresa.

    Usa osm_id quando disponível (identificador permanente do OpenStreetMap).
    Fallback para hash de categoria+nome+cidade quando osm_id não está presente.
    """
    osm_id = empresa.get("osm_id")
    if osm_id:
        return f"osm_{osm_id}"

    chave = (
        f"{empresa.get('categoria_id', '')}|"
        f"{_normalizar(empresa.get('nome', ''))}|"
        f"{_normalizar(empresa.get('cidade', ''))}"
    )
    return f"hash_{hashlib.md5(chave.encode('utf-8')).hexdigest()[:12]}"


def _normalizar(texto: str) -> str:
    return texto.lower().strip() if texto else ""


# ---------------------------------------------------------------------------
# Atualização do histórico
# ---------------------------------------------------------------------------


def atualizar_historico(
    historico_anterior: dict,
    empresas_execucao: list,
    timestamp: str,
    cidade: str = "",
) -> tuple:
    """
    Atualiza o histórico com os dados da execução atual.

    Parâmetros:
        historico_anterior: dict {empresa_id → entrada} carregado do arquivo anterior
        empresas_execucao: lista de todas as empresas encontradas nesta execução
        timestamp: ISO timestamp da execução atual
        cidade: cidade configurada (para enriquecer entradas novas)

    Retorna:
        (historico_atualizado: dict, mudancas: list, stats: dict)
    """
    historico = {k: dict(v) for k, v in historico_anterior.items()}  # cópia rasa
    mudancas = []

    # Marcar todas as entradas anteriores como não encontradas até confirmar
    for entrada in historico.values():
        entrada["encontrada_execucao_atual"] = False

    # Processar cada empresa da execução atual
    ids_execucao = set()
    for empresa in empresas_execucao:
        empresa_id = gerar_empresa_id(empresa)
        ids_execucao.add(empresa_id)

        if empresa_id in historico:
            entrada_anterior = historico[empresa_id]
            mudancas_empresa = _detectar_mudancas(entrada_anterior, empresa)
            historico[empresa_id] = _atualizar_entrada(
                entrada_anterior, empresa, timestamp, mudancas_empresa
            )
            for m in mudancas_empresa:
                mudancas.append({
                    "empresa_id": empresa_id,
                    "nome": empresa.get("nome", ""),
                    **m,
                })
        else:
            historico[empresa_id] = _nova_entrada(empresa_id, empresa, timestamp, cidade)
            mudancas.append({
                "tipo": "nova_empresa",
                "empresa_id": empresa_id,
                "nome": empresa.get("nome", ""),
                "descricao": "Empresa encontrada pela primeira vez",
            })

    # Detectar empresas que sumiram (estavam antes, não vieram agora)
    for empresa_id, entrada in historico.items():
        if empresa_id not in ids_execucao:
            classificacao = entrada.get("classificacao_comercial_atual", "pouco_util")
            if classificacao not in ("pouco_util",) and entrada.get("vezes_encontrada", 0) > 0:
                mudancas.append({
                    "tipo": "empresa_sumiu",
                    "empresa_id": empresa_id,
                    "nome": entrada.get("nome", ""),
                    "descricao": "Empresa não encontrada nesta execução (estava presente antes)",
                })

    # Recalcular status_interno para todas as entradas
    for empresa_id, entrada in historico.items():
        status, motivo = _calcular_status_interno(entrada)
        entrada["status_interno"] = status
        entrada["motivo_status_interno"] = motivo

    stats = _calcular_stats(historico, mudancas, len(empresas_execucao))
    return historico, mudancas, stats


# ---------------------------------------------------------------------------
# Nova entrada
# ---------------------------------------------------------------------------


def _nova_entrada(empresa_id: str, empresa: dict, timestamp: str, cidade: str) -> dict:
    """Cria nova entrada no histórico para empresa vista pela primeira vez."""
    return {
        "empresa_id": empresa_id,
        "nome": empresa.get("nome", "(sem nome registrado)"),
        "categoria_id": empresa.get("categoria_id", ""),
        "categoria_nome": empresa.get("categoria_nome", ""),
        "cidade": empresa.get("cidade") or cidade,
        "osm_id": empresa.get("osm_id"),
        "primeira_vez_encontrada": timestamp,
        "ultima_vez_encontrada": timestamp,
        "vezes_encontrada": 1,
        "encontrada_execucao_atual": True,
        "classificacao_comercial_atual": empresa.get("classificacao_comercial", "pouco_util"),
        "prioridade_abordagem_atual": empresa.get("prioridade_abordagem", "nula"),
        "abordavel_agora": empresa.get("abordavel_agora", False),
        "canal_abordagem_sugerido": empresa.get("canal_abordagem_sugerido"),
        "contato_principal": empresa.get("contato_principal"),
        "score_presenca_digital_atual": empresa.get("score_presenca_digital", 0),
        "score_prontidao_ia_atual": empresa.get("score_prontidao_ia", 0),
        "status_interno": "novo",
        "motivo_status_interno": "Empresa encontrada pela primeira vez nesta execução.",
        "mudancas_detectadas": [],
    }


# ---------------------------------------------------------------------------
# Atualização de entrada existente
# ---------------------------------------------------------------------------


def _atualizar_entrada(
    anterior: dict, empresa: dict, timestamp: str, mudancas_detectadas: list
) -> dict:
    """Atualiza campos de uma entrada existente com dados da execução atual."""
    return {
        **anterior,
        "nome": empresa.get("nome", anterior.get("nome", "")),
        "ultima_vez_encontrada": timestamp,
        "vezes_encontrada": anterior.get("vezes_encontrada", 0) + 1,
        "encontrada_execucao_atual": True,
        "classificacao_comercial_atual": empresa.get(
            "classificacao_comercial", anterior.get("classificacao_comercial_atual")
        ),
        "prioridade_abordagem_atual": empresa.get(
            "prioridade_abordagem", anterior.get("prioridade_abordagem_atual")
        ),
        "abordavel_agora": empresa.get("abordavel_agora", False),
        "canal_abordagem_sugerido": empresa.get("canal_abordagem_sugerido"),
        "contato_principal": empresa.get("contato_principal"),
        "score_presenca_digital_atual": empresa.get("score_presenca_digital", 0),
        "score_prontidao_ia_atual": empresa.get("score_prontidao_ia", 0),
        "mudancas_detectadas": mudancas_detectadas,
    }


# ---------------------------------------------------------------------------
# Detecção de mudanças
# ---------------------------------------------------------------------------


def _detectar_mudancas(anterior: dict, empresa_atual: dict) -> list:
    """
    Compara entrada anterior com dados atuais e retorna lista de mudanças detectadas.
    Retorna lista vazia se nada mudou.
    """
    mudancas = []

    class_ant = anterior.get("classificacao_comercial_atual")
    class_atu = empresa_atual.get("classificacao_comercial")
    if class_ant and class_atu and class_ant != class_atu:
        mudancas.append({
            "tipo": "classificacao_mudou",
            "de": class_ant,
            "para": class_atu,
            "descricao": f"Classificação: {class_ant} → {class_atu}",
        })

    prio_ant = anterior.get("prioridade_abordagem_atual")
    prio_atu = empresa_atual.get("prioridade_abordagem")
    if prio_ant and prio_atu and prio_ant != prio_atu:
        mudancas.append({
            "tipo": "prioridade_mudou",
            "de": prio_ant,
            "para": prio_atu,
            "descricao": f"Prioridade: {prio_ant} → {prio_atu}",
        })

    abord_ant = anterior.get("abordavel_agora", False)
    abord_atu = empresa_atual.get("abordavel_agora", False)
    if abord_ant != abord_atu:
        if abord_atu:
            mudancas.append({
                "tipo": "ganhou_contato",
                "descricao": "Passou a ter canal de contato direto identificado",
            })
        else:
            mudancas.append({
                "tipo": "perdeu_contato",
                "descricao": "Perdeu canal de contato direto nos dados públicos",
            })

    canal_ant = anterior.get("canal_abordagem_sugerido")
    canal_atu = empresa_atual.get("canal_abordagem_sugerido")
    if canal_ant and canal_atu and canal_ant != canal_atu:
        mudancas.append({
            "tipo": "canal_mudou",
            "de": canal_ant,
            "para": canal_atu,
            "descricao": f"Canal: {canal_ant} → {canal_atu}",
        })

    return mudancas


# ---------------------------------------------------------------------------
# Status interno
# ---------------------------------------------------------------------------


def _calcular_status_interno(entrada: dict) -> tuple:
    """
    Determina o status interno e motivo de uma entrada do histórico.

    Ordem de avaliação:
    1. Primeiro aparecimento → novo
    2. Não encontrada nesta execução → revisar (se era útil antes)
    3. Classificação inútil → descartar
    4. Mudança relevante detectada → revisar
    5. Abordável e priorizada → pronto_para_abordagem
    6. Qualquer outro caso → baixa_prioridade
    """
    vezes = entrada.get("vezes_encontrada", 1)
    encontrada = entrada.get("encontrada_execucao_atual", True)
    classificacao = entrada.get("classificacao_comercial_atual", "pouco_util")
    abordavel = entrada.get("abordavel_agora", False)
    mudancas = entrada.get("mudancas_detectadas", [])

    if vezes == 1 and encontrada:
        return "novo", "Empresa encontrada pela primeira vez. Ainda não consolidada no histórico."

    if not encontrada:
        return "revisar", (
            "Empresa não encontrada na última execução. "
            "Verificar se ainda existe ou se os dados públicos mudaram."
        )

    if classificacao == "pouco_util":
        return "descartar", "Dados insuficientes para abordagem comercial nos registros públicos."

    tipos_mudanca = {m.get("tipo") for m in mudancas}
    if tipos_mudanca & _MUDANCAS_RELEVANTES:
        descricao_mudancas = ", ".join(sorted(tipos_mudanca & _MUDANCAS_RELEVANTES))
        return "revisar", f"Mudança relevante detectada nesta execução: {descricao_mudancas}."

    if abordavel and classificacao in ("semi_digital_prioritaria", "analogica"):
        return (
            "pronto_para_abordagem",
            "Canal de contato direto identificado e perfil comercial adequado para abordagem.",
        )

    return "baixa_prioridade", (
        "Perfil de baixa oportunidade imediata ou sem canal de contato direto identificado."
    )


# ---------------------------------------------------------------------------
# Fila de revisão
# ---------------------------------------------------------------------------


def gerar_fila_revisao(historico: dict) -> list:
    """
    Gera fila de revisão com os leads mais relevantes da execução atual.

    Inclui:
    - Novos leads com classificação boa (semi_digital ou analogica)
    - Leads prontos para abordagem
    - Leads com mudanças relevantes (revisar)

    Exclui baixa_prioridade e descartar da fila ativa.
    """
    fila = []

    for entrada in historico.values():
        status = entrada.get("status_interno")
        classificacao = entrada.get("classificacao_comercial_atual", "pouco_util")

        incluir = False
        if status == "pronto_para_abordagem":
            incluir = True
        elif status == "novo" and classificacao in ("semi_digital_prioritaria", "analogica"):
            incluir = True
        elif status == "revisar":
            incluir = True

        if incluir:
            fila.append(dict(entrada))

    fila.sort(key=lambda e: (
        _ORDEM_STATUS.get(e.get("status_interno"), 99),
        _ORDEM_PRIORIDADE.get(e.get("prioridade_abordagem_atual", "nula"), 3),
        -e.get("score_prontidao_ia_atual", 0),
    ))

    return fila


# ---------------------------------------------------------------------------
# Resumo da execução
# ---------------------------------------------------------------------------


def gerar_resumo_execucao(
    historico_anterior: dict,
    historico_atual: dict,
    mudancas: list,
    stats: dict,
    timestamp: str,
) -> dict:
    """Gera resumo estruturado da execução atual para o arquivo resumo_execucao.json."""
    contagem_status: dict = {}
    for entrada in historico_atual.values():
        s = entrada.get("status_interno", "desconhecido")
        contagem_status[s] = contagem_status.get(s, 0) + 1

    contagem_mudancas: dict = {}
    for m in mudancas:
        t = m.get("tipo", "desconhecido")
        contagem_mudancas[t] = contagem_mudancas.get(t, 0) + 1

    empresas_novas = [m for m in mudancas if m.get("tipo") == "nova_empresa"]
    empresas_sumiram = [m for m in mudancas if m.get("tipo") == "empresa_sumiu"]
    mudancas_relevantes = [
        m for m in mudancas
        if m.get("tipo") in _MUDANCAS_RELEVANTES
    ]

    return {
        "timestamp_execucao": timestamp,
        "total_no_historico": len(historico_atual),
        "total_encontradas_execucao_atual": stats.get("total_execucao", 0),
        "empresas_novas_nesta_execucao": len(empresas_novas),
        "empresas_que_sumiram": len(empresas_sumiram),
        "total_mudancas_detectadas": len(mudancas),
        "mudancas_por_tipo": contagem_mudancas,
        "contagem_por_status_interno": contagem_status,
        "detalhe_mudancas_relevantes": [
            {
                "nome": m.get("nome"),
                "tipo": m.get("tipo"),
                "descricao": m.get("descricao"),
                "empresa_id": m.get("empresa_id"),
            }
            for m in mudancas_relevantes
        ],
        "detalhe_empresas_novas": [
            {"nome": m.get("nome"), "empresa_id": m.get("empresa_id")}
            for m in empresas_novas
        ],
        "detalhe_empresas_sumiram": [
            {"nome": m.get("nome"), "empresa_id": m.get("empresa_id")}
            for m in empresas_sumiram
        ],
    }


# ---------------------------------------------------------------------------
# Stats internas
# ---------------------------------------------------------------------------


def _calcular_stats(historico: dict, mudancas: list, total_execucao: int) -> dict:
    contagem_status: dict = {}
    for entrada in historico.values():
        s = entrada.get("status_interno", "desconhecido")
        contagem_status[s] = contagem_status.get(s, 0) + 1

    return {
        "total_execucao": total_execucao,
        "total_historico": len(historico),
        "por_status": contagem_status,
        "total_mudancas": len(mudancas),
    }
