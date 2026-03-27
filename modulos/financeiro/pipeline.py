"""
modulos/financeiro/pipeline.py — Pipeline de análise financeira reutilizável.

Separa o registro de dados (responsabilidade de quem chama)
da análise (posição de caixa → alertas → resumo → previsão → riscos).

Tanto main_financeiro.py quanto agente_financeiro.py usam esta função.
Não há duplicação de lógica entre eles.
"""

import hashlib
import json
import logging
from datetime import datetime

import config
from core.persistencia import salvar_json_fixo
from modulos.financeiro.classificador_eventos import classificar_eventos
from modulos.financeiro.analisador_caixa import analisar_caixa
from modulos.financeiro.gerador_alertas import gerar_alertas
from modulos.financeiro.resumo_financeiro import gerar_resumo
from modulos.financeiro.previsao_caixa import gerar_previsao
from modulos.financeiro.registrador_eventos import carregar_eventos
from modulos.financeiro.contas_a_receber import carregar_com_status_efetivo as receber_efetivo
from modulos.financeiro.contas_a_pagar import carregar_com_status_efetivo as pagar_efetivo

logger = logging.getLogger(__name__)


def executar_analise_financeira(
    eventos: list = None,
    contas_a_receber: list = None,
    contas_a_pagar: list = None,
    salvar: bool = True,
    ts: str = None,
) -> dict:
    """
    Executa análise financeira completa.

    Se eventos/contas forem None, carrega dos arquivos com status efetivo.
    Se salvar=True, persiste todos os JSONs de saída (fixo + timestamped).

    Retorna dict com todos os resultados:
      eventos, contas_a_receber, contas_a_pagar,
      posicao, alertas, decisoes, resumo, previsao, fila_riscos
    """
    if ts is None:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")

    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)

    # ── Carregar dados se não fornecidos ───────────────────────────────────
    if eventos is None:
        eventos = carregar_eventos()
    if contas_a_receber is None:
        contas_a_receber = receber_efetivo()
    if contas_a_pagar is None:
        contas_a_pagar = pagar_efetivo()

    # ── Análise ────────────────────────────────────────────────────────────
    eventos  = classificar_eventos(eventos)
    posicao  = analisar_caixa(eventos, contas_a_receber=contas_a_receber, contas_a_pagar=contas_a_pagar)
    alertas, decisoes = gerar_alertas(eventos, posicao, contas_a_receber=contas_a_receber, contas_a_pagar=contas_a_pagar)
    resumo   = gerar_resumo(posicao, contas_a_receber, contas_a_pagar, alertas, decisoes)
    previsao, fila_riscos = gerar_previsao(
        saldo_base=posicao["saldo_atual_estimado"],
        contas_a_receber=contas_a_receber,
        contas_a_pagar=contas_a_pagar,
        eventos=eventos,
    )

    # IDs determinísticos nos riscos (não têm ID nativo)
    for risco in fila_riscos:
        if "id" not in risco:
            risco["id"] = _id_risco(risco)

    # ── Persistência ───────────────────────────────────────────────────────
    if salvar:
        salvar_json_fixo(eventos,     "eventos_financeiros.json")
        salvar_json_fixo(posicao,     "posicao_caixa.json")
        salvar_json_fixo(alertas,     "fila_alertas_financeiros.json")
        salvar_json_fixo(decisoes,    "fila_decisoes_financeiras.json")
        salvar_json_fixo(resumo,      "resumo_financeiro_operacional.json")
        salvar_json_fixo(previsao,    "previsao_caixa.json")
        salvar_json_fixo(fila_riscos, "fila_riscos_financeiros.json")
        _salvar_ts(eventos,     f"eventos_financeiros_{ts}.json")
        _salvar_ts(posicao,     f"posicao_caixa_{ts}.json")
        _salvar_ts(alertas,     f"fila_alertas_financeiros_{ts}.json")
        _salvar_ts(decisoes,    f"fila_decisoes_financeiras_{ts}.json")
        _salvar_ts(resumo,      f"resumo_financeiro_operacional_{ts}.json")
        _salvar_ts(previsao,    f"previsao_caixa_{ts}.json")
        _salvar_ts(fila_riscos, f"fila_riscos_financeiros_{ts}.json")

    logger.info(
        f"Pipeline financeiro concluido: saldo={posicao['saldo_atual_estimado']:.2f} "
        f"alertas={len(alertas)} riscos={len(fila_riscos)}"
    )

    return {
        "eventos":          eventos,
        "contas_a_receber": contas_a_receber,
        "contas_a_pagar":   contas_a_pagar,
        "posicao":          posicao,
        "alertas":          alertas,
        "decisoes":         decisoes,
        "resumo":           resumo,
        "previsao":         previsao,
        "fila_riscos":      fila_riscos,
    }


# ─── Internos ───────────────────────────────────────────────────────────────

def _id_risco(risco: dict) -> str:
    """ID determinístico para risco: hash de tipo+descricao."""
    chave = f"{risco.get('tipo', '')}|{risco.get('descricao', '')}"
    return "risco_" + hashlib.md5(chave.encode()).hexdigest()[:12]


def _salvar_ts(dados, nome_arquivo: str) -> None:
    """Salva snapshot com timestamp em PASTA_DADOS."""
    import os
    caminho = config.PASTA_DADOS / nome_arquivo
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conteudo = json.dumps(dados, ensure_ascii=False, indent=2)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)
    n = len(dados) if isinstance(dados, list) else 1
    logger.info(f"Snapshot salvo: {caminho} ({n} registros)")
