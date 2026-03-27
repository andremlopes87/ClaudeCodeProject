"""
core/contratos_empresa.py — Camada de contratos e faturamento da Vetor.

Ponte formal entre proposta aceita e receita: transforma compromisso comercial
em plano de faturamento e gera contas a receber rastreáveis no financeiro.

Fluxo:
  proposta aceita
    → contrato (compromisso comercial)
    → plano de faturamento (parcelas/recorrências)
    → contas a receber (com referência ao contrato)

Regras:
  - Só gera contrato se proposta.status == 'aceita' E valor > 0
  - Sem proposta aceita: não gera automaticamente
  - Idempotente: não duplica contratos para a mesma proposta
  - Não duplica parcelas já geradas no financeiro
  - Best-effort: erros de enriquecimento não bloqueiam o fluxo principal
"""

import uuid
import logging
from datetime import datetime, date, timedelta
from pathlib import Path

import config

log = logging.getLogger(__name__)

# ─── Caminhos ─────────────────────────────────────────────────────────────────

_ARQ_CONTRATOS   = "contratos_clientes.json"
_ARQ_PLANOS      = "planos_faturamento.json"
_ARQ_HISTORICO   = "historico_contratos.json"
_ARQ_PROPOSTAS   = "propostas_comerciais.json"
_ARQ_ACEITES     = "aceites_propostas.json"
_ARQ_PIPELINE    = "pipeline_comercial.json"
_ARQ_CONTAS      = "contas_clientes.json"
_ARQ_RECEBER     = "contas_a_receber.json"
_ARQ_CATALOGO    = "catalogo_ofertas.json"

# Janela de geração antecipada para recorrentes (parcelas)
_JANELA_RECORRENTE = 3  # gera as primeiras N parcelas/meses


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
    return datetime.now().isoformat(timespec="seconds")


def _hoje() -> str:
    return date.today().isoformat()


def _vencimento(dias_offset: int) -> str:
    return (date.today() + timedelta(days=dias_offset)).isoformat()


# ─── Geração de contrato ──────────────────────────────────────────────────────

