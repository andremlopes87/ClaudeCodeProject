"""
modulos/entrega/processador_insumos_entrega.py

Aplica insumos registrados em insumos_entrega.json sobre checklists e
pipeline_entrega. Nao inventa fatos. Aplica apenas o que estiver
explicitamente registrado com status_aplicacao=pendente.

Mapa de aplicacao:
  contato_confirmado      → desbloqueia sem_contato_principal + conclui ck_contato*
  objetivo_confirmado     → conclui ck_objetivo_prioritario / ck_expectativa
  canal_confirmado        → conclui ck_canais_existentes
  ativo_digital_confirmado→ conclui ck_ativo_digital
  escopo_confirmado       → conclui ck_escopo_inicial / ck_escopo_basico / ck_escopo_servico
  documento_recebido      → registra evidencia no item correspondente
  bloqueio_resolvido      → remove bloqueio pelo tipo informado na chave
  resposta_cliente        → registra contexto nas observacoes (nao conclui item sozinho)
  contexto_adicional      → registra contexto nas observacoes (nao conclui item sozinho)

Transicoes de status_entrega:
  aguardando_insumo → onboarding   quando todos os bloqueios criticos forem removidos
  onboarding        → planejada    quando itens obrigatorios principais estiverem pronto/concluido
  planejada         → em_execucao  quando escopo confirmado e sem bloqueios criticos
  em_execucao       → concluida    quando todos os itens obrigatorios estiverem concluidos
"""

from datetime import datetime

import config

# ─── Mapa tipo_insumo → ids de checklist item que ele resolve ─────────────────

_MAPA_TIPO_ITEM = {
    "contato_confirmado":       ["ck_contato_principal", "ck_contato_responsavel"],
    "objetivo_confirmado":      ["ck_objetivo_prioritario", "ck_expectativa"],
    "canal_confirmado":         ["ck_canais_existentes"],
    "ativo_digital_confirmado": ["ck_ativo_digital"],
    "escopo_confirmado":        ["ck_escopo_inicial", "ck_escopo_basico", "ck_escopo_servico"],
    "documento_recebido":       [],   # aplica pelo campo chave
    "bloqueio_resolvido":       [],   # aplica pelo campo chave
    "resposta_cliente":         [],   # so registra contexto
    "contexto_adicional":       [],   # so registra contexto
}

# Bloqueios que insumos podem remover
_BLOQUEIO_POR_TIPO_INSUMO = {
    "contato_confirmado":       "sem_contato_principal",
    "ativo_digital_confirmado": "sem_contexto_digital",
    "escopo_confirmado":        "sem_contexto_digital",
}

# Itens que, quando prontos, destravam o planejamento
_ITENS_CRITICOS_PLANEJAMENTO = {
    "ck_escopo_inicial", "ck_escopo_basico", "ck_escopo_servico",
}

# Bloqueios que impedem transicao para em_execucao
_BLOQUEIOS_CRITICOS = {"sem_contato_principal"}


# ─── API pública ──────────────────────────────────────────────────────────────

def carregar_insumos_pendentes(insumos: list) -> list:
    """Filtra insumos com status_aplicacao=pendente."""
    return [i for i in insumos if i.get("status_aplicacao") == "pendente"]


def aplicar_insumo_na_entrega(
    insumo: dict,
    entrega: dict,
    checklist: dict,
    historico: list,
    log,
) -> bool:
    """
    Aplica um insumo sobre a entrega e seu checklist.
    Modifica entrega, checklist e historico in-place.
    Retorna True se algo mudou.
    """
    tipo  = insumo.get("tipo_insumo", "")
    chave = insumo.get("chave", "")
    valor = insumo.get("valor", "")
    desc  = insumo.get("descricao", "")

    mudou = False

    # 1. Tentar aplicar no checklist
    mudou_ck = atualizar_checklist_por_insumo(insumo, checklist, log)
    mudou = mudou or mudou_ck

    # 2. Remover bloqueio correspondente da entrega
    tipo_bloqueio = _BLOQUEIO_POR_TIPO_INSUMO.get(tipo)
    if tipo_bloqueio:
        mudou_bl = _remover_bloqueio_entrega(entrega, tipo_bloqueio, log)
        mudou = mudou or mudou_bl

    # bloqueio_resolvido usa a chave como tipo de bloqueio a remover
    if tipo == "bloqueio_resolvido" and chave:
        mudou_bl = _remover_bloqueio_entrega(entrega, chave, log)
        mudou = mudou or mudou_bl

    # 3. Para insumos de contexto: registrar nas observacoes do primeiro item pendente
    if tipo in ("resposta_cliente", "contexto_adicional") and desc:
        for item in checklist.get("itens", []):
            if item.get("status") == "pendente":
                obs_atual = item.get("observacoes", "")
                item["observacoes"] = (obs_atual + f" | {desc}").strip(" |")
                item["atualizado_em"] = _agora()
                mudou = True
                break

    # 4. Atualizar ultimo_insumo_em na entrega
    if mudou:
        entrega["ultimo_insumo_em"] = _agora()
        entrega["atualizado_em"]    = _agora()
        registrar_historico_insumo(
            entrega["id"], insumo, historico,
            f"Insumo '{tipo}' aplicado — {desc[:60]}" if desc else f"Insumo '{tipo}' aplicado",
        )

    return mudou


def mapear_insumo_para_item_checklist(insumo: dict) -> list:
    """
    Retorna lista de item_ids do checklist que este insumo pode resolver.
    Para documento_recebido, usa o campo chave diretamente.
    """
    tipo  = insumo.get("tipo_insumo", "")
    chave = insumo.get("chave", "")

    if tipo == "documento_recebido" and chave:
        return [chave]
    return _MAPA_TIPO_ITEM.get(tipo, [])


