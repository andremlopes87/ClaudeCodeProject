"""
core/contatos_contas.py

Camada formal de contatos (pessoas) associados a cada conta/empresa.

Para enviar email, ligar ou negociar, o sistema precisa saber QUEM é o
contato — nome, cargo, canal preferido. Este módulo mantém esses dados
de forma estruturada, sem LLM e sem API externa.

Regras:
  - Nunca duplicar: mesmo email + mesma conta → atualizar existente
  - Histórico de alterações em historico_contatos_contas.json
  - Validação mínima de email e telefone nas bordas
  - Custo zero

Arquivos gerenciados:
  dados/contatos_contas.json
  dados/historico_contatos_contas.json
"""

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQ_CONTATOS  = config.PASTA_DADOS / "contatos_contas.json"
_ARQ_HISTORICO = config.PASTA_DADOS / "historico_contatos_contas.json"

_CONFIANCAS = ("alta", "media", "baixa", "desconhecida")

# Ordem de prioridade para obter_contato_principal
_ORDEM_CONFIANCA = {c: i for i, c in enumerate(_CONFIANCAS)}


# ─── I/O ──────────────────────────────────────────────────────────────────────

def _ler() -> dict:
    if not _ARQ_CONTATOS.exists():
        return {"contatos": []}
    try:
        with open(_ARQ_CONTATOS, encoding="utf-8") as f:
            dados = json.load(f)
        if not isinstance(dados, dict) or "contatos" not in dados:
            raise ValueError("formato inválido")
        return dados
    except Exception as exc:
        log.warning(f"[contatos_contas] arquivo corrompido, recriando: {exc}")
        return {"contatos": []}