def gerar_contrato_de_proposta(proposta_id: str,
                                origem: str = "") -> "dict | None":
    """
    Tenta gerar um contrato a partir de uma proposta aceita.
    Retorna None se:
      - proposta não encontrada
      - proposta não está aceita
      - valor ausente/zero
      - contrato já existe para esta proposta
    """
    propostas = _ler(_ARQ_PROPOSTAS)
    proposta  = next((p for p in propostas if p["id"] == proposta_id), None)
    if not proposta:
        log.warning(f"[contratos] proposta {proposta_id} nao encontrada")
        return None

    if proposta.get("status") not in ("aceita", "aprovada_para_envio", "enviada"):
        if proposta.get("aceita_em") or proposta.get("aprovada_em"):
            pass  # aceita mesmo com status diferente (aceites explícitos)
        else:
            log.debug(f"[contratos] proposta {proposta_id} status={proposta.get('status')} — sem base suficiente")
            return None

    # Verificar aceite explícito
    aceites   = _ler(_ARQ_ACEITES)
    aceite    = next((a for a in aceites if a.get("proposta_id") == proposta_id), None)
    if not aceite and proposta.get("status") != "aceita":
        log.debug(f"[contratos] proposta {proposta_id} sem aceite registrado")
        return None

    valor = float(proposta.get("proposta_valor") or 0)
    if valor <= 0:
        log.debug(f"[contratos] proposta {proposta_id} valor={valor} — sem base suficiente")
        return None

    # Dedup: não gerar se já existe contrato para esta proposta
    contratos = _ler(_ARQ_CONTRATOS)
    if any(c.get("proposta_id") == proposta_id
           and c.get("status") not in ("cancelado",)
           for c in contratos):
        log.debug(f"[contratos] contrato ja existe para proposta {proposta_id}")
        return None

    modelo = _inferir_modelo_cobranca(proposta)
    num_parcelas = _inferir_numero_parcelas(proposta, modelo)

    agora = _agora()
    contrato_id = f"ct_{uuid.uuid4().hex[:8]}"

    contrato = {
        "id":                     contrato_id,
        "conta_id":               proposta.get("conta_id", ""),
        "oportunidade_id":        proposta.get("oportunidade_id", ""),
        "proposta_id":            proposta_id,
        "contraparte":            proposta.get("contraparte", ""),
        "oferta_id":              proposta.get("oferta_id", ""),
        "oferta_nome":            proposta.get("oferta_nome", ""),
        "pacote_id":              proposta.get("pacote_id", ""),
        "pacote_nome":            proposta.get("pacote_nome", ""),
        "linha_servico":          proposta.get("linha_servico", ""),
        "valor_total":            valor,
        "modelo_cobranca":        modelo,
        "numero_parcelas":        num_parcelas,
        "periodicidade":          _periodicidade(modelo),
        "data_inicio":            _hoje(),
        "data_primeiro_vencimento": _vencimento(30),
        "status":                 "ativo",
        "origem":                 origem,
        "escopo_resumido":        (proposta.get("escopo") or "")[:200],
        "observacoes":            "",
        "gerado_em":              agora,
        "atualizado_em":          agora,
        "ativado_em":             agora,
        "encerrado_em":           None,
    }

    contratos.append(contrato)
    _salvar(_ARQ_CONTRATOS, contratos)

    _registrar_historico(contrato_id, "contrato_gerado",
                         f"Contrato gerado de proposta {proposta_id} | "
                         f"valor=R${valor:.2f} | modelo={modelo}",
                         origem)

    # Enriquecer conta com contrato_id (best-effort)
    _vincular_contrato_a_conta(contrato_id, contrato)

    log.info(f"[contratos] {contrato_id} criado | contraparte={contrato['contraparte']} | "
             f"valor=R${valor:.2f} | modelo={modelo}")

    # Gerar documento oficial de contrato (best-effort)
    try:
        from core.documentos_empresa import gerar_documento_contrato
        _doc = gerar_documento_contrato(contrato_id, origem=origem)
        # Preparar envio por email assistido se documento gerado
        if _doc:
            try:
                from core.expediente_documentos_email import preparar_envio_documento
                preparar_envio_documento(_doc["id"], origem=origem)
            except Exception as _exc_env:
                log.debug(f"[contratos] envio documento nao preparado: {_exc_env}")
    except Exception as _exc_doc:
        log.debug(f"[contratos] documento nao gerado: {_exc_doc}")

    return contrato


def _inferir_modelo_cobranca(proposta: dict) -> str:
    """
    Infere modelo de cobrança pela linha de serviço e oferta.
    Prioridade: campo explícito > linha_servico > padrão avulso.
    """
    if proposta.get("modelo_cobranca"):
        return proposta["modelo_cobranca"]

    linha = proposta.get("linha_servico", "").lower()
    oferta = proposta.get("oferta_id", "").lower()

    # Serviços de gestão/recorrência contínua
    if any(k in linha for k in ("gestao", "recorrente", "suporte", "manutencao")):
        return "recorrente_mensal"
    if any(k in oferta for k in ("gestao", "recorrente", "mensal")):
        return "recorrente_mensal"

    # Implantações com múltiplas etapas → parcela fixa
    valor = float(proposta.get("proposta_valor") or 0)
    if valor >= 3000 and "implantacao" in (linha + oferta):
        return "parcela_fixa"

    # Diagnósticos, projetos curtos, avulsos → pagamento único
    return "avulso"


def _inferir_numero_parcelas(proposta: dict, modelo: str) -> int:
    if proposta.get("numero_parcelas"):
        try:
            return int(proposta["numero_parcelas"])
        except (ValueError, TypeError):
            pass
    if modelo == "avulso":
        return 1
    if modelo == "parcela_fixa":
        valor = float(proposta.get("proposta_valor") or 0)
        if valor >= 5000:
            return 3
        if valor >= 2000:
            return 2
        return 1
    if modelo in ("recorrente_mensal", "recorrente_trimestral"):
        return _JANELA_RECORRENTE
    return 1


