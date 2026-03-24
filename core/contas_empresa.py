"""
core/contas_empresa.py

Camada mestra de contas/clientes da Vetor.

Cada empresa atendida — lead, cliente ou ex-cliente — tem um registro único
que une: leads → oportunidades → propostas → entregas → financeiro.

Regras de matching (conservador, sem fundi automático):
  1. email_principal  (exato)
  2. instagram        (exato, sem @)
  3. site             (exato, sem http/https, sem trailing slash)
  4. telefone/whatsapp (somente dígitos, mínimo 8)
  5. nome_normalizado  (apenas se len >= 4, após remoção de sufixos corporativos)

Arquivos gerenciados:
  dados/contas_clientes.json
  dados/historico_contas_clientes.json
  dados/jornada_contas.json
"""

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_CONTAS    = config.PASTA_DADOS / "contas_clientes.json"
_ARQ_HISTORICO = config.PASTA_DADOS / "historico_contas_clientes.json"
_ARQ_JORNADA   = config.PASTA_DADOS / "jornada_contas.json"

# Referências a outros arquivos (leitura ou update mínimo)
_ARQ_PIPELINE  = config.PASTA_DADOS / "pipeline_comercial.json"
_ARQ_PROPOSTAS = config.PASTA_DADOS / "propostas_comerciais.json"
_ARQ_ENTREGA   = config.PASTA_DADOS / "pipeline_entrega.json"
_ARQ_RECEBER   = config.PASTA_DADOS / "contas_a_receber.json"


# ─── I/O ──────────────────────────────────────────────────────────────────────

def _ler(arq: Path, padrao):
    try:
        if arq.exists():
            return json.loads(arq.read_text(encoding="utf-8")) or padrao
    except Exception:
        pass
    return padrao


def _salvar(arq: Path, dados) -> None:
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── Normalização ─────────────────────────────────────────────────────────────

_RE_SUFIXOS = re.compile(
    r"\b(ltda|me|eireli|s\.?a\.?|epp|mei|microempresa|empresa|comercio|"
    r"comercial|servicos|industria|informatica)\b",
    re.IGNORECASE,
)


def _normalizar_nome(nome: str) -> str:
    """Versão normalizada do nome para comparação (sem sufixos, sem pontuação)."""
    n = (nome or "").lower().strip()
    n = _RE_SUFIXOS.sub(" ", n)
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _normalizar_tel(tel: str) -> str:
    return re.sub(r"\D", "", tel or "")


def _normalizar_site(site: str) -> str:
    s = (site or "").lower().strip()
    s = re.sub(r"^https?://", "", s)
    return s.rstrip("/")


def _normalizar_ig(ig: str) -> str:
    return (ig or "").lower().strip().lstrip("@")


# ─── Carregamento ─────────────────────────────────────────────────────────────

def carregar_contas() -> list:
    return _ler(_ARQ_CONTAS, [])


# ─── Matching ─────────────────────────────────────────────────────────────────

def _encontrar_conta_existente(contas: list, dados: dict) -> "dict | None":
    """
    Matching conservador por prioridade:
    email > instagram > site > telefone/whatsapp > nome_normalizado
    """
    nome_norm = _normalizar_nome(dados.get("nome_empresa", "") or dados.get("nome", ""))
    site      = _normalizar_site(dados.get("site", ""))
    instagram = _normalizar_ig(dados.get("instagram", ""))
    email     = (dados.get("email_principal", "") or dados.get("email", "")).strip().lower()
    tel       = _normalizar_tel(dados.get("telefone_principal", "") or dados.get("telefone", ""))
    wpp       = _normalizar_tel(dados.get("whatsapp", ""))

    for conta in contas:
        c_email = (conta.get("email_principal", "") or "").strip().lower()
        if email and c_email and email == c_email:
            return conta

        c_ig = _normalizar_ig(conta.get("instagram", ""))
        if instagram and c_ig and instagram == c_ig:
            return conta

        c_site = _normalizar_site(conta.get("site", ""))
        if site and c_site and site == c_site:
            return conta

        c_tel = _normalizar_tel(conta.get("telefone_principal", ""))
        c_wpp = _normalizar_tel(conta.get("whatsapp", ""))
        for t in (tel, wpp):
            if t and len(t) >= 8 and t in {c_tel, c_wpp} - {""}:
                return conta

        c_nome = conta.get("nome_normalizado", "")
        if nome_norm and len(nome_norm) >= 4 and c_nome and nome_norm == c_nome:
            return conta

    return None


# ─── Criação e enriquecimento ─────────────────────────────────────────────────

