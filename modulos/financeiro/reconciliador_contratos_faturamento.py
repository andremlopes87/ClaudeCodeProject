"""
modulos/financeiro/reconciliador_contratos_faturamento.py

Fecha o ciclo de vida de contratos e planos de faturamento:
  - Reconcilia parcelas com contas_a_receber / recebimentos confirmados
  - Atualiza status de planos (planejado → concluido)
  - Atualiza status de contratos (ativo → concluido) cruzando entrega + financeiro
  - Enriquece contas_clientes.json com métricas financeiras
  - Enriquece previsao_caixa.json com parcelas planejadas futuras (conservador vs expandido)

Regras gerais:
  - Idempotente: pode rodar várias vezes sem efeito colateral
  - Best-effort: erros internos são logados, nunca travam o ciclo
  - Não duplica histórico: verifica antes de registrar
"""

import uuid
import logging
from datetime import date, timedelta
from pathlib import Path

import config

log = logging.getLogger(__name__)

# ─── Caminhos ─────────────────────────────────────────────────────────────────

_ARQ_CONTRATOS  = "contratos_clientes.json"
_ARQ_PLANOS     = "planos_faturamento.json"
_ARQ_RECEBER    = "contas_a_receber.json"
_ARQ_CONTAS     = "contas_clientes.json"
_ARQ_ENTREGA    = "pipeline_entrega.json"
_ARQ_HIST_CT    = "historico_contratos.json"
_ARQ_HIST_RECON = "historico_reconciliacao_contratos.json"
_ARQ_PREVISAO   = "previsao_caixa.json"

_JANELAS_DIAS = [7, 30, 60, 90]


# ─── I/O ──────────────────────────────────────────────────────────────────────

def _ler(arq: str, padrao=None):
    if padrao is None:
        padrao = []
    p = config.PASTA_DADOS / arq
    if not p.exists():
        return padrao
    try:
        import json
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return padrao


def _salvar(arq: str, dados):
    import json
    import os
    p = config.PASTA_DADOS / arq
    p.parent.mkdir(parents=True, exist_ok=True)
    conteudo = json.dumps(dados, ensure_ascii=False, indent=2)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def _agora() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _hoje() -> date:
    return date.today()


# ─── PARTE A: Reconciliar parcelas com recebíveis ─────────────────────────────

def reconciliar_parcelas_com_recebiveis(origem: str = "") -> dict:
    """
    Para cada parcela de cada plano, verifica o status da conta_a_receber vinculada
    e atualiza o status da parcela + campos de resumo do plano.
    Retorna resumo de alterações.
    """
    planos    = _ler(_ARQ_PLANOS)
    recebiveis = {r["id"]: r for r in _ler(_ARQ_RECEBER) if r.get("id")}
    hoje       = _hoje()

    n_reconciliadas = 0
    n_planos_atualizados = 0

    for plano in planos:
        if plano.get("status") in ("cancelado",):
            continue

        parcelas_alteradas = False
        for parc in plano.get("parcelas", []):
            status_anterior = parc.get("status", "planejada")
            novo_status = _reconciliar_parcela(parc, recebiveis, hoje)

            if novo_status != status_anterior:
                parc["status"]      = novo_status
                parcelas_alteradas  = True
                n_reconciliadas    += 1
                log.debug(f"[reconciliador] parcela {parc['id'][:12]} "
                          f"{status_anterior} -> {novo_status}")
                registrar_historico_reconciliacao(
                    plano.get("contrato_id", ""),
                    plano["id"],
                    parc["id"],
                    "parcela_reconciliada",
                    f"Status: {status_anterior} -> {novo_status} | "
                    f"venc={parc['vencimento']} | R${parc['valor']:.2f}",
                    origem,
                )

        if parcelas_alteradas:
            # Atualizar campos de resumo do plano
            _atualizar_resumo_plano(plano, recebiveis)
            plano["atualizado_em"] = _agora()
            n_planos_atualizados += 1

    if n_planos_atualizados:
        _salvar(_ARQ_PLANOS, planos)
        log.info(f"[reconciliador] {n_reconciliadas} parcela(s) reconciliada(s) | "
                 f"{n_planos_atualizados} plano(s) atualizado(s)")

    return {
        "parcelas_reconciliadas": n_reconciliadas,
        "planos_atualizados":     n_planos_atualizados,
    }