def _periodicidade(modelo: str) -> str:
    return {
        "avulso":               "unico",
        "parcela_fixa":         "mensal",
        "recorrente_mensal":    "mensal",
        "recorrente_trimestral": "trimestral",
    }.get(modelo, "unico")


# ─── Plano de faturamento ─────────────────────────────────────────────────────

def gerar_plano_faturamento(contrato_id: str,
                             origem: str = "") -> "dict | None":
    """
    Gera o plano de faturamento para um contrato ativo sem plano.
    Retorna None se já existir plano ou contrato inválido.
    """
    contratos = _ler(_ARQ_CONTRATOS)
    contrato  = next((c for c in contratos if c["id"] == contrato_id), None)
    if not contrato:
        return None

    if contrato.get("status") not in ("ativo", "aguardando_ativacao"):
        return None

    planos = _ler(_ARQ_PLANOS)
    if any(p.get("contrato_id") == contrato_id
           and p.get("status") not in ("cancelado",)
           for p in planos):
        log.debug(f"[contratos] plano ja existe para contrato {contrato_id}")
        return None

    modelo       = contrato.get("modelo_cobranca", "avulso")
    valor_total  = float(contrato.get("valor_total", 0))
    num_parcelas = int(contrato.get("numero_parcelas", 1))
    periodicidade = contrato.get("periodicidade", "unico")

    # Calcular valor por parcela
    valor_parcela = round(valor_total / max(num_parcelas, 1), 2)
    # Ajuste para evitar arredondamento: última parcela absorve diferença
    resto = round(valor_total - valor_parcela * num_parcelas, 2)

    # Primeiro vencimento
    try:
        primeiro_venc = date.fromisoformat(contrato.get("data_primeiro_vencimento", _vencimento(30)))
    except ValueError:
        primeiro_venc = date.today() + timedelta(days=30)

    # Intervalo em dias por periodicidade
    intervalo = {"mensal": 30, "trimestral": 90, "unico": 0}.get(periodicidade, 30)

    parcelas = []
    for i in range(num_parcelas):
        venc_data = primeiro_venc + timedelta(days=intervalo * i)
        valor_p   = valor_parcela + (resto if i == num_parcelas - 1 else 0)
        parc_id   = f"parc_{uuid.uuid4().hex[:8]}"
        parcelas.append({
            "id":              parc_id,
            "numero":          i + 1,
            "descricao":       f"Parcela {i+1}/{num_parcelas} — {contrato.get('oferta_nome', contrato.get('linha_servico', ''))}",
            "valor":           round(valor_p, 2),
            "vencimento":      venc_data.isoformat(),
            "status":          "planejada",
            "conta_receber_id": None,
            "gerada_em":       _agora(),
            "recebida_em":     None,
        })

    agora   = _agora()
    plano_id = f"pln_{uuid.uuid4().hex[:8]}"
    plano = {
        "id":          plano_id,
        "contrato_id": contrato_id,
        "conta_id":    contrato.get("conta_id", ""),
        "proposta_id": contrato.get("proposta_id", ""),
        "contraparte": contrato.get("contraparte", ""),
        "tipo_plano":  modelo,
        "valor_total": valor_total,
        "parcelas":    parcelas,
        "status":      "planejado",
        "gerado_em":   agora,
        "atualizado_em": agora,
    }

    planos.append(plano)
    _salvar(_ARQ_PLANOS, planos)

    _registrar_historico(contrato_id, "plano_faturamento_criado",
                         f"Plano {plano_id} | {num_parcelas} parcela(s) | "
                         f"valor=R${valor_total:.2f} | tipo={modelo}",
                         origem)

    log.info(f"[contratos] plano {plano_id} criado | contrato={contrato_id} | "
             f"parcelas={num_parcelas} | modelo={modelo}")
    return plano


# ─── Geração de recebíveis ────────────────────────────────────────────────────