def _salvar(dados: dict) -> None:
    try:
        _ARQ_CONTATOS.parent.mkdir(parents=True, exist_ok=True)
        with open(_ARQ_CONTATOS, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.warning(f"[contatos_contas] falha ao salvar: {exc}")


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _gerar_id() -> str:
    return f"cont_{uuid.uuid4().hex[:8]}"


# ─── Validação ────────────────────────────────────────────────────────────────

def _email_valido(email: str) -> bool:
    """Validação mínima: tem @ e um ponto após o @."""
    if not email or not isinstance(email, str):
        return False
    email = email.strip()
    partes = email.split("@")
    return len(partes) == 2 and "." in partes[1] and len(partes[0]) > 0


def _telefone_normalizado(tel: str) -> str:
    """Remove formatação, mantém apenas dígitos e + inicial."""
    if not tel or not isinstance(tel, str):
        return ""
    limpo = re.sub(r"[^\d+]", "", tel.strip())
    # Se começar com 55 e tiver 13+ dígitos, presumir Brasil sem o +
    if limpo.startswith("55") and len(limpo) >= 12 and not limpo.startswith("+"):
        limpo = "+" + limpo
    return limpo if len(limpo) >= 8 else ""


# ─── CRUD ─────────────────────────────────────────────────────────────────────

def criar_contato(conta_id: str, dados: dict) -> dict:
    """
    Cria novo contato para uma conta.

    Campos em dados:
      nome          : str  (obrigatório)
      cargo         : str
      email         : str
      telefone      : str
      whatsapp      : str
      canal_preferido: str (email | telefone | whatsapp)
      origem        : str
      confianca     : str (alta | media | baixa | desconhecida)
      notas         : str

    Regra de deduplicação:
      Se já existe contato ativo com mesmo email + conta_id → atualiza e retorna.
      Telefone sozinho não deduplica (um número pode ter vários contatos).

    Retorna o contato criado ou atualizado.
    """
    nome = str(dados.get("nome", "")).strip()
    if not nome:
        log.warning("[contatos_contas] criar_contato chamado sem nome")

    email     = dados.get("email", "")
    telefone  = _telefone_normalizado(dados.get("telefone", ""))
    whatsapp  = _telefone_normalizado(dados.get("whatsapp", ""))
    confianca = dados.get("confianca", "desconhecida")
    if confianca not in _CONFIANCAS:
        confianca = "desconhecida"

    # Deduplicação por email + conta_id
    if email and _email_valido(email):
        existente = _buscar_por_email(conta_id, email)
        if existente:
            return atualizar_contato(existente["contato_id"], {
                "nome":            nome or existente["nome"],
                "cargo":           dados.get("cargo", existente.get("cargo", "")),
                "telefone":        telefone or existente.get("telefone", ""),
                "whatsapp":        whatsapp or existente.get("whatsapp", ""),
                "canal_preferido": dados.get("canal_preferido", existente.get("canal_preferido", "")),
                "origem":          dados.get("origem", existente.get("origem", "")),
                "confianca":       confianca,
                "notas":           dados.get("notas", existente.get("notas", "")),
            })
    elif email:
        log.warning(f"[contatos_contas] email inválido ignorado: '{email}'")
        email = ""

    agora   = _agora()
    contato = {
        "contato_id":     _gerar_id(),
        "conta_id":       conta_id,
        "nome":           nome,
        "cargo":          str(dados.get("cargo", "")),
        "email":          email,
        "telefone":       telefone,
        "whatsapp":       whatsapp,
        "canal_preferido": dados.get("canal_preferido", _inferir_canal(email, telefone, whatsapp)),
        "origem":         str(dados.get("origem", "manual")),
        "confianca":      confianca,
        "ativo":          True,
        "criado_em":      agora,
        "atualizado_em":  agora,
        "notas":          str(dados.get("notas", "")),
    }

    bd = _ler()
    bd["contatos"].append(contato)
    _salvar(bd)

    _registrar_hist(contato["contato_id"], conta_id, "contato_criado",
                    f"nome={nome} | email={email} | tel={telefone} | canal={contato['canal_preferido']}")

    log.info(f"[contatos_contas] {contato['contato_id']} criado para conta {conta_id}")
    return contato


def obter_contatos_conta(conta_id: str) -> list:
    """Retorna todos os contatos (ativos e inativos) de uma conta."""
    return [c for c in _ler()["contatos"] if c.get("conta_id") == conta_id]


def obter_contatos_ativos_conta(conta_id: str) -> list:
    """Retorna apenas contatos ativos de uma conta."""
    return [c for c in obter_contatos_conta(conta_id) if c.get("ativo", True)]


def obter_contato(contato_id: str) -> "dict | None":
    """Retorna um contato por ID ou None se não encontrado."""
    return next((c for c in _ler()["contatos"] if c.get("contato_id") == contato_id), None)


def atualizar_contato(contato_id: str, campos: dict) -> "dict | None":
    """
    Atualiza campos de um contato existente.
    Campos não informados mantêm valor atual.
    Retorna o contato atualizado ou None se não encontrado.
    """
    bd = _ler()
    contato = next((c for c in bd["contatos"] if c.get("contato_id") == contato_id), None)
    if not contato:
        log.warning(f"[contatos_contas] contato {contato_id} não encontrado para atualização")
        return None

    campos_alterados = []
    campos_editaveis = (
        "nome", "cargo", "email", "canal_preferido", "origem",
        "confianca", "notas",
    )

    for campo in campos_editaveis:
        if campo in campos and campos[campo] != contato.get(campo):
            contato[campo] = campos[campo]
            campos_alterados.append(campo)

    # Campos com normalização especial
    for campo_tel in ("telefone", "whatsapp"):
        if campo_tel in campos:
            valor = _telefone_normalizado(campos[campo_tel])
            if valor and valor != contato.get(campo_tel):
                contato[campo_tel] = valor
                campos_alterados.append(campo_tel)

    if campos_alterados:
        contato["atualizado_em"] = _agora()
        _salvar(bd)
        _registrar_hist(contato_id, contato.get("conta_id", ""),
                        "contato_atualizado", f"campos={', '.join(campos_alterados)}")

    return contato


def desativar_contato(contato_id: str) -> bool:
    """
    Desativa um contato (soft delete).
    Retorna True se encontrado e desativado, False caso contrário.
    """
    bd = _ler()
    contato = next((c for c in bd["contatos"] if c.get("contato_id") == contato_id), None)
    if not contato:
        return False

    contato["ativo"]         = False
    contato["atualizado_em"] = _agora()
    _salvar(bd)

    _registrar_hist(contato_id, contato.get("conta_id", ""),
                    "contato_desativado", "ativo → False")
    log.info(f"[contatos_contas] {contato_id} desativado")
    return True


def obter_contato_principal(conta_id: str) -> "dict | None":
    """
    Retorna o contato principal de uma conta.

    Critérios (em ordem):
      1. Ativo = True
      2. Maior confiança (alta > media > baixa > desconhecida)
      3. Em empate: primeiro criado (criado_em mais antigo)

    Retorna None se a conta não tiver contatos ativos.
    """
    ativos = obter_contatos_ativos_conta(conta_id)
    if not ativos:
        return None
    return sorted(
        ativos,
        key=lambda c: (
            _ORDEM_CONFIANCA.get(c.get("confianca", "desconhecida"), 99),
            c.get("criado_em", ""),
        ),
    )[0]


# ─── Importação de enriquecimento ─────────────────────────────────────────────

def importar_de_enriquecimento(empresa: dict) -> list:
    """
    Cria contatos a partir de dados de enriquecimento (candidata OSM).

    Lê campos: telefone, email, whatsapp, website (para email extraído).
    Usa conta_id = empresa.get("conta_id") ou empresa.get("id") ou osm_id.
    Retorna lista de contatos criados ou atualizados.
    """
    conta_id = (
        empresa.get("conta_id")
        or empresa.get("id")
        or str(empresa.get("osm_id", ""))
    )
    if not conta_id:
        log.warning("[contatos_contas] importar_de_enriquecimento sem conta_id")
        return []

    nome_empresa = empresa.get("nome", empresa.get("nome_empresa", ""))
    criados: list = []

    telefone = _telefone_normalizado(
        empresa.get("telefone") or empresa.get("telefone_principal", "")
    )
    email = empresa.get("email") or empresa.get("email_principal", "")
    whatsapp = _telefone_normalizado(
        empresa.get("whatsapp") or empresa.get("whatsapp_contato", "")
    )

    # Inferir confiança baseada na fonte
    origem = empresa.get("fonte_dados", empresa.get("origem_inicial", "enriquecimento"))
    confianca = "media" if telefone or (email and _email_valido(email)) else "baixa"

    # Se tem email válido — cria/atualiza contato com email
    if email and _email_valido(email):
        c = criar_contato(conta_id, {
            "nome":            f"Responsável — {nome_empresa}",
            "cargo":           "responsável",
            "email":           email,
            "telefone":        telefone,
            "whatsapp":        whatsapp or telefone,
            "canal_preferido": "email",
            "origem":          origem,
            "confianca":       confianca,
        })
        criados.append(c)

    # Se tem apenas telefone (sem email) — cria contato por telefone
    elif telefone:
        c = criar_contato(conta_id, {
            "nome":            f"Responsável — {nome_empresa}",
            "cargo":           "responsável",
            "telefone":        telefone,
            "whatsapp":        whatsapp or telefone,
            "canal_preferido": empresa.get("canal_abordagem_sugerido", "telefone"),
            "origem":          origem,
            "confianca":       confianca,
        })
        criados.append(c)

    log.info(
        f"[contatos_contas] importar_de_enriquecimento conta={conta_id}: "
        f"{len(criados)} contato(s) criado(s)/atualizado(s)"
    )
    return criados


# ─── Auxiliares internos ──────────────────────────────────────────────────────

def _buscar_por_email(conta_id: str, email: str) -> "dict | None":
    """Busca contato ativo por conta_id + email (case-insensitive)."""
    email_norm = email.strip().lower()
    return next(
        (c for c in _ler()["contatos"]
         if c.get("conta_id") == conta_id
         and c.get("email", "").strip().lower() == email_norm
         and c.get("ativo", True)),
        None,
    )


def _inferir_canal(email: str, telefone: str, whatsapp: str) -> str:
    """Infere canal preferido a partir dos campos disponíveis."""
    if email:
        return "email"
    if whatsapp:
        return "whatsapp"
    if telefone:
        return "telefone"
    return "desconhecido"


def _registrar_hist(
    contato_id: str,
    conta_id: str,
    evento: str,
    descricao: str,
) -> None:
    hist: list = []
    if _ARQ_HISTORICO.exists():
        try:
            with open(_ARQ_HISTORICO, encoding="utf-8") as f:
                hist = json.load(f)
            if not isinstance(hist, list):
                hist = []
        except Exception:
            hist = []

    hist.append({
        "id":          uuid.uuid4().hex[:8],
        "contato_id":  contato_id,
        "conta_id":    conta_id,
        "evento":      evento,
        "descricao":   descricao,
        "registrado_em": _agora(),
    })

    try:
        _ARQ_HISTORICO.parent.mkdir(parents=True, exist_ok=True)
        with open(_ARQ_HISTORICO, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        log.warning(f"[contatos_contas] falha ao salvar histórico: {exc}")
