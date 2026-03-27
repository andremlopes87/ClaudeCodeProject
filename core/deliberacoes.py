"""
core/deliberacoes.py — Camada de deliberações do conselho.

Gerencia o ciclo de vida de deliberações escaladas ao conselho:
  pendente -> em_analise -> deliberado -> aplicado | arquivado

Arquivos:
  dados/deliberacoes_conselho.json
  dados/historico_deliberacoes.json

Uso típico:
  - Secretário lê fila_consolidada e chama criar_ou_atualizar_deliberacao() por item
  - Conselho edita deliberacoes_conselho.json: seta status="deliberado" + decisao_conselho
  - Agentes chamam buscar_deliberacao_por_item_id() para detectar decisões e fechar o loop
"""

import hashlib
import json
from datetime import datetime

import config

_ARQ_DELIBERACOES = "deliberacoes_conselho.json"
_ARQ_HISTORICO    = "historico_deliberacoes.json"


# ─── Carga e persistência ─────────────────────────────────────────────────────

def carregar_deliberacoes() -> list:
    """Carrega dados/deliberacoes_conselho.json."""
    return _carregar_json(_ARQ_DELIBERACOES, padrao=[])


def salvar_deliberacoes(deliberacoes: list) -> None:
    """Persiste dados/deliberacoes_conselho.json."""
    _salvar_json(_ARQ_DELIBERACOES, deliberacoes)


def carregar_historico_deliberacoes() -> list:
    """Carrega dados/historico_deliberacoes.json."""
    return _carregar_json(_ARQ_HISTORICO, padrao=[])


def salvar_historico_deliberacoes(historico: list) -> None:
    """Persiste dados/historico_deliberacoes.json."""
    _salvar_json(_ARQ_HISTORICO, historico)


# ─── Operações principais ─────────────────────────────────────────────────────

def criar_ou_atualizar_deliberacao(item: dict) -> str:
    """
    Cria ou atualiza uma deliberação a partir de um item escalado.
    Idempotente: merge por id derivado de item_id.
    Retorna o id da deliberação.
    """
    deliberacoes = carregar_deliberacoes()
    historico    = carregar_historico_deliberacoes()
    agora        = datetime.now().isoformat(timespec="seconds")

    item_id  = item.get("item_id", "")
    delib_id = _id_deliberacao(item_id)

    index = {d["id"]: idx for idx, d in enumerate(deliberacoes)}

    if delib_id in index:
        d = deliberacoes[index[delib_id]]
        if d.get("status") == "pendente":
            d["descricao"]           = item.get("descricao", d["descricao"])
            d["contexto_resumido"]   = item.get("descricao", d.get("contexto_resumido", ""))[:200]
            d["urgencia"]            = item.get("urgencia", d["urgencia"])
            d["recomendacao_agente"] = item.get("acao_sugerida", d.get("recomendacao_agente", ""))
            d["atualizado_em"]       = agora
            deliberacoes[index[delib_id]] = d
            historico.append(_evento(delib_id, "deliberacao_atualizada",
                f"Atualizada via {item.get('agente_origem', '?')}", item.get("agente_origem", "sistema")))
    else:
        nova = {
            "id":                  delib_id,
            "agente_origem":       item.get("agente_origem", "?"),
            "tipo":                item.get("tipo", ""),
            "titulo":              _gerar_titulo(item),
            "descricao":           item.get("descricao", ""),
            "contexto_resumido":   item.get("descricao", "")[:200],
            "impacto":             _inferir_impacto(item),
            "urgencia":            item.get("urgencia", "media"),
            "recomendacao_agente": item.get("acao_sugerida", ""),
            "alternativas":        [],
            "status":              "pendente",
            "referencia_ids":      [item_id],
            "criado_em":           agora,
            "atualizado_em":       agora,
            "resolvido_em":        None,
            "decisao_conselho":    None,
            "observacao_conselho": None,
        }
        deliberacoes.append(nova)
        historico.append(_evento(delib_id, "deliberacao_criada",
            f"Criada a partir de {item_id} por {item.get('agente_origem', '?')}",
            item.get("agente_origem", "sistema")))

    salvar_deliberacoes(deliberacoes)
    salvar_historico_deliberacoes(historico)
    return delib_id


def registrar_evento_deliberacao(
    deliberacao_id: str,
    evento: str,
    descricao: str,
    origem: str,
) -> None:
    """Registra um evento no histórico. Carrega e salva o arquivo."""
    historico = carregar_historico_deliberacoes()
    historico.append(_evento(deliberacao_id, evento, descricao, origem))
    salvar_historico_deliberacoes(historico)


def marcar_como_deliberada(deliberacao_id: str, decisao: str, observacao: str = "") -> bool:
    """
    Marca deliberação como deliberada pelo conselho.
    Retorna True se encontrada e atualizada.
    decisao: texto livre (ex: "Cobrar Padaria urgentemente — prazo 48h")
    """
    deliberacoes = carregar_deliberacoes()
    agora        = datetime.now().isoformat(timespec="seconds")
    for d in deliberacoes:
        if d["id"] == deliberacao_id and d["status"] in ("pendente", "em_analise"):
            d["status"]              = "deliberado"
            d["decisao_conselho"]    = decisao
            d["observacao_conselho"] = observacao
            d["resolvido_em"]        = agora
            d["atualizado_em"]       = agora
            salvar_deliberacoes(deliberacoes)
            registrar_evento_deliberacao(deliberacao_id, "deliberacao_deliberada",
                f"Decisao: {decisao[:100]}", "conselho")
            return True
    return False