def gerar_recebiveis_do_plano(plano_id: str,
                               origem: str = "") -> list:
    """
    Para cada parcela 'planejada' do plano, gera conta a receber no financeiro.
    Idempotente: pula parcelas que já têm conta_receber_id.
    Retorna lista de contas a receber geradas.
    """
    planos = _ler(_ARQ_PLANOS)
    plano  = next((p for p in planos if p["id"] == plano_id), None)
    if not plano:
        return []

    if plano.get("status") == "cancelado":
        return []

    contratos = _ler(_ARQ_CONTRATOS)
    contrato  = next((c for c in contratos if c["id"] == plano.get("contrato_id", "")), None)
    if contrato and contrato.get("status") == "cancelado":
        return []

    recebiveis_gerados = []
    parcelas_atualizadas = False
    agora = _agora()

    for parc in plano.get("parcelas", []):
        if parc.get("status") != "planejada":
            continue
        if parc.get("conta_receber_id"):
            continue  # já gerado

        # Montar conta a receber
        conta_receber = {
            "contraparte":          plano.get("contraparte", ""),
            "descricao":            parc["descricao"],
            "valor_total":          parc["valor"],
            "data_emissao":         agora[:10],
            "data_vencimento":      parc["vencimento"],
            "status":               "aberta",
            "categoria":            "receita",
            # Rastreabilidade de contrato
            "contrato_id":          plano["contrato_id"],
            "proposta_id":          plano.get("proposta_id", ""),
            "conta_id":             plano.get("conta_id", ""),
            "plano_faturamento_id": plano_id,
            "parcela_id":           parc["id"],
            "origem_recebivel":     "contrato_vetor",
            "descricao_origem":     f"Contrato {plano['contrato_id']} | parcela {parc['numero']}",
        }

        # Registrar via módulo financeiro
        try:
            from modulos.financeiro.contas_a_receber import registrar_conta_a_receber
            cr = registrar_conta_a_receber(conta_receber)
            parc["conta_receber_id"] = cr["id"]
            parc["status"]           = "gerada_no_financeiro"
            parcelas_atualizadas     = True
            recebiveis_gerados.append(cr)
            _registrar_historico(plano["contrato_id"], "recebivel_gerado",
                                 f"Conta a receber {cr['id']} | parcela {parc['numero']} | "
                                 f"venc={parc['vencimento']} | valor=R${parc['valor']:.2f}",
                                 origem)
            log.info(f"[contratos] recebivel {cr['id']} | parcela {parc['numero']} "
                     f"venc={parc['vencimento']} | R${parc['valor']:.2f}")
        except Exception as exc:
            log.warning(f"[contratos] erro ao gerar recebivel para parcela {parc['id']}: {exc}")

    if parcelas_atualizadas:
        # Atualizar status do plano
        total_parc = len(plano["parcelas"])
        geradas    = sum(1 for p in plano["parcelas"] if p.get("status") != "planejada")
        if geradas == 0:
            plano["status"] = "planejado"
        elif geradas < total_parc:
            plano["status"] = "parcialmente_gerado"
        else:
            plano["status"] = "totalmente_gerado"
        plano["atualizado_em"] = agora
        _salvar(_ARQ_PLANOS, planos)

    return recebiveis_gerados


# ─── Batch por agentes ────────────────────────────────────────────────────────

def processar_contratos_pendentes(origem: str = "") -> dict:
    """
    Itera propostas aceitas sem contrato e gera contratos + planos.
    Chamado pelo agente_comercial.
    Retorna resumo: {contratos_gerados, planos_gerados, erros}.
    """
    propostas = _ler(_ARQ_PROPOSTAS)
    contratos_g = 0
    planos_g    = 0
    erros       = 0

    aceitas = [p for p in propostas
               if p.get("status") == "aceita"
               or p.get("aceita_em")
               or p.get("aprovada_em")]

    for prop in aceitas:
        try:
            ct = gerar_contrato_de_proposta(prop["id"], origem)
            if ct:
                contratos_g += 1
                plano = gerar_plano_faturamento(ct["id"], origem)
                if plano:
                    planos_g += 1
        except Exception as exc:
            log.warning(f"[contratos] erro ao processar proposta {prop['id']}: {exc}")
            erros += 1

    if contratos_g:
        log.info(f"[contratos] ciclo: {contratos_g} contrato(s) | {planos_g} plano(s)")

    return {"contratos_gerados": contratos_g, "planos_gerados": planos_g, "erros": erros}