def _reconciliar_parcela(parc: dict, recebiveis: dict, hoje: date) -> str:
    """Retorna novo status para a parcela com base na conta_a_receber vinculada."""
    cr_id  = parc.get("conta_receber_id")
    status_atual = parc.get("status", "planejada")

    # Parcela já finalizada — não regredir
    if status_atual in ("recebida", "cancelada"):
        return status_atual

    if cr_id and cr_id in recebiveis:
        cr = recebiveis[cr_id]
        cr_status = cr.get("status", "aberta")
        if cr_status == "recebida":
            return "recebida"
        if cr_status in ("aberta", "parcial"):
            # Verificar vencimento
            try:
                venc = date.fromisoformat(parc.get("vencimento", ""))
                if venc < hoje:
                    return "vencida"
            except ValueError:
                pass
            return "gerada_no_financeiro"
        if cr_status == "vencida":
            return "vencida"
        if cr_status == "cancelada":
            return "cancelada"

    # Sem conta_receber_id — verificar vencimento
    if status_atual == "planejada":
        try:
            venc = date.fromisoformat(parc.get("vencimento", ""))
            if venc < hoje:
                return "vencida"
        except ValueError:
            pass

    return status_atual


def _atualizar_resumo_plano(plano: dict, recebiveis: dict) -> None:
    """Preenche campos de resumo de valores no plano (in-place)."""
    parcelas = plano.get("parcelas", [])
    total_planejado  = sum(p["valor"] for p in parcelas)
    total_gerado     = sum(p["valor"] for p in parcelas
                          if p.get("status") in ("gerada_no_financeiro", "recebida", "vencida"))
    total_recebido   = 0.0
    total_em_aberto  = 0.0
    proximo_venc     = ""

    for p in parcelas:
        if p.get("status") == "recebida":
            cr = recebiveis.get(p.get("conta_receber_id", ""), {})
            total_recebido += float(cr.get("valor_recebido", p["valor"]))
        elif p.get("status") in ("gerada_no_financeiro", "vencida"):
            cr = recebiveis.get(p.get("conta_receber_id", ""), {})
            total_em_aberto += float(cr.get("valor_em_aberto", p["valor"]))
        elif p.get("status") == "planejada":
            total_em_aberto += p["valor"]
            if not proximo_venc or p["vencimento"] < proximo_venc:
                proximo_venc = p["vencimento"]

    plano["total_planejado"]      = round(total_planejado, 2)
    plano["total_gerado"]         = round(total_gerado, 2)
    plano["total_recebido"]       = round(total_recebido, 2)
    plano["total_em_aberto"]      = round(total_em_aberto, 2)
    plano["proximo_vencimento"]   = proximo_venc
    plano["resumo_status_parcelas"] = {
        s: sum(1 for p in parcelas if p.get("status") == s)
        for s in ("planejada", "gerada_no_financeiro", "recebida", "vencida", "cancelada")
        if any(p.get("status") == s for p in parcelas)
    }


# ─── PARTE B: Atualizar status do plano ───────────────────────────────────────

