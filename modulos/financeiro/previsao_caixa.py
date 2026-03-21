"""
modulos/financeiro/previsao_caixa.py — Previsão de caixa por janela temporal.

Gera projeções para 7 / 30 / 60 / 90 dias a partir do saldo atual,
percorrendo cronologicamente os vencimentos registrados dentro de cada janela.

IMPORTANTE — separação conceitual:
  risco_operacional  = calculado diretamente do caixa e dos vencimentos registrados
  sinais_crescimento = heurísticas simples para apoio à decisão — NÃO são métricas financeiras
                       formais. Devem ser tratados como indicadores de atenção, não diagnósticos.

Saídas:
  previsao_caixa.json          — projeção por janela + sinais + pontos de aperto
  fila_riscos_financeiros.json — lista ordenada de riscos acionáveis
"""

import logging
from datetime import date, timedelta

import config

logger = logging.getLogger(__name__)

_JANELAS_DIAS = [7, 30, 60, 90]


def gerar_previsao(
    saldo_base: float,
    contas_a_receber: list,
    contas_a_pagar: list,
    eventos: list,
) -> tuple:
    """
    Gera previsão de caixa e fila de riscos.
    Retorna: (previsao: dict, fila_riscos: list)
    """
    hoje = date.today()

    janelas = {}
    for dias in _JANELAS_DIAS:
        janelas[f"{dias}_dias"] = _projetar_janela(
            saldo_base, contas_a_receber, contas_a_pagar, eventos, hoje, dias
        )

    pontos_de_aperto = _detectar_pontos_de_aperto(janelas)
    sinais           = _sinais_crescimento(saldo_base, janelas, contas_a_receber, contas_a_pagar)
    fila_riscos      = _gerar_fila_riscos(janelas, contas_a_receber, contas_a_pagar, eventos, hoje, sinais)

    previsao = {
        "saldo_base":        round(saldo_base, 2),
        "janelas":           janelas,
        "pontos_de_aperto":  pontos_de_aperto,
        "sinais_crescimento": sinais,
        "gerado_em":         hoje.isoformat(),
    }
    return previsao, fila_riscos


# ─── Projeção por janela ────────────────────────────────────────────────────

def _projetar_janela(saldo_base, contas_receber, contas_pagar, eventos, hoje, dias) -> dict:
    data_fim = hoje + timedelta(days=dias)

    # Coleta todos os fluxos datados dentro da janela
    # Formato: (data, valor, contraparte_ou_descricao, tipo)
    fluxos = []

    for c in contas_receber:
        if c.get("status") not in ("aberta", "parcial"):
            continue
        venc = _parse_date(c.get("data_vencimento"))
        if venc and hoje <= venc <= data_fim:
            fluxos.append((venc, float(c["valor_em_aberto"]), c.get("contraparte", "?"), "entrada"))

    for c in contas_pagar:
        if c.get("status") not in ("aberta", "parcial"):
            continue
        venc = _parse_date(c.get("data_vencimento"))
        if venc and hoje <= venc <= data_fim:
            fluxos.append((venc, -float(c["valor_em_aberto"]), c.get("contraparte", "?"), "saida"))

    for ev in eventos:
        if ev.get("status") == "cancelado":
            continue
        tipo = ev.get("tipo", "")
        venc = _parse_date(ev.get("data_vencimento"))
        if not venc or not (hoje <= venc <= data_fim):
            continue
        valor = float(ev.get("valor", 0))
        if tipo == "entrada_prevista":
            fluxos.append((venc, valor, ev.get("descricao", "?"), "entrada"))
        if tipo in ("saida_prevista", "conta_a_vencer"):
            fluxos.append((venc, -valor, ev.get("descricao", "?"), "saida"))

    fluxos.sort(key=lambda x: x[0])

    # Totais da janela
    entradas = sum(v for _, v, _, t in fluxos if v > 0)
    saidas   = abs(sum(v for _, v, _, t in fluxos if v < 0))
    saldo_final = saldo_base + entradas - saidas

    # Percurso cronológico para detectar buraco de caixa
    saldo_corrente = saldo_base
    menor_saldo    = saldo_base
    data_menor     = hoje.isoformat()

    for data_fluxo, valor, _, _ in fluxos:
        saldo_corrente += valor
        if saldo_corrente < menor_saldo:
            menor_saldo = saldo_corrente
            data_menor  = data_fluxo.isoformat()

    houve_buraco = menor_saldo < config.FINANCEIRO_THRESHOLD_RISCO

    # Detalhes das contas no período (para consulta)
    contas_a_vencer_no_periodo = [
        {"contraparte": c.get("contraparte"), "valor": float(c["valor_em_aberto"]), "data": c["data_vencimento"]}
        for c in contas_pagar
        if c.get("status") in ("aberta", "parcial")
        and _parse_date(c.get("data_vencimento"))
        and hoje <= _parse_date(c["data_vencimento"]) <= data_fim
    ]
    contas_a_receber_no_periodo = [
        {"contraparte": c.get("contraparte"), "valor": float(c["valor_em_aberto"]), "data": c["data_vencimento"]}
        for c in contas_receber
        if c.get("status") in ("aberta", "parcial")
        and _parse_date(c.get("data_vencimento"))
        and hoje <= _parse_date(c["data_vencimento"]) <= data_fim
    ]

    return {
        "janela_dias":                     dias,
        "periodo_ate":                     data_fim.isoformat(),
        "entradas_previstas":              round(entradas, 2),
        "saidas_previstas":                round(saidas, 2),
        "saldo_projetado":                 round(saldo_final, 2),
        "risco_periodo":                   saldo_final < config.FINANCEIRO_THRESHOLD_RISCO,
        "menor_saldo_projetado_na_janela": round(menor_saldo, 2),
        "data_do_menor_saldo":             data_menor,
        "houve_buraco_de_caixa":           houve_buraco,
        "contas_a_receber_no_periodo":     contas_a_receber_no_periodo,
        "contas_a_vencer_no_periodo":      contas_a_vencer_no_periodo,
    }