def gerar_recebiveis_pendentes(origem: str = "") -> dict:
    """
    Para cada plano sem todos os recebíveis gerados, gera as parcelas faltantes.
    Chamado pelo agente_financeiro.
    """
    planos = _ler(_ARQ_PLANOS)
    total_gerados = 0
    erros         = 0

    pendentes = [p for p in planos
                 if p.get("status") in ("planejado", "parcialmente_gerado")]

    for plano in pendentes:
        try:
            gerados = gerar_recebiveis_do_plano(plano["id"], origem)
            total_gerados += len(gerados)
        except Exception as exc:
            log.warning(f"[contratos] erro ao gerar recebiveis do plano {plano['id']}: {exc}")
            erros += 1

    return {"recebiveis_gerados": total_gerados, "erros": erros}


# ─── Vínculo com contas ───────────────────────────────────────────────────────

def _vincular_contrato_a_conta(contrato_id: str, contrato: dict) -> None:
    """Enriquece registro da conta com dados do contrato (best-effort)."""
    conta_id = contrato.get("conta_id")
    if not conta_id:
        return
    try:
        contas = _ler(_ARQ_CONTAS)
        conta  = next((c for c in contas if c["id"] == conta_id), None)
        if not conta:
            return
        # Acumular contratos_ativos
        ativos = conta.get("contratos_ativos", [])
        if contrato_id not in ativos:
            ativos.append(contrato_id)
        conta["contratos_ativos"]        = ativos
        conta["valor_total_fechado"]     = round(
            float(conta.get("valor_total_fechado") or 0)
            + float(contrato.get("valor_total") or 0), 2
        )
        conta["atualizado_em"] = _agora()
        _salvar(_ARQ_CONTAS, contas)
    except Exception as exc:
        log.debug(f"[contratos] vincular_conta ignorado: {exc}")


def enriquecer_contas_com_contratos() -> int:
    """
    Para cada conta, recalcula faturamento_previsto e ultimo_vencimento_previsto.
    Chamado pelo agente_financeiro após gerar recebíveis.
    Retorna número de contas atualizadas.
    """
    contratos = _ler(_ARQ_CONTRATOS)
    planos    = _ler(_ARQ_PLANOS)
    contas    = _ler(_ARQ_CONTAS)

    n_atualizadas = 0
    for conta in contas:
        conta_id = conta["id"]
        cts_ativos = [c for c in contratos
                      if c.get("conta_id") == conta_id
                      and c.get("status") == "ativo"]
        if not cts_ativos:
            continue

        # Faturamento previsto = soma das parcelas planejadas/geradas
        fat_previsto = 0.0
        ultimo_venc  = ""
        for ct in cts_ativos:
            plano = next((p for p in planos if p.get("contrato_id") == ct["id"]), None)
            if plano:
                for parc in plano.get("parcelas", []):
                    if parc.get("status") not in ("recebida", "cancelada"):
                        fat_previsto += float(parc.get("valor", 0))
                        venc = parc.get("vencimento", "")
                        if venc > ultimo_venc:
                            ultimo_venc = venc

        conta["faturamento_previsto"]      = round(fat_previsto, 2)
        conta["ultimo_vencimento_previsto"] = ultimo_venc
        conta["atualizado_em"] = _agora()
        n_atualizadas += 1

    if n_atualizadas:
        _salvar(_ARQ_CONTAS, contas)

    return n_atualizadas


# ─── Histórico ────────────────────────────────────────────────────────────────