def marcar_como_aplicada(deliberacao_id: str) -> bool:
    """
    Marca deliberação como aplicada (decisão refletida no estado dos agentes).
    Retorna True se encontrada e atualizada.
    """
    deliberacoes = carregar_deliberacoes()
    agora        = datetime.now().isoformat(timespec="seconds")
    for d in deliberacoes:
        if d["id"] == deliberacao_id and d["status"] == "deliberado":
            d["status"]        = "aplicado"
            d["atualizado_em"] = agora
            salvar_deliberacoes(deliberacoes)
            registrar_evento_deliberacao(deliberacao_id, "decisao_aplicada",
                "Decisao refletida no estado dos agentes", "sistema")
            return True
    return False


def consolidar_deliberacoes_equivalentes() -> int:
    """
    Consolida deliberações com mesmo tipo e mesma contraparte ainda pendentes.
    Mantém a mais recente como primária, arquiva as demais com referencia_ids merged.
    Retorna número de consolidações feitas.
    """
    deliberacoes = carregar_deliberacoes()
    historico    = carregar_historico_deliberacoes()
    agora        = datetime.now().isoformat(timespec="seconds")
    consolidadas = 0

    grupos = {}
    for d in deliberacoes:
        if d.get("status") not in ("pendente", "em_analise"):
            continue
        contraparte = _extrair_contraparte(d.get("descricao", ""))
        if not contraparte:
            continue
        chave = (d.get("tipo", ""), contraparte)
        grupos.setdefault(chave, []).append(d)

    for grupo in grupos.values():
        if len(grupo) < 2:
            continue
        grupo_sorted = sorted(grupo, key=lambda x: x.get("criado_em", ""), reverse=True)
        primaria = grupo_sorted[0]
        for duplicata in grupo_sorted[1:]:
            refs = primaria.get("referencia_ids", [])
            for r in duplicata.get("referencia_ids", []):
                if r not in refs:
                    refs.append(r)
            primaria["referencia_ids"] = refs
            primaria["atualizado_em"]  = agora
            duplicata["status"]        = "arquivado"
            duplicata["atualizado_em"] = agora
            historico.append(_evento(duplicata["id"], "deliberacao_arquivada",
                f"Consolidada em {primaria['id']}", "sistema"))
            consolidadas += 1

    if consolidadas:
        salvar_deliberacoes(deliberacoes)
        salvar_historico_deliberacoes(historico)
    return consolidadas


def buscar_deliberacao_por_item_id(item_id: str):
    """
    Busca a deliberação correspondente a um item_id.
    Procura por id derivado e também em referencia_ids (itens consolidados).
    Retorna dict ou None.
    """
    delib_id = _id_deliberacao(item_id)
    for d in carregar_deliberacoes():
        if d["id"] == delib_id or item_id in d.get("referencia_ids", []):
            return d
    return None


# ─── Internos ─────────────────────────────────────────────────────────────────

def _id_deliberacao(item_id: str) -> str:
    return f"delib_{item_id}"


def _id_evento(deliberacao_id: str, evento: str, ts: str) -> str:
    chave = f"{deliberacao_id}|{evento}|{ts}"
    return "ev_" + hashlib.md5(chave.encode()).hexdigest()[:12]


def _evento(deliberacao_id: str, evento: str, descricao: str, origem: str) -> dict:
    agora = datetime.now().isoformat(timespec="seconds")
    return {
        "id":             _id_evento(deliberacao_id, evento, agora),
        "deliberacao_id": deliberacao_id,
        "evento":         evento,
        "descricao":      descricao,
        "origem":         origem,
        "registrado_em":  agora,
    }


def _gerar_titulo(item: dict) -> str:
    tipo        = item.get("tipo", "item")
    desc        = item.get("descricao", "")
    contraparte = _extrair_contraparte(desc)
    return f"{tipo} — {contraparte}" if contraparte else (desc[:80] or tipo)


def _inferir_impacto(item: dict) -> str:
    urgencia = item.get("urgencia", "")
    if urgencia in ("imediata", "alta"):
        return "alto"
    if urgencia == "media":
        return "medio"
    return "baixo"


def _extrair_contraparte(descricao: str) -> str:
    """Extrai texto antes de '—' como identificador de contraparte."""
    if "\u2014" in descricao:
        return descricao.split("\u2014")[0].strip()
    if " - " in descricao:
        return descricao.split(" - ")[0].strip()
    return ""


def _carregar_json(nome: str, padrao):
    caminho = config.PASTA_DADOS / nome
    if not caminho.exists():
        return padrao
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def _salvar_json(nome: str, dados) -> None:
    import os
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = config.PASTA_DADOS / nome
    conteudo = json.dumps(dados, ensure_ascii=False, indent=2)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)