def atualizar_status_plano(origem: str = "") -> dict:
    """
    Atualiza status geral do plano com base no estado das parcelas.
    Chama _atualizar_resumo_plano se necessário.
    """
    planos     = _ler(_ARQ_PLANOS)
    recebiveis = {r["id"]: r for r in _ler(_ARQ_RECEBER) if r.get("id")}
    n_atualizados = 0

    for plano in planos:
        if plano.get("status") in ("cancelado",):
            continue

        status_anterior = plano.get("status", "planejado")
        novo_status = _calcular_status_plano(plano)

        if "total_recebido" not in plano:
            _atualizar_resumo_plano(plano, recebiveis)

        if novo_status != status_anterior:
            plano["status"]      = novo_status
            plano["atualizado_em"] = _agora()
            n_atualizados       += 1
            log.info(f"[reconciliador] plano {plano['id']} "
                     f"{status_anterior} -> {novo_status}")
            registrar_historico_reconciliacao(
                plano.get("contrato_id", ""),
                plano["id"], "",
                "plano_atualizado",
                f"Status: {status_anterior} -> {novo_status}",
                origem,
            )

    if n_atualizados:
        _salvar(_ARQ_PLANOS, planos)

    return {"planos_atualizados": n_atualizados}


def _calcular_status_plano(plano: dict) -> str:
    """Regra explícita de status do plano baseada nas parcelas."""
    parcelas = plano.get("parcelas", [])
    if not parcelas:
        return plano.get("status", "planejado")

    statuses = [p.get("status", "planejada") for p in parcelas]
    total = len(statuses)

    n_planejada    = statuses.count("planejada")
    n_gerada       = statuses.count("gerada_no_financeiro")
    n_recebida     = statuses.count("recebida")
    n_vencida      = statuses.count("vencida")

    if n_recebida == total:
        return "concluido"
    if n_recebida > 0 and (n_gerada > 0 or n_vencida > 0):
        return "em_recebimento"
    if n_recebida > 0:
        return "em_recebimento"
    if n_gerada == total:
        return "totalmente_gerado"
    if n_gerada > 0 and n_planejada > 0:
        return "parcialmente_gerado"
    if n_gerada > 0:
        return "totalmente_gerado"
    if n_vencida > 0:
        return "em_recebimento"  # há parcelas vencidas — plano está em cobrança
    return "planejado"


# ─── PARTE C: Atualizar status do contrato ────────────────────────────────────

def atualizar_status_contrato(origem: str = "") -> dict:
    """
    Atualiza status, status_operacional, status_financeiro e percentuais
    de cada contrato ativo com base na entrega e no plano.
    """
    contratos  = _ler(_ARQ_CONTRATOS)
    planos     = _ler(_ARQ_PLANOS)
    entregas   = _ler(_ARQ_ENTREGA)

    # Índices
    plano_por_ct  = {p["contrato_id"]: p for p in planos}
    ent_por_prop  = {}  # proposta_id -> entrega
    ent_por_ct_id = {}  # conta_id -> entregas
    for e in entregas:
        if e.get("oportunidade_id"):
            ent_por_prop[e["oportunidade_id"]] = e
        if e.get("conta_id"):
            ent_por_ct_id.setdefault(e["conta_id"], []).append(e)

    n_atualizados = 0

    for ct in contratos:
        if ct.get("status") in ("cancelado",):
            continue

        plano     = plano_por_ct.get(ct["id"])
        entrega   = _encontrar_entrega(ct, ent_por_prop, ent_por_ct_id, entregas)

        status_op  = _calcular_status_operacional(entrega)
        status_fin = _calcular_status_financeiro(plano)
        pct_fat    = _pct_faturado(plano)
        pct_rec    = _pct_recebido(plano)
        pct_ent    = float(entrega.get("percentual_conclusao", 0)) if entrega else 0.0
        ult_venc   = plano.get("proximo_vencimento", "") if plano else ""
        novo_status = _calcular_status_contrato(status_op, status_fin, ct)

        mudou = (
            ct.get("status_operacional") != status_op
            or ct.get("status_financeiro") != status_fin
            or ct.get("status") != novo_status
        )

        ct["status_operacional"]  = status_op
        ct["status_financeiro"]   = status_fin
        ct["percentual_faturado"] = round(pct_fat, 1)
        ct["percentual_recebido"] = round(pct_rec, 1)
        ct["percentual_entrega"]  = round(pct_ent, 1)
        ct["ultimo_vencimento"]   = ult_venc
        ct["atualizado_em"]       = _agora()

        if mudou:
            status_anterior = ct.get("status", "ativo")
            if novo_status != ct.get("status"):
                ct["status"] = novo_status
                if novo_status == "concluido" and not ct.get("encerrado_em"):
                    ct["encerrado_em"] = _agora()
            n_atualizados += 1
            log.info(f"[reconciliador] contrato {ct['id']} "
                     f"status={novo_status} op={status_op} fin={status_fin} "
                     f"fat={pct_fat:.0f}% rec={pct_rec:.0f}% ent={pct_ent:.0f}%")
            registrar_historico_reconciliacao(
                ct["id"], "", "",
                "contrato_status_atualizado",
                f"status={novo_status} | op={status_op} | fin={status_fin} | "
                f"fat={pct_fat:.0f}% | rec={pct_rec:.0f}% | ent={pct_ent:.0f}%",
                origem,
            )
            if novo_status == "concluido":
                _registrar_hist_contrato(
                    ct["id"], "contrato_concluido",
                    f"Contrato concluído | fat={pct_fat:.0f}% | rec={pct_rec:.0f}%",
                    origem,
                )

    if n_atualizados:
        _salvar(_ARQ_CONTRATOS, contratos)

    return {"contratos_atualizados": n_atualizados}


