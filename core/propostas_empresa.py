"""
core/propostas_empresa.py

Camada formal de propostas comerciais da Vetor.

Cada proposta é o objeto oficial que liga:
  oportunidade → fechamento → entrega

Não envia emails. Não gera PDF. Apenas mantém o estado auditável.

Arquivos gerenciados:
  dados/propostas_comerciais.json
  dados/historico_propostas_comerciais.json
  dados/aceites_propostas.json
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_PROPOSTAS  = config.PASTA_DADOS / "propostas_comerciais.json"
_ARQ_HISTORICO  = config.PASTA_DADOS / "historico_propostas_comerciais.json"
_ARQ_ACEITES    = config.PASTA_DADOS / "aceites_propostas.json"

# Sequência válida de status
_STATUS_VALIDOS = {
    "rascunho",
    "pronta_para_revisao",
    "aguardando_conselho",
    "aprovada_para_envio",
    "enviada",
    "aceita",
    "rejeitada",
    "arquivada",
}

_ESTAGIOS_FINAIS_OPP = {"ganho", "perdido", "encerrado"}


# ─── I/O ──────────────────────────────────────────────────────────────────────

def _ler(arq: Path, padrao):
    try:
        if arq.exists():
            with open(arq, encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        log.warning(f"[propostas] falha ao ler {arq.name}: {exc}")
    return padrao


def _salvar(arq: Path, dados) -> None:
    try:
        arq.parent.mkdir(parents=True, exist_ok=True)
        with open(arq, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.warning(f"[propostas] falha ao salvar {arq.name}: {exc}")


def carregar_propostas() -> list:
    return _ler(_ARQ_PROPOSTAS, [])


def salvar_propostas(lista: list) -> None:
    _salvar(_ARQ_PROPOSTAS, lista)


def carregar_historico() -> list:
    return _ler(_ARQ_HISTORICO, [])


def carregar_aceites() -> list:
    return _ler(_ARQ_ACEITES, [])


# ─── Montagem do corpo da proposta ───────────────────────────────────────────

def montar_corpo_proposta(opp: dict) -> dict:
    """
    Monta escopo, entregáveis, premissas e fora_do_escopo com base em:
    - catálogo de ofertas (pacote selecionado)
    - contexto da oportunidade
    - guia de comunicação da Vetor
    Retorna dict com os campos do corpo.
    """
    from core.ofertas_empresa import carregar_catalogo, montar_texto_proposta

    oferta_id = opp.get("oferta_id", "")
    pacote_id = opp.get("pacote_id", "")
    linha     = opp.get("linha_servico_sugerida", "")
    contraparte = opp.get("contraparte", "")

    # Buscar dados do pacote no catálogo
    catalogo  = carregar_catalogo()
    oferta    = next((o for o in catalogo.get("ofertas", []) if o["id"] == oferta_id), {})
    pacotes   = {p["id"]: p for p in oferta.get("pacotes", [])}
    pacote    = pacotes.get(pacote_id, {})

    entregaveis    = pacote.get("entregaveis", oferta.get("entregaveis_base", []))
    checklist_ent  = pacote.get("checklist_entrega", [])
    valor_ref      = pacote.get("valor_referencia") or opp.get("valor_referencia")
    prazo_dias     = pacote.get("prazo_dias") or opp.get("prazo_dias_oferta")

    # Premissas padrão por linha
    _PREMISSAS = {
        "marketing_presenca_digital": [
            "Acesso às contas de redes sociais e Google Business para diagnóstico",
            "Contato responsável disponível para 1-2 alinhamentos durante o projeto",
            "Feedbacks respondidos em até 48h úteis",
        ],
        "automacao_atendimento": [
            "Contato responsável pelo atendimento disponível para alinhamentos",
            "Acesso ao WhatsApp Business da empresa",
            "Aprovação interna de scripts antes da implantação",
        ],
        "gestao_financeira": [
            "Disponibilização de extratos e dados dos últimos 3-6 meses",
            "Contato responsável financeiro disponível para alinhamentos",
            "Feedbacks respondidos em até 48h úteis",
        ],
        "gestao_comercial": [
            "Manutenção do processo implantado na fase anterior",
            "Participação do responsável nas revisões periódicas agendadas",
        ],
    }
    premissas = _PREMISSAS.get(linha, [
        "Disponibilidade do contato responsável para alinhamentos",
        "Feedbacks respondidos em até 48h úteis",
    ])

    # Fora do escopo padrão por linha
    _FORA_ESCOPO = {
        "marketing_presenca_digital": [
            "Criação de conteúdo recorrente para redes sociais",
            "Gestão contínua de anúncios pagos",
            "Redesign completo de identidade visual",
        ],
        "automacao_atendimento": [
            "Desenvolvimento de software ou integração com sistemas externos",
            "Gestão diária da equipe de vendas",
            "Scripts em idiomas além do português",
        ],
        "gestao_financeira": [
            "Contabilidade fiscal ou tributária",
            "Consultoria jurídica ou trabalhista",
            "Auditoria formal",
        ],
        "gestao_comercial": [
            "Expansão do escopo original contratado sem novo contrato",
            "Suporte operacional diário fora dos ciclos de revisão",
        ],
    }
    fora_do_escopo = _FORA_ESCOPO.get(linha, [
        "Atividades fora do escopo definido acima",
        "Suporte contínuo além do prazo do projeto",
    ])

    # Resumo do problema (via contexto_origem ou categoria)
    resumo_problema = (
        opp.get("contexto_origem", "")
        or opp.get("diagnostico_resumo", "")
        or f"Empresa identificada com oportunidade em {linha.replace('_', ' ')} — "
           f"categoria: {opp.get('categoria', 'não especificada')}"
    )

    # Texto de proposta via template
    texto = montar_texto_proposta(
        opp,
        nome_contato=opp.get("contato_principal", contraparte),
        gap_principal=opp.get("gap_principal", ""),
    )

    return {
        "resumo_problema":  resumo_problema[:500],
        "escopo":           f"Entrega de {oferta.get('nome', linha)}, pacote {pacote.get('nome', pacote_id)}, "
                            f"conforme entregáveis listados abaixo.",
        "entregaveis":      entregaveis,
        "checklist_execucao": checklist_ent,
        "premissas":        premissas,
        "fora_do_escopo":   fora_do_escopo,
        "proposta_valor":   valor_ref,
        "prazo_referencia": prazo_dias,
        "texto_assunto":    texto.get("assunto", ""),
        "texto_intro":      texto.get("intro", ""),
        "texto_corpo":      texto.get("corpo", ""),
        "texto_fechamento": texto.get("fechamento", ""),
    }


# ─── Detecção de deliberação ──────────────────────────────────────────────────

def detectar_se_requer_deliberacao(opp: dict, corpo: dict) -> tuple[bool, str]:
    """
    Retorna (True, motivo) se a proposta precisa de validação do conselho.
    """
    from core.ofertas_empresa import verificar_gatilho_deliberacao_oferta
    delib, motivo = verificar_gatilho_deliberacao_oferta(opp)
    if delib:
        return True, motivo

    # Valor acima do teto mesmo sem oferta trigger
    valor = corpo.get("proposta_valor")
    if valor:
        try:
            if float(valor) > 5000.0:
                return True, f"valor_proposta=R${valor} acima do teto"
        except (TypeError, ValueError):
            pass

    # Sem entregáveis definidos = escopo ambíguo
    if not corpo.get("entregaveis"):
        return True, "entregáveis não definidos — escopo ambíguo"

    return False, ""


# ─── Geração de proposta ──────────────────────────────────────────────────────

def gerar_proposta_comercial(opp: dict, origem: str = "agente_comercial") -> dict | None:
    """
    Gera proposta formal para a oportunidade.

    Retorna o dict da proposta criada, ou None se não for possível gerar.

    Regras:
    - opp deve ter oferta_id definida
    - opp não deve estar em estágio final
    - se já existir proposta ativa para a opp, atualiza em vez de duplicar
    """
    opp_id    = opp.get("id", "")
    oferta_id = opp.get("oferta_id", "")

    if not oferta_id:
        log.debug(f"[propostas] {opp_id} sem oferta_id — não gerando proposta")
        return None

    if opp.get("estagio") in _ESTAGIOS_FINAIS_OPP:
        # Para ganhos, a proposta já deve ter sido aceita; não regerar
        return None

    propostas = carregar_propostas()
    agora     = datetime.now().isoformat(timespec="seconds")

    # Verificar se já existe proposta ativa (não arquivada/rejeitada)
    proposta_existente = next(
        (p for p in propostas
         if p.get("oportunidade_id") == opp_id
         and p.get("status") not in {"arquivada", "rejeitada"}),
        None,
    )
    if proposta_existente:
        log.debug(f"[propostas] {opp_id} já tem proposta {proposta_existente['id']} — ignorando")
        return proposta_existente

    corpo = montar_corpo_proposta(opp)
    requer_delib, motivo_delib = detectar_se_requer_deliberacao(opp, corpo)

    if requer_delib:
        status = "aguardando_conselho"
    elif corpo.get("entregaveis"):
        status = "pronta_para_revisao"
    else:
        status = "rascunho"

    proposta = {
        "id":                    f"prop_{str(uuid.uuid4())[:8]}",
        "oportunidade_id":       opp_id,
        "contraparte":           opp.get("contraparte", ""),
        "cidade":                opp.get("cidade", ""),
        "categoria":             opp.get("categoria", ""),
        "oferta_id":             oferta_id,
        "oferta_nome":           opp.get("nome_oferta", ""),
        "pacote_id":             opp.get("pacote_id", ""),
        "pacote_nome":           opp.get("nome_pacote", ""),
        "linha_servico":         opp.get("linha_servico_sugerida", ""),
        "origem_oportunidade":   opp.get("origem_oportunidade", ""),
        # Corpo da proposta
        "resumo_problema":       corpo["resumo_problema"],
        "escopo":                corpo["escopo"],
        "entregaveis":           corpo["entregaveis"],
        "checklist_execucao":    corpo["checklist_execucao"],
        "premissas":             corpo["premissas"],
        "fora_do_escopo":        corpo["fora_do_escopo"],
        "proposta_valor":        corpo["proposta_valor"],
        "prazo_referencia":      corpo["prazo_referencia"],
        # Texto
        "texto_assunto":         corpo["texto_assunto"],
        "texto_intro":           corpo["texto_intro"],
        "texto_corpo":           corpo["texto_corpo"],
        "texto_fechamento":      corpo["texto_fechamento"],
        # Estado
        "status":                status,
        "requer_deliberacao":    requer_delib,
        "motivo_deliberacao":    motivo_delib,
        "versao":                1,
        "gerada_em":             agora,
        "atualizada_em":         agora,
        "aprovada_em":           None,
        "rejeitada_em":          None,
        "aceita_em":             None,
        "gerada_por":            origem,
    }

    propostas.append(proposta)
    salvar_propostas(propostas)

    registrar_historico_proposta(
        proposta["id"],
        "proposta_gerada",
        f"Proposta gerada para {opp.get('contraparte', '?')} | "
        f"oferta={oferta_id}/{opp.get('pacote_id')} | "
        f"valor=R${corpo['proposta_valor']} | status={status}",
        origem=origem,
    )

    log.info(
        f"[propostas] {proposta['id']} gerada — "
        f"{opp.get('contraparte')} | {oferta_id}/{opp.get('pacote_id')} | "
        f"R${corpo['proposta_valor']} | status={status}"
    )
    return proposta


# ─── Vínculo com o pipeline ───────────────────────────────────────────────────

def vincular_proposta_ao_pipeline(opp: dict, proposta: dict) -> None:
    """Atualiza campos de proposta no dict de oportunidade in-place."""
    agora = datetime.now().isoformat(timespec="seconds")
    opp["proposta_id"]      = proposta["id"]
    opp["proposta_status"]  = proposta["status"]
    opp["ultima_proposta_em"] = agora
    opp["valor_proposta"]   = proposta.get("proposta_valor")


# ─── Aprovação / Rejeição ─────────────────────────────────────────────────────

def aprovar_proposta(proposta_id: str, origem: str = "conselho") -> tuple[bool, str]:
    """
    Marca proposta como aprovada_para_envio.
    Retorna (True, '') ou (False, motivo).
    """
    propostas = carregar_propostas()
    prop = next((p for p in propostas if p["id"] == proposta_id), None)
    if not prop:
        return False, f"proposta {proposta_id} não encontrada"

    if prop["status"] in {"aceita", "arquivada", "rejeitada"}:
        return False, f"proposta já em status={prop['status']}"

    agora = datetime.now().isoformat(timespec="seconds")
    prop["status"]       = "aprovada_para_envio"
    prop["aprovada_em"]  = agora
    prop["atualizada_em"] = agora
    salvar_propostas(propostas)

    registrar_historico_proposta(
        proposta_id, "proposta_aprovada",
        f"Aprovada por {origem}",
        origem=origem,
    )
    log.info(f"[propostas] {proposta_id} aprovada por {origem}")

    # Gerar documento oficial de proposta (best-effort)
    try:
        from core.documentos_empresa import gerar_documento_proposta
        gerar_documento_proposta(proposta_id, origem=origem)
    except Exception as _exc_doc:
        log.debug(f"[propostas] documento nao gerado: {_exc_doc}")

    return True, ""


def rejeitar_proposta(proposta_id: str, motivo: str = "", origem: str = "conselho") -> tuple[bool, str]:
    """Marca proposta como rejeitada."""
    propostas = carregar_propostas()
    prop = next((p for p in propostas if p["id"] == proposta_id), None)
    if not prop:
        return False, f"proposta {proposta_id} não encontrada"

    agora = datetime.now().isoformat(timespec="seconds")
    prop["status"]       = "rejeitada"
    prop["rejeitada_em"] = agora
    prop["atualizada_em"] = agora
    if motivo:
        prop["motivo_rejeicao"] = motivo
    salvar_propostas(propostas)

    registrar_historico_proposta(
        proposta_id, "proposta_rejeitada",
        f"Rejeitada por {origem}" + (f" — motivo: {motivo}" if motivo else ""),
        origem=origem,
    )
    log.info(f"[propostas] {proposta_id} rejeitada por {origem}")
    return True, ""


def arquivar_proposta(proposta_id: str, origem: str = "conselho") -> tuple[bool, str]:
    """Arquiva proposta sem rejeitar formalmente."""
    propostas = carregar_propostas()
    prop = next((p for p in propostas if p["id"] == proposta_id), None)
    if not prop:
        return False, f"proposta {proposta_id} não encontrada"

    agora = datetime.now().isoformat(timespec="seconds")
    prop["status"]       = "arquivada"
    prop["atualizada_em"] = agora
    salvar_propostas(propostas)

    registrar_historico_proposta(
        proposta_id, "proposta_arquivada",
        f"Arquivada por {origem}",
        origem=origem,
    )
    return True, ""


# ─── Aceite ───────────────────────────────────────────────────────────────────

def registrar_aceite_proposta(
    proposta_id: str,
    tipo_aceite: str = "aceite_manual_conselho",
    descricao: str = "",
    origem: str = "conselho",
) -> tuple[bool, str]:
    """
    Registra aceite de proposta pelo cliente (ou via conselho como proxy).
    Atualiza status da proposta para 'aceita'.
    """
    propostas = carregar_propostas()
    prop = next((p for p in propostas if p["id"] == proposta_id), None)
    if not prop:
        return False, f"proposta {proposta_id} não encontrada"

    if prop["status"] in {"rejeitada", "arquivada"}:
        return False, f"não é possível aceitar proposta com status={prop['status']}"

    agora = datetime.now().isoformat(timespec="seconds")
    prop["status"]    = "aceita"
    prop["aceita_em"] = agora
    prop["atualizada_em"] = agora
    salvar_propostas(propostas)

    aceites = carregar_aceites()
    aceites.append({
        "id":            str(uuid.uuid4())[:8],
        "proposta_id":   proposta_id,
        "tipo_aceite":   tipo_aceite,
        "descricao":     descricao or f"Aceite registrado por {origem}",
        "origem":        origem,
        "registrado_em": agora,
    })
    _salvar(_ARQ_ACEITES, aceites)

    registrar_historico_proposta(
        proposta_id, "proposta_aceita",
        f"Aceite tipo={tipo_aceite} registrado por {origem}",
        origem=origem,
    )
    log.info(f"[propostas] {proposta_id} aceita — tipo={tipo_aceite}")
    return True, ""


# ─── Histórico ────────────────────────────────────────────────────────────────

def registrar_historico_proposta(
    proposta_id: str, evento: str, descricao: str, origem: str = ""
) -> None:
    historico = carregar_historico()
    historico.append({
        "id":            str(uuid.uuid4())[:8],
        "proposta_id":   proposta_id,
        "evento":        evento,
        "descricao":     descricao,
        "origem":        origem,
        "registrado_em": datetime.now().isoformat(timespec="seconds"),
    })
    if len(historico) > 1000:
        historico = historico[-1000:]
    _salvar(_ARQ_HISTORICO, historico)


# ─── Consultas ────────────────────────────────────────────────────────────────

def buscar_proposta_por_opp(opp_id: str, apenas_ativas: bool = True) -> dict | None:
    """Retorna a proposta mais recente para a oportunidade."""
    propostas = carregar_propostas()
    candidatas = [p for p in propostas if p.get("oportunidade_id") == opp_id]
    if apenas_ativas:
        candidatas = [p for p in candidatas if p.get("status") not in {"arquivada", "rejeitada"}]
    if not candidatas:
        return None
    return sorted(candidatas, key=lambda p: p.get("gerada_em", ""), reverse=True)[0]


def buscar_proposta_aprovada_ou_aceita(opp_id: str) -> dict | None:
    """Retorna proposta aprovada ou aceita para uso pela entrega."""
    propostas = carregar_propostas()
    aptas = [
        p for p in propostas
        if p.get("oportunidade_id") == opp_id
        and p.get("status") in {"aprovada_para_envio", "enviada", "aceita"}
    ]
    if not aptas:
        return None
    return sorted(aptas, key=lambda p: p.get("gerada_em", ""), reverse=True)[0]


def sinais_proposta_para_opp(opp_id: str) -> list[str]:
    """
    Retorna lista de sinais de proposta para uso no avaliador de fechamento.
    Sinais possíveis: proposta_gerada, proposta_aprovada, proposta_aceita
    """
    prop = buscar_proposta_por_opp(opp_id, apenas_ativas=False)
    if not prop:
        return []
    sinais = ["proposta_gerada"]
    if prop["status"] in {"aprovada_para_envio", "enviada"}:
        sinais.append("proposta_aprovada")
    if prop["status"] == "aceita":
        sinais.append("proposta_aceita")
    return sinais


# ─── Resumo para painel ───────────────────────────────────────────────────────

def resumir_para_painel() -> dict:
    propostas = carregar_propostas()
    por_status: dict = {}
    for p in propostas:
        s = p.get("status", "desconhecido")
        por_status[s] = por_status.get(s, 0) + 1

    historico = carregar_historico()

    return {
        "total":              len(propostas),
        "rascunho":           por_status.get("rascunho", 0),
        "pronta_para_revisao": por_status.get("pronta_para_revisao", 0),
        "aguardando_conselho": por_status.get("aguardando_conselho", 0),
        "aprovadas":          por_status.get("aprovada_para_envio", 0),
        "enviadas":           por_status.get("enviada", 0),
        "aceitas":            por_status.get("aceita", 0),
        "rejeitadas":         por_status.get("rejeitada", 0),
        "arquivadas":         por_status.get("arquivada", 0),
        "por_status":         por_status,
        "lista":              propostas,
        "historico_recente":  historico[-20:] if historico else [],
    }