# ─── Pontos de aperto ──────────────────────────────────────────────────────

def _detectar_pontos_de_aperto(janelas: dict) -> list:
    """Retorna lista de janelas onde houve buraco ou risco de período."""
    vistos = set()
    pontos = []
    for nome, janela in sorted(janelas.items(), key=lambda x: x[1]["janela_dias"]):
        if janela["houve_buraco_de_caixa"] or janela["risco_periodo"]:
            chave = janela["data_do_menor_saldo"]
            pontos.append({
                "janela":        nome,
                "data":          chave,
                "menor_saldo":   janela["menor_saldo_projetado_na_janela"],
                "houve_buraco":  janela["houve_buraco_de_caixa"],
            })
    return pontos


# ─── Sinais de crescimento (heurísticos) ──────────────────────────────────

def _sinais_crescimento(saldo_base, janelas, contas_receber, contas_pagar) -> dict:
    """
    Sinais heurísticos simples para apoio à decisão.
    NAO sao metricas financeiras formais — tratados como indicadores de atencao.
    """
    j7  = janelas["7_dias"]
    j30 = janelas["30_dias"]

    # ── Risco operacional imediato (caixa esta semana) ──────────────────
    risco_op = j7["houve_buraco_de_caixa"] or j7["risco_periodo"]

    # ── Risco de crescimento (fluxo estruturalmente negativo) ───────────
    # Saídas superam entradas nos próximos 30 dias
    risco_cresc = j30["saidas_previstas"] > j30["entradas_previstas"]
    # Ou saldo cai mais de 50% em 30 dias
    if not risco_cresc and saldo_base > 0:
        risco_cresc = j30["saldo_projetado"] < saldo_base * 0.5

    # Buraco em 30 dias também é sinal de risco estrutural
    buraco_30 = j30["houve_buraco_de_caixa"]

    # ── Folga para investir (margem acima do comprometido) ──────────────
    folga = max(0.0, j30["saldo_projetado"])
    tem_folga = folga > max(saldo_base * 0.3, config.FINANCEIRO_VALOR_RELEVANTE)

    # ── Dependência concentrada (um cliente > 50% do aberto) ───────────
    recebiveis = [
        (c.get("contraparte", "desconhecido"), float(c.get("valor_em_aberto", 0)))
        for c in contas_receber
        if c.get("status") in ("aberta", "parcial")
    ]
    total_rec = sum(v for _, v in recebiveis)
    maior_contraparte   = None
    percentual_maior    = 0.0
    dependencia         = False
    if recebiveis and total_rec > 0:
        por_contraparte = {}
        for contra, valor in recebiveis:
            por_contraparte[contra] = por_contraparte.get(contra, 0) + valor
        maior_contraparte = max(por_contraparte, key=por_contraparte.get)
        percentual_maior  = (por_contraparte[maior_contraparte] / total_rec) * 100
        dependencia       = percentual_maior >= 50

    # ── Classificação heurística geral ─────────────────────────────────
    if risco_op:
        classificacao = "critico"
    elif buraco_30 or risco_cresc:
        classificacao = "apertado"
    elif dependencia:
        classificacao = "apertado"
    elif tem_folga:
        classificacao = "folga"
    else:
        classificacao = "estavel"

    # ── Observações recomendadas ────────────────────────────────────────
    obs = []
    if risco_op:
        obs.append("Caixa desta semana em risco — revisar pagamentos imediatos antes de assumir novos compromissos")
    if buraco_30 and not risco_op:
        d = j30["data_do_menor_saldo"]
        m = j30["menor_saldo_projetado_na_janela"]
        obs.append(
            f"Caixa pode ficar negativo em {d} (saldo projetado: R$ {m:,.2f}) — "
            "considerar antecipar cobranca ou adiar despesa nao critica"
        )
    if risco_cresc:
        obs.append(
            f"Saidas dos proximos 30 dias (R$ {j30['saidas_previstas']:,.2f}) superam entradas "
            f"(R$ {j30['entradas_previstas']:,.2f}) — evitar novos compromissos financeiros"
        )
    if dependencia and maior_contraparte:
        obs.append(
            f"{maior_contraparte} representa {percentual_maior:.0f}% do valor a receber — "
            "risco de dependencia: inadimplencia ou cancelamento deste cliente compromete o caixa"
        )
    if not risco_op and not risco_cresc and not buraco_30 and tem_folga:
        obs.append(
            f"Caixa saudavel nos proximos 30 dias (saldo projetado: R$ {j30['saldo_projetado']:,.2f}) — "
            "ha margem para assumir novos compromissos"
        )
    if not obs:
        obs.append("Sem sinais de alerta identificados no periodo analisado")

    return {
        "nota":                          "Sinais heuristicos simples — nao sao metricas financeiras formais",
        "classificacao":                 classificacao,
        "risco_operacional_imediato":    risco_op,
        "risco_de_crescimento":          risco_cresc,
        "buraco_de_caixa_em_30_dias":    buraco_30,
        "folga_para_investir":           round(folga, 2),
        "tem_folga_para_investir":       tem_folga,
        "dependencia_concentrada":       dependencia,
        "maior_contraparte":             maior_contraparte,
        "percentual_maior_contraparte":  round(percentual_maior, 1),
        "observacoes_recomendadas":      obs,
    }