def _encontrar_entrega(ct: dict, ent_por_prop: dict,
                       ent_por_ct_id: dict, todas: list) -> "dict | None":
    # 1. Por oportunidade_id
    if ct.get("oportunidade_id") and ct["oportunidade_id"] in ent_por_prop:
        return ent_por_prop[ct["oportunidade_id"]]
    # 2. Por conta_id — pegar mais recente
    if ct.get("conta_id") and ct["conta_id"] in ent_por_ct_id:
        ents = ent_por_ct_id[ct["conta_id"]]
        return max(ents, key=lambda e: e.get("registrado_em", ""), default=None)
    # 3. Por contraparte (fallback)
    contraparte = ct.get("contraparte", "").lower()
    if contraparte:
        for e in todas:
            if e.get("contraparte", "").lower() == contraparte:
                return e
    return None


def _calcular_status_operacional(entrega: "dict | None") -> str:
    if not entrega:
        return "sem_entrega"
    st = entrega.get("status_entrega", "")
    if st == "concluida":
        return "concluido"
    if st == "aguardando_insumo":
        return "bloqueado"
    if st in ("onboarding", "em_execucao", "em_andamento"):
        return "ativo"
    return "ativo"


def _calcular_status_financeiro(plano: "dict | None") -> str:
    if not plano:
        return "sem_plano"
    st = plano.get("status", "planejado")
    return {
        "planejado":          "planejado",
        "parcialmente_gerado": "em_faturamento",
        "totalmente_gerado":  "em_cobranca",
        "em_recebimento":     "em_recebimento",
        "concluido":          "concluido",
        "cancelado":          "cancelado",
    }.get(st, st)


def _calcular_status_contrato(status_op: str, status_fin: str,
                               ct: dict) -> str:
    """
    Regra explícita: contrato só é concluido quando AMBOS (op e fin) concluírem.
    Em recorrentes, mantém ativo enquanto houver ciclo financeiro vivo.
    """
    modelo = ct.get("modelo_cobranca", "avulso")

    # Cancelado permanece cancelado
    if ct.get("status") == "cancelado":
        return "cancelado"
    if ct.get("status") == "pausado":
        return "pausado"

    # Conclusão: operacional E financeiro encerrados
    if status_op == "concluido" and status_fin == "concluido":
        return "concluido"

    # Em recorrentes: se plano concluiu mas entrega ainda ativa → ativo
    if modelo in ("recorrente_mensal", "recorrente_trimestral"):
        if status_fin in ("concluido",) and status_op == "ativo":
            return "ativo"  # aguardar próximo ciclo de faturamento

    # Bloqueio operacional não encerra contrato
    if status_op == "bloqueado":
        return "ativo"

    return "ativo"