def _registrar_historico(contrato_id: str, evento: str,
                          descricao: str, origem: str = "") -> None:
    hist = _ler(_ARQ_HISTORICO)
    hist.append({
        "id":           f"hct_{uuid.uuid4().hex[:8]}",
        "contrato_id":  contrato_id,
        "evento":       evento,
        "descricao":    descricao,
        "origem":       origem,
        "registrado_em": _agora(),
    })
    _salvar(_ARQ_HISTORICO, hist)


# ─── Consultas para o painel ──────────────────────────────────────────────────

def carregar_contratos() -> list:
    return _ler(_ARQ_CONTRATOS)


def carregar_planos() -> list:
    return _ler(_ARQ_PLANOS)


def resumir_para_painel() -> dict:
    contratos  = _ler(_ARQ_CONTRATOS)
    planos     = _ler(_ARQ_PLANOS)
    recebiveis = _ler(_ARQ_RECEBER)
    hoje = date.today().isoformat()

    ativos    = [c for c in contratos if c.get("status") == "ativo"]
    cancelados = [c for c in contratos if c.get("status") == "cancelado"]
    aguardando = [c for c in contratos if c.get("status") == "aguardando_ativacao"]

    valor_fechado = sum(float(c.get("valor_total", 0)) for c in ativos)

    # Faturamento previsto nos próximos 30 dias (parcelas não recebidas)
    fat_30d = 0.0
    daqui30 = (date.today() + timedelta(days=30)).isoformat()
    for plano in planos:
        for parc in plano.get("parcelas", []):
            if parc.get("status") not in ("recebida", "cancelada"):
                venc = parc.get("vencimento", "")
                if hoje <= venc <= daqui30:
                    fat_30d += float(parc.get("valor", 0))

    # Recebíveis abertos originados de contratos
    rcv_abertos = [r for r in recebiveis
                   if r.get("origem_recebivel") == "contrato_vetor"
                   and r.get("status") in ("aberta", "parcial", "vencida")]

    # Contratos sem plano
    ct_com_plano = {p.get("contrato_id") for p in planos if p.get("status") != "cancelado"}
    sem_plano    = [c for c in ativos if c["id"] not in ct_com_plano]

    # Planos com inconsistência (planejado há mais de 1 dia sem gerar recebíveis)
    inconsistentes = [p for p in planos
                      if p.get("status") == "planejado"
                      and p.get("gerado_em", "")[:10] < hoje]

    return {
        "total_contratos":           len(contratos),
        "contratos_ativos":          len(ativos),
        "contratos_aguardando":      len(aguardando),
        "contratos_cancelados":      len(cancelados),
        "valor_fechado_total":        round(valor_fechado, 2),
        "faturamento_previsto_30d":   round(fat_30d, 2),
        "recebiveis_contrato_abertos": len(rcv_abertos),
        "contratos_sem_plano":        len(sem_plano),
        "planos_com_inconsistencia":  len(inconsistentes),
    }


def obter_detalhe_contrato(contrato_id: str) -> dict:
    """Retorna contrato + plano + parcelas + recebíveis + histórico."""
    contratos = _ler(_ARQ_CONTRATOS)
    contrato  = next((c for c in contratos if c["id"] == contrato_id), None)
    if not contrato:
        return {}

    planos = _ler(_ARQ_PLANOS)
    plano  = next((p for p in planos if p.get("contrato_id") == contrato_id), None)

    recebiveis = []
    if plano:
        cr_ids = {parc.get("conta_receber_id") for parc in plano.get("parcelas", [])
                  if parc.get("conta_receber_id")}
        todos_rcv = _ler(_ARQ_RECEBER)
        recebiveis = [r for r in todos_rcv if r.get("id") in cr_ids]

    hist = [h for h in _ler(_ARQ_HISTORICO) if h.get("contrato_id") == contrato_id]
    hist = sorted(hist, key=lambda h: h.get("registrado_em", ""), reverse=True)[:20]

    return {
        "contrato":    contrato,
        "plano":       plano,
        "recebiveis":  recebiveis,
        "historico":   hist,
    }