# ─── Fila de riscos acionáveis ─────────────────────────────────────────────

def _gerar_fila_riscos(janelas, contas_receber, contas_pagar, eventos, hoje, sinais) -> list:
    """
    Gera lista de riscos acionáveis ordenados por urgência + impacto.
    Cada risco tem: tipo, descricao, urgencia, impacto_estimado, acao_sugerida, prazo_sugerido.
    """
    riscos = []
    limiar = config.FINANCEIRO_VALOR_RELEVANTE

    # ── Risco 1: contas a receber vencidas sem resolução ──────────────
    for c in contas_receber:
        if c.get("status") != "vencida":
            continue
        valor = float(c.get("valor_em_aberto", 0))
        venc  = c.get("data_vencimento", "?")
        riscos.append({
            "tipo":             "vencido_sem_resolucao",
            "descricao":        f"{c.get('contraparte', '?')} — {c.get('descricao', '?')} — vencido em {venc}",
            "urgencia":         "alta",
            "impacto_estimado": round(valor, 2),
            "acao_sugerida":    "acionar cobranca — ligar ou enviar mensagem para o cliente",
            "prazo_sugerido":   hoje.isoformat(),
        })

    # ── Risco 2: contas a pagar vencidas sem pagamento ────────────────
    for c in contas_pagar:
        if c.get("status") != "vencida":
            continue
        valor = float(c.get("valor_em_aberto", 0))
        venc  = c.get("data_vencimento", "?")
        riscos.append({
            "tipo":             "vencido_sem_pagamento",
            "descricao":        f"{c.get('contraparte', '?')} — {c.get('descricao', '?')} — vencido em {venc}",
            "urgencia":         "alta",
            "impacto_estimado": round(valor, 2),
            "acao_sugerida":    "efetuar pagamento urgente ou negociar prazo com o fornecedor",
            "prazo_sugerido":   hoje.isoformat(),
        })

    # ── Risco 3: vencimentos iminentes a pagar ────────────────────────
    for c in contas_pagar:
        if c.get("status") not in ("aberta", "parcial"):
            continue
        venc = _parse_date(c.get("data_vencimento"))
        if not venc:
            continue
        diff = (venc - hoje).days
        if diff < 0:
            continue  # já vencida, tratada acima
        if diff <= config.FINANCEIRO_DIAS_ALERTA_IMEDIATO:
            urgencia = "alta"
        elif diff <= config.FINANCEIRO_DIAS_ALERTA_CURTO_PRAZO:
            urgencia = "media"
        else:
            continue
        valor = float(c.get("valor_em_aberto", 0))
        riscos.append({
            "tipo":             "vencimento_iminente",
            "descricao":        f"{c.get('contraparte', '?')} — {c.get('descricao', '?')} — vence em {diff} dia(s)",
            "urgencia":         urgencia,
            "impacto_estimado": round(valor, 2),
            "acao_sugerida":    "confirmar disponibilidade de caixa e efetuar pagamento no prazo",
            "prazo_sugerido":   venc.isoformat(),
        })

    # ── Risco 4: buraco de caixa dentro de alguma janela ─────────────
    buracos_registrados = set()
    for nome, janela in sorted(janelas.items(), key=lambda x: x[1]["janela_dias"]):
        if not janela["houve_buraco_de_caixa"]:
            continue
        data_b = janela["data_do_menor_saldo"]
        if data_b in buracos_registrados:
            continue  # mesmo buraco já registrado pela janela menor
        buracos_registrados.add(data_b)
        menor = janela["menor_saldo_projetado_na_janela"]
        urgencia = "alta" if janela["janela_dias"] <= 7 else "media"
        riscos.append({
            "tipo":             "caixa_insuficiente_na_janela",
            "descricao":        (
                f"Caixa pode ficar negativo nos proximos {janela['janela_dias']} dias "
                f"(menor saldo projetado: R$ {menor:,.2f} em {data_b})"
            ),
            "urgencia":         urgencia,
            "impacto_estimado": round(abs(menor), 2),
            "acao_sugerida":    "antecipar cobranca de cliente ou adiar despesa nao critica",
            "prazo_sugerido":   data_b,
        })

    # ── Risco 5: concentração de receita ─────────────────────────────
    if sinais.get("dependencia_concentrada"):
        contraparte = sinais.get("maior_contraparte", "?")
        pct         = sinais.get("percentual_maior_contraparte", 0)
        j30_saldo   = janelas["30_dias"]["saldo_projetado"]
        riscos.append({
            "tipo":             "concentracao_receita",
            "descricao":        f"{contraparte} representa {pct:.0f}% do valor a receber em aberto",
            "urgencia":         "media",
            "impacto_estimado": 0.0,
            "acao_sugerida":    "diversificar base de clientes — nao assumir despesas fixas baseadas apenas neste recebivel",
            "prazo_sugerido":   None,
        })

    # ── Risco 6: crescimento bloqueado ───────────────────────────────
    if sinais.get("risco_de_crescimento"):
        j30 = janelas["30_dias"]
        riscos.append({
            "tipo":             "crescimento_bloqueado",
            "descricao":        (
                f"Saidas dos proximos 30 dias (R$ {j30['saidas_previstas']:,.2f}) "
                f"superam entradas (R$ {j30['entradas_previstas']:,.2f})"
            ),
            "urgencia":         "media",
            "impacto_estimado": round(j30["saidas_previstas"] - j30["entradas_previstas"], 2),
            "acao_sugerida":    "revisar despesas ou antecipar faturamento para equilibrar o fluxo",
            "prazo_sugerido":   j30["periodo_ate"],
        })

    # Ordenação: alta → media, depois por impacto decrescente
    _ordem = {"alta": 0, "media": 1, "baixa": 2}
    riscos.sort(key=lambda r: (_ordem.get(r["urgencia"], 2), -r["impacto_estimado"]))
    return riscos


# ─── Utilitário ────────────────────────────────────────────────────────────

def _parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None