def _pct_faturado(plano: "dict | None") -> float:
    if not plano:
        return 0.0
    total = float(plano.get("total_planejado") or plano.get("valor_total") or 0)
    gerado = float(plano.get("total_gerado") or 0)
    if total <= 0:
        return 0.0
    return min(100.0, (gerado / total) * 100)


def _pct_recebido(plano: "dict | None") -> float:
    if not plano:
        return 0.0
    total = float(plano.get("total_planejado") or plano.get("valor_total") or 0)
    recebido = float(plano.get("total_recebido") or 0)
    if total <= 0:
        return 0.0
    return min(100.0, (recebido / total) * 100)


# ─── PARTE D: Enriquecer contas com dados financeiros ─────────────────────────

def enriquecer_conta_com_financeiro(origem: str = "") -> int:
    """
    Atualiza contas_clientes.json com métricas financeiras derivadas de contratos.
    Retorna número de contas atualizadas.
    """
    contratos  = _ler(_ARQ_CONTRATOS)
    planos     = _ler(_ARQ_PLANOS)
    recebiveis = _ler(_ARQ_RECEBER)
    contas     = _ler(_ARQ_CONTAS)

    plano_por_ct = {p["contrato_id"]: p for p in planos}
    rcv_idx      = {r["id"]: r for r in recebiveis if r.get("id")}

    n_atualizadas = 0
    agora = _agora()

    for conta in contas:
        conta_id = conta["id"]
        cts = [c for c in contratos if c.get("conta_id") == conta_id]
        if not cts:
            continue

        fat_previsto  = 0.0
        fat_recebido  = 0.0
        ct_ativos     = []
        ct_concluidos = []
        ult_venc      = ""
        ult_receb     = ""

        for ct in cts:
            plano = plano_por_ct.get(ct["id"])
            if ct.get("status") == "ativo":
                ct_ativos.append(ct["id"])
            elif ct.get("status") == "concluido":
                ct_concluidos.append(ct["id"])

            if plano:
                for p in plano.get("parcelas", []):
                    if p.get("status") not in ("recebida", "cancelada"):
                        fat_previsto += p["valor"]
                        v = p.get("vencimento", "")
                        if v and (not ult_venc or v > ult_venc):
                            ult_venc = v
                    cr = rcv_idx.get(p.get("conta_receber_id", ""), {})
                    fat_recebido += float(cr.get("valor_recebido", 0))
                    rec_data = cr.get("data_recebimento", "")
                    if rec_data and (not ult_receb or rec_data > ult_receb):
                        ult_receb = rec_data

        conta["faturamento_previsto"]          = round(fat_previsto, 2)
        conta["faturamento_recebido"]          = round(fat_recebido, 2)
        conta["contratos_ativos"]              = ct_ativos
        conta["contratos_concluidos"]          = ct_concluidos
        conta["ultimo_vencimento_previsto"]    = ult_venc
        conta["ultimo_recebimento_confirmado"] = ult_receb
        conta["atualizado_em"]                 = agora
        n_atualizadas += 1

    if n_atualizadas:
        _salvar(_ARQ_CONTAS, contas)
        log.info(f"[reconciliador] {n_atualizadas} conta(s) enriquecida(s) com dados financeiros")

    return n_atualizadas


# ─── PARTE E: Enriquecer previsão de caixa ────────────────────────────────────