def encontrar_ou_criar_conta(dados_empresa: dict, origem: str = "") -> dict:
    """
    Retorna conta existente (por matching) ou cria nova.
    Enriquece campos vazios se conta já existir — sem sobrescrever.
    """
    contas = carregar_contas()
    conta  = _encontrar_conta_existente(contas, dados_empresa)
    agora  = datetime.now().isoformat(timespec="seconds")

    if conta:
        _enriquecer_campos(conta, dados_empresa, agora)
        _salvar(_ARQ_CONTAS, contas)
        return conta

    # Criar nova conta
    nome     = dados_empresa.get("nome_empresa", "") or dados_empresa.get("nome", "") or ""
    conta_id = f"conta_{uuid.uuid4().hex[:8]}"
    conta = {
        "id":                    conta_id,
        "nome_empresa":          nome,
        "nome_normalizado":      _normalizar_nome(nome),
        "site":                  dados_empresa.get("site", ""),
        "instagram":             dados_empresa.get("instagram", ""),
        "email_principal":       dados_empresa.get("email_principal", "") or dados_empresa.get("email", ""),
        "telefone_principal":    dados_empresa.get("telefone_principal", "") or dados_empresa.get("telefone", ""),
        "whatsapp":              dados_empresa.get("whatsapp", ""),
        "cidade":                dados_empresa.get("cidade", ""),
        "categoria":             dados_empresa.get("categoria", ""),
        "origem_inicial":        dados_empresa.get("origem_inicial", origem),
        "status_relacionamento": dados_empresa.get("status_relacionamento", "lead"),
        "fase_atual":            dados_empresa.get("fase_atual", "descoberta"),
        "oportunidade_ativa":    False,
        "cliente_ativo":         False,
        "risco_relacionamento":  False,
        "valor_total_propostas": 0.0,
        "valor_total_fechado":   0.0,
        "entregas_ativas":       0,
        "oportunidade_ids":      [],
        "proposta_ids":          [],
        "entrega_ids":           [],
        "tags":                  dados_empresa.get("tags", []),
        "observacoes":           dados_empresa.get("observacoes", ""),
        "criado_em":             agora,
        "atualizado_em":         agora,
    }
    contas.append(conta)
    _salvar(_ARQ_CONTAS, contas)
    registrar_historico_conta(conta_id, "conta_criada",
                              f"Conta criada via {origem or 'desconhecido'}", origem)
    registrar_evento_jornada_conta(conta_id, "conta_criada", "", "",
                                   f"Conta '{nome}' criada", origem)
    log.info(f"[contas] criada: {conta_id} — {nome}")
    return conta


def _enriquecer_campos(conta: dict, dados: dict, agora: str) -> None:
    """Preenche campos vazios da conta com dados novos. Não sobrescreve."""
    campos = [
        ("site",             lambda d: d.get("site", "")),
        ("instagram",        lambda d: d.get("instagram", "")),
        ("email_principal",  lambda d: d.get("email_principal", "") or d.get("email", "")),
        ("telefone_principal", lambda d: d.get("telefone_principal", "") or d.get("telefone", "")),
        ("whatsapp",         lambda d: d.get("whatsapp", "")),
        ("cidade",           lambda d: d.get("cidade", "")),
        ("categoria",        lambda d: d.get("categoria", "")),
    ]
    mudou = False
    for campo, extrator in campos:
        val = extrator(dados)
        if val and not conta.get(campo):
            conta[campo] = val
            mudou = True
    if mudou:
        conta["atualizado_em"] = agora


def enriquecer_conta(conta_id: str, dados_novos: dict) -> bool:
    contas = carregar_contas()
    conta  = next((c for c in contas if c["id"] == conta_id), None)
    if not conta:
        return False
    _enriquecer_campos(conta, dados_novos, datetime.now().isoformat(timespec="seconds"))
    _salvar(_ARQ_CONTAS, contas)
    return True


# ─── Vínculos ─────────────────────────────────────────────────────────────────

def vincular_oportunidade_a_conta(opp_id: str, conta_id: str, origem: str = "") -> bool:
    """Registra opp_id na conta e atualiza status para 'oportunidade' se ainda for lead."""
    contas = carregar_contas()
    conta  = next((c for c in contas if c["id"] == conta_id), None)
    if not conta:
        return False

    agora   = datetime.now().isoformat(timespec="seconds")
    opp_ids = conta.setdefault("oportunidade_ids", [])
    if opp_id not in opp_ids:
        opp_ids.append(opp_id)
        conta["oportunidade_ativa"] = True
        if conta.get("status_relacionamento") == "lead":
            conta["status_relacionamento"] = "oportunidade"
            conta["fase_atual"]            = "comercial"
        conta["atualizado_em"] = agora
        _salvar(_ARQ_CONTAS, contas)
        registrar_evento_jornada_conta(
            conta_id, "oportunidade_associada", "oportunidade", opp_id,
            f"Oportunidade {opp_id} associada", origem,
        )
    return True