def atualizar_checklist_por_insumo(insumo: dict, checklist: dict, log) -> bool:
    """
    Marca itens do checklist como 'pronto' quando o insumo os resolve.
    Respeita depende_de: nao conclui item com dependencia ainda pendente.
    Retorna True se algum item mudou.
    """
    item_ids = mapear_insumo_para_item_checklist(insumo)
    if not item_ids:
        return False

    agora   = _agora()
    mudou   = False
    ids_set = set(item_ids)

    # indice de status por id para verificar dependencias
    status_por_id = {it["id"]: it.get("status", "pendente") for it in checklist.get("itens", [])}

    for item in checklist.get("itens", []):
        if item["id"] not in ids_set:
            continue
        if item.get("status") in ("pronto", "concluido", "dispensado"):
            continue
        dep = item.get("depende_de")
        if dep and status_por_id.get(dep) not in ("pronto", "concluido", "dispensado"):
            log.info(f"    [checklist] {item['id']} aguarda dependencia {dep}")
            continue

        # Adicionar evidencia
        evidencias = item.setdefault("evidencias", [])
        evidencias.append({
            "insumo_id":  insumo.get("id", ""),
            "tipo":       insumo.get("tipo_insumo", ""),
            "valor":      str(insumo.get("valor", ""))[:100],
            "registrado_em": agora,
        })
        item["status"]       = "pronto"
        item["atualizado_em"] = agora
        mudou = True
        log.info(f"    [checklist] {item['id']} → pronto (insumo: {insumo.get('tipo_insumo')})")

    if mudou:
        checklist["atualizado_em"] = agora
    return mudou


def atualizar_pipeline_entrega_por_checklist(entrega: dict, checklist: dict, log) -> bool:
    """
    Recalcula status_entrega e percentual_conclusao com base no checklist atual.
    Aplica transicoes seguras sem pular etapas sem base objetiva.
    Retorna True se o status mudou.
    """
    itens         = checklist.get("itens", [])
    obrigatorios  = [i for i in itens if i.get("obrigatorio", True)]
    total_obrig   = len(obrigatorios)
    prontos       = sum(1 for i in obrigatorios if i.get("status") in ("pronto", "concluido"))
    concluidos    = sum(1 for i in obrigatorios if i.get("status") == "concluido")
    bloqueios     = entrega.get("bloqueios", [])
    bloqueios_criticos = [b for b in bloqueios if b.get("tipo") in _BLOQUEIOS_CRITICOS]

    pct = int((prontos / total_obrig * 100)) if total_obrig else 0
    entrega["percentual_conclusao"] = pct

    status_atual = entrega.get("status_entrega", "onboarding")
    novo_status  = status_atual

    if status_atual == "aguardando_insumo" and not bloqueios_criticos:
        novo_status = "onboarding"

    elif status_atual == "onboarding":
        # Maioria dos obrigatorios principais prontos → planejada
        itens_criticos_ok = all(
            any(i["id"] == cid and i.get("status") in ("pronto", "concluido")
                for i in itens)
            for cid in _ITENS_CRITICOS_PLANEJAMENTO
            if any(i["id"] == cid for i in itens)
        )
        if itens_criticos_ok or pct >= 60:
            novo_status = "planejada"

    elif status_atual == "planejada" and not bloqueios_criticos:
        # Escopo confirmado e maioria pronta → em_execucao
        escopo_ok = any(
            i["id"] in _ITENS_CRITICOS_PLANEJAMENTO and i.get("status") in ("pronto", "concluido")
            for i in itens
        )
        if escopo_ok and pct >= 40:
            novo_status = "em_execucao"

    elif status_atual == "em_execucao":
        if concluidos == total_obrig and total_obrig > 0:
            novo_status = "concluida"

    if novo_status != status_atual:
        entrega["status_entrega"] = novo_status
        entrega["atualizado_em"]  = _agora()
        log.info(f"  [entrega] {entrega['id']} status: {status_atual} → {novo_status} ({pct}%)")
        return True

    log.info(f"  [entrega] {entrega['id']} status mantido: {status_atual} ({pct}%)")
    return False


def registrar_historico_insumo(entrega_id: str, insumo: dict, historico: list, descricao: str) -> None:
    """Adiciona evento de aplicacao de insumo ao historico (in-place)."""
    historico.append({
        "id":            f"hev_{entrega_id}_insumo_{len(historico)}",
        "entrega_id":    entrega_id,
        "evento":        "insumo_aplicado",
        "insumo_id":     insumo.get("id", ""),
        "tipo_insumo":   insumo.get("tipo_insumo", ""),
        "descricao":     descricao,
        "origem":        insumo.get("origem", "externo"),
        "registrado_em": _agora(),
    })


def marcar_insumo_como_aplicado(insumo: dict, mudou: bool) -> None:
    """
    Atualiza status_aplicacao e aplicado_em do insumo in-place.
    Se nao mudou nada, marca como ignorado.
    """
    insumo["status_aplicacao"] = "aplicado" if mudou else "ignorado"
    insumo["aplicado_em"]      = _agora()


# ─── Auxiliares ───────────────────────────────────────────────────────────────

def _remover_bloqueio_entrega(entrega: dict, tipo_bloqueio: str, log) -> bool:
    antes = entrega.get("bloqueios", [])
    depois = [b for b in antes if b.get("tipo") != tipo_bloqueio]
    if len(depois) < len(antes):
        entrega["bloqueios"] = depois
        log.info(f"  [bloqueio removido] {tipo_bloqueio} em {entrega['id']}")
        return True
    return False


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")