def enriquecer_previsao_caixa_com_planos(origem: str = "") -> dict:
    """
    Lê a previsao_caixa.json existente e adiciona:
      - entradas_planejadas_contratos_por_janela (parcelas ainda não geradas)
      - total_previsto_conservador (só recebiveis gerados)
      - total_previsto_expandido (recebiveis + parcelas planejadas)
      - detalhe_contratos_planejados

    Parcelas planejadas entram só na leitura expandida (mais incerta).
    Recebiveis já gerados entram na leitura conservadora.
    """
    planos     = _ler(_ARQ_PLANOS)
    contratos  = _ler(_ARQ_CONTRATOS)
    previsao   = _ler(_ARQ_PREVISAO, {})

    hoje      = _hoje()
    ct_ids_ativos = {c["id"] for c in contratos if c.get("status") == "ativo"}

    # Agregar parcelas planejadas por janela
    planejadas_por_janela: dict = {f"{d}_dias": 0.0 for d in _JANELAS_DIAS}
    detalhe_planejado: list = []

    for plano in planos:
        if plano.get("contrato_id") not in ct_ids_ativos:
            continue
        if plano.get("status") == "cancelado":
            continue

        contraparte = plano.get("contraparte", "")
        for parc in plano.get("parcelas", []):
            if parc.get("status") != "planejada":
                continue  # só parcelas ainda não geradas no financeiro

            try:
                venc = date.fromisoformat(parc["vencimento"])
            except (ValueError, KeyError):
                continue

            if venc < hoje:
                continue  # já vencida sem ser gerada — não projeta

            dias_ate_venc = (venc - hoje).days
            for d in _JANELAS_DIAS:
                if dias_ate_venc <= d:
                    planejadas_por_janela[f"{d}_dias"] = round(
                        planejadas_por_janela[f"{d}_dias"] + parc["valor"], 2
                    )

            detalhe_planejado.append({
                "contrato_id":  plano.get("contrato_id", ""),
                "contraparte":  contraparte,
                "parcela_id":   parc["id"],
                "valor":        parc["valor"],
                "vencimento":   parc["vencimento"],
                "dias_ate_venc": dias_ate_venc,
            })

    # Totais conservador vs expandido para janela de 30 dias
    janelas_existentes = previsao.get("janelas", {})
    j30 = janelas_existentes.get("30_dias", {})
    entradas_geradas_30d = j30.get("entradas_previstas", 0.0)
    planejadas_30d       = planejadas_por_janela["30_dias"]

    total_conservador = round(entradas_geradas_30d, 2)
    total_expandido   = round(entradas_geradas_30d + planejadas_30d, 2)

    # Enriquecer previsao com campos de contratos
    previsao["entradas_planejadas_contratos_por_janela"] = {
        k: round(v, 2) for k, v in planejadas_por_janela.items()
    }
    previsao["total_previsto_conservador"] = total_conservador
    previsao["total_previsto_expandido"]   = total_expandido
    previsao["detalhe_contratos_planejados"] = sorted(
        detalhe_planejado, key=lambda x: x["vencimento"]
    )
    previsao["contratos_enriquecido_em"] = _agora()

    _salvar(_ARQ_PREVISAO, previsao)

    registrar_historico_reconciliacao(
        "", "", "",
        "previsao_caixa_enriquecida",
        f"Planejado 30d=R${planejadas_30d:.2f} | "
        f"conservador=R${total_conservador:.2f} | expandido=R${total_expandido:.2f}",
        origem,
    )

    log.info(f"[reconciliador] previsao enriquecida | "
             f"planejado_30d=R${planejadas_30d:.2f} | "
             f"conservador=R${total_conservador:.2f} | expandido=R${total_expandido:.2f}")

    return {
        "planejadas_por_janela": planejadas_por_janela,
        "total_conservador":     total_conservador,
        "total_expandido":       total_expandido,
        "itens_planejados":      len(detalhe_planejado),
    }


# ─── Entrada principal (batch) ────────────────────────────────────────────────

def executar_reconciliacao(origem: str = "") -> dict:
    """
    Executa o ciclo completo de reconciliação na ordem correta.
    Chamado pelo agente_financeiro.
    """
    res_parc = reconciliar_parcelas_com_recebiveis(origem)
    res_plan = atualizar_status_plano(origem)
    res_ct   = atualizar_status_contrato(origem)
    n_contas = enriquecer_conta_com_financeiro(origem)
    res_prev = enriquecer_previsao_caixa_com_planos(origem)

    return {
        "parcelas_reconciliadas":   res_parc["parcelas_reconciliadas"],
        "planos_atualizados":       res_plan["planos_atualizados"],
        "contratos_atualizados":    res_ct["contratos_atualizados"],
        "contas_enriquecidas":      n_contas,
        "planejado_30d":            res_prev.get("total_expandido", 0),
    }