def vincular_proposta_a_conta(proposta_id: str, conta_id: str,
                               valor: float = 0.0, origem: str = "") -> bool:
    contas = carregar_contas()
    conta  = next((c for c in contas if c["id"] == conta_id), None)
    if not conta:
        return False

    agora    = datetime.now().isoformat(timespec="seconds")
    prop_ids = conta.setdefault("proposta_ids", [])
    if proposta_id not in prop_ids:
        prop_ids.append(proposta_id)
        if valor:
            conta["valor_total_propostas"] = (conta.get("valor_total_propostas") or 0) + valor
        if conta.get("fase_atual") in ("descoberta", "comercial"):
            conta["fase_atual"] = "proposta"
        conta["atualizado_em"] = agora
        _salvar(_ARQ_CONTAS, contas)
        registrar_evento_jornada_conta(
            conta_id, "proposta_gerada", "proposta", proposta_id,
            f"Proposta {proposta_id} gerada", origem,
        )
    return True


def vincular_entrega_a_conta(entrega_id: str, conta_id: str, origem: str = "") -> bool:
    contas = carregar_contas()
    conta  = next((c for c in contas if c["id"] == conta_id), None)
    if not conta:
        return False

    agora   = datetime.now().isoformat(timespec="seconds")
    ent_ids = conta.setdefault("entrega_ids", [])
    if entrega_id not in ent_ids:
        ent_ids.append(entrega_id)
        conta["cliente_ativo"]  = True
        conta["entregas_ativas"] = len(ent_ids)
        if conta.get("status_relacionamento") in ("lead", "oportunidade"):
            conta["status_relacionamento"] = "cliente_ativo"
        if conta.get("fase_atual") not in ("entrega", "acompanhamento", "encerrado"):
            conta["fase_atual"] = "onboarding"
        conta["atualizado_em"] = agora
        _salvar(_ARQ_CONTAS, contas)
        registrar_evento_jornada_conta(
            conta_id, "entrega_aberta", "entrega", entrega_id,
            f"Entrega {entrega_id} aberta", origem,
        )
    return True


def vincular_evento_financeiro_a_conta(evento_id: str, conta_id: str,
                                        tipo: str = "", origem: str = "") -> bool:
    """Mínimo: registra na jornada sem alterar arquivos financeiros."""
    registrar_evento_jornada_conta(
        conta_id, "evento_financeiro_associado", "evento_financeiro", evento_id,
        f"Evento financeiro {tipo or evento_id} associado", origem,
    )
    return True


def marcar_proposta_aceita_na_conta(conta_id: str, proposta_id: str,
                                     valor: float = 0.0, origem: str = "") -> bool:
    """Promove conta para cliente_ativo ao aceitar proposta."""
    contas = carregar_contas()
    conta  = next((c for c in contas if c["id"] == conta_id), None)
    if not conta:
        return False

    agora = datetime.now().isoformat(timespec="seconds")
    conta["cliente_ativo"]         = True
    conta["status_relacionamento"] = "cliente_ativo"
    if conta.get("fase_atual") not in ("entrega", "acompanhamento"):
        conta["fase_atual"] = "onboarding"
    if valor:
        conta["valor_total_fechado"] = (conta.get("valor_total_fechado") or 0) + valor
    conta["atualizado_em"] = agora
    _salvar(_ARQ_CONTAS, contas)
    registrar_evento_jornada_conta(
        conta_id, "proposta_aceita", "proposta", proposta_id,
        f"Proposta {proposta_id} aceita — conta promovida a cliente_ativo", origem,
    )
    return True


# ─── Busca por contraparte ────────────────────────────────────────────────────

def encontrar_conta_por_contraparte(nome: str) -> "dict | None":
    """Busca conta pelo nome_normalizado. Útil para vincular registros legados."""
    if not nome:
        return None
    nome_norm = _normalizar_nome(nome)
    if len(nome_norm) < 3:
        return None
    return next(
        (c for c in carregar_contas() if c.get("nome_normalizado") == nome_norm),
        None,
    )


# ─── Associação passiva de financeiro ────────────────────────────────────────