# ─── Atualização de status operacional por entrega ────────────────────────────

def atualizar_contrato_por_entrega(entrega_id: str,
                                    status_entrega: str,
                                    conta_id: str = "",
                                    oportunidade_id: str = "",
                                    origem: str = "") -> bool:
    """
    Chamado pelo agente_operacao_entrega quando uma entrega muda de status.
    Atualiza status_operacional do contrato vinculado.
    Retorna True se algum contrato foi atualizado.
    """
    contratos = _ler(_ARQ_CONTRATOS)
    atualizado = False

    for ct in contratos:
        if ct.get("status") == "cancelado":
            continue
        # Vincular por oportunidade_id (mais preciso) ou conta_id
        if ((oportunidade_id and ct.get("oportunidade_id") == oportunidade_id)
                or (conta_id and ct.get("conta_id") == conta_id)):
            novo_op = _calcular_status_operacional({"status_entrega": status_entrega})
            if ct.get("status_operacional") != novo_op:
                ct["status_operacional"] = novo_op
                ct["atualizado_em"]      = _agora()
                atualizado = True
                log.debug(f"[reconciliador] contrato {ct['id']} op={novo_op} "
                          f"por entrega {entrega_id}")

    if atualizado:
        _salvar(_ARQ_CONTRATOS, contratos)

    return atualizado


# ─── Histórico ────────────────────────────────────────────────────────────────

def registrar_historico_reconciliacao(
    contrato_id: str,
    plano_id: str,
    parcela_id: str,
    evento: str,
    descricao: str,
    origem: str = "",
) -> None:
    hist = _ler(_ARQ_HIST_RECON)
    hist.append({
        "id":            f"rec_{uuid.uuid4().hex[:8]}",
        "contrato_id":   contrato_id,
        "plano_id":      plano_id,
        "parcela_id":    parcela_id,
        "evento":        evento,
        "descricao":     descricao,
        "origem":        origem,
        "registrado_em": _agora(),
    })
    _salvar(_ARQ_HIST_RECON, hist)


def _registrar_hist_contrato(contrato_id: str, evento: str,
                               descricao: str, origem: str = "") -> None:
    hist = _ler(_ARQ_HIST_CT)
    hist.append({
        "id":           f"hct_{uuid.uuid4().hex[:8]}",
        "contrato_id":  contrato_id,
        "evento":       evento,
        "descricao":    descricao,
        "origem":       origem,
        "registrado_em": _agora(),
    })
    _salvar(_ARQ_HIST_CT, hist)


# ─── Resumo para painel ───────────────────────────────────────────────────────

def resumir_para_painel() -> dict:
    contratos  = _ler(_ARQ_CONTRATOS)
    planos     = _ler(_ARQ_PLANOS)
    recebiveis = _ler(_ARQ_RECEBER)
    hoje = _hoje().isoformat()

    ativos     = [c for c in contratos if c.get("status") == "ativo"]
    concluidos = [c for c in contratos if c.get("status") == "concluido"]

    planos_em_receb = [p for p in planos if p.get("status") == "em_recebimento"]
    parcelas_vencidas = sum(
        sum(1 for p in pl.get("parcelas", []) if p.get("status") == "vencida")
        for pl in planos
    )
    fat_recebido_total = sum(
        float(p.get("total_recebido") or 0) for p in planos
    )

    # Inconsistências: entrega concluída mas plano não concluído
    inconsistentes = [
        c for c in contratos
        if c.get("status_operacional") == "concluido"
        and c.get("status_financeiro") not in ("concluido", "sem_plano")
    ]

    return {
        "contratos_ativos":         len(ativos),
        "contratos_concluidos":     len(concluidos),
        "planos_em_recebimento":    len(planos_em_receb),
        "parcelas_vencidas":        parcelas_vencidas,
        "faturamento_recebido_total": round(fat_recebido_total, 2),
        "inconsistencias":          len(inconsistentes),
    }