def associar_contas_a_receber_a_contas() -> int:
    """
    Percorre contas_a_receber.json e preenche conta_id nos itens que
    ainda não o têm mas têm contraparte conhecida.
    Retorna o número de itens atualizados.
    """
    receber = _ler(_ARQ_RECEBER, [])
    if not receber:
        return 0

    contas  = carregar_contas()
    n_linked = 0
    for item in receber:
        if item.get("conta_id") or not item.get("contraparte"):
            continue
        nome_norm = _normalizar_nome(item["contraparte"])
        conta = next((c for c in contas if c.get("nome_normalizado") == nome_norm), None)
        if conta:
            item["conta_id"] = conta["id"]
            n_linked += 1

    if n_linked:
        _salvar(_ARQ_RECEBER, receber)
    return n_linked


# ─── Jornada e Histórico ─────────────────────────────────────────────────────

def registrar_evento_jornada_conta(
    conta_id: str,
    tipo_evento: str,
    referencia_tipo: str,
    referencia_id: str,
    descricao: str,
    origem: str = "",
) -> dict:
    agora  = datetime.now().isoformat(timespec="seconds")
    evento = {
        "id":              f"jrn_{uuid.uuid4().hex[:8]}",
        "conta_id":        conta_id,
        "tipo_evento":     tipo_evento,
        "referencia_tipo": referencia_tipo,
        "referencia_id":   referencia_id,
        "descricao":       descricao,
        "origem":          origem,
        "registrado_em":   agora,
    }
    jornada = _ler(_ARQ_JORNADA, [])
    jornada.append(evento)
    _salvar(_ARQ_JORNADA, jornada)
    return evento


def registrar_historico_conta(conta_id: str, evento: str,
                               descricao: str, origem: str = "") -> dict:
    agora = datetime.now().isoformat(timespec="seconds")
    item  = {
        "id":           f"hcnt_{uuid.uuid4().hex[:8]}",
        "conta_id":     conta_id,
        "evento":       evento,
        "descricao":    descricao,
        "origem":       origem,
        "registrado_em": agora,
    }
    historico = _ler(_ARQ_HISTORICO, [])
    historico.append(item)
    _salvar(_ARQ_HISTORICO, historico)
    return item


# ─── Resumo e detalhe para painel ─────────────────────────────────────────────

def resumir_para_painel() -> dict:
    contas     = carregar_contas()
    por_status: dict = {}
    for c in contas:
        s = c.get("status_relacionamento", "desconhecido")
        por_status[s] = por_status.get(s, 0) + 1

    return {
        "total_contas":             len(contas),
        "leads":                    por_status.get("lead", 0),
        "oportunidades":            por_status.get("oportunidade", 0),
        "clientes_ativos":          por_status.get("cliente_ativo", 0),
        "clientes_em_implantacao":  por_status.get("cliente_em_implantacao", 0),
        "clientes_recorrentes":     por_status.get("cliente_recorrente", 0),
        "clientes_inativos":        por_status.get("cliente_inativo", 0),
        "perdidos":                 por_status.get("perdido", 0),
        "com_risco":                sum(1 for c in contas if c.get("risco_relacionamento")),
        "por_status":               por_status,
    }


def obter_detalhe_conta(conta_id: str) -> dict:
    """Retorna conta + objetos relacionados para o drill-down do painel."""
    contas = carregar_contas()
    conta  = next((c for c in contas if c["id"] == conta_id), None)
    if not conta:
        return {}

    pipeline  = _ler(_ARQ_PIPELINE,  [])
    propostas = _ler(_ARQ_PROPOSTAS, [])
    entregas  = _ler(_ARQ_ENTREGA,   [])
    jornada   = _ler(_ARQ_JORNADA,   [])

    nome_norm = conta.get("nome_normalizado", "")

    # Match por conta_id (direto) + fallback por nome_normalizado (para registros legados)
    opps  = [o for o in pipeline  if o.get("conta_id") == conta_id
             or (_normalizar_nome(o.get("contraparte", "")) == nome_norm and nome_norm
                 and not o.get("conta_id"))]
    props = [p for p in propostas if p.get("conta_id") == conta_id]
    ents  = [e for e in entregas  if e.get("conta_id") == conta_id
             or (_normalizar_nome(e.get("contraparte", "")) == nome_norm and nome_norm
                 and not e.get("conta_id"))]
    jrn   = sorted(
        [j for j in jornada if j.get("conta_id") == conta_id],
        key=lambda j: j.get("registrado_em", ""),
        reverse=True,
    )[:20]

    return {
        "conta":         conta,
        "oportunidades": opps,
        "propostas":     props,
        "entregas":      ents,
        "jornada":       jrn,
    }
