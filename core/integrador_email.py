"""
core/integrador_email.py — Integrador do canal de email assistido (v0.42).

Converte execuções prontas com canal=email (fila_execucao_contato.json)
em emails preparados (fila_envio_email.json) para revisão pelo conselho.

Modo desta etapa: assistido — o sistema prepara e para.
Nunca envia nada. simulado=True em todos os registros.

Fluxo:
  fila_execucao_contato (canal=email, pronto=True)
    → preparar_email_para_execucao()
    → fila_envio_email.json  (status: preparado | bloqueado)
    → historico_email.json
    → estado_canal_email.json

Identidade lida exclusivamente de:
  core/identidade_empresa.py (carregar_identidade, carregar_guia_comunicacao,
                               carregar_assinaturas, carregar_canais)
  dados/config_canal_email.json
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import config

_ARQ_FILA_EXEC    = "fila_execucao_contato.json"
_ARQ_FILA_EMAIL   = "fila_envio_email.json"
_ARQ_HISTORICO    = "historico_email.json"
_ARQ_ESTADO       = "estado_canal_email.json"
_ARQ_CONFIG       = "config_canal_email.json"

_STATUS_ELEGIVEL  = "aguardando_integracao_canal"
_STATUS_PROCESSADO = "email_preparado"

_PASTA_LOGS = config.PASTA_LOGS / "empresa"

_CONFIG_PADRAO = {
    "modo":                        "assistido",
    "habilitado":                  True,
    "nome_remetente":              "",
    "email_remetente_planejado":   "",
    "responder_para_planejado":    "",
    "assunto_prefixo":             "",
    "assinatura_tipo_padrao":      "comercial",
    "usar_html":                   False,
    "exigir_email_destino":        True,
    "limite_preparos_por_ciclo":   50,
    "observacoes":                 "",
    "criado_em":                   None,
    "atualizado_em":               None,
}


# ─── Ponto de entrada público ─────────────────────────────────────────────────

def executar() -> dict:
    """
    Ponto de entrada para o orquestrador.
    Prepara emails para execuções elegíveis. Persiste em fila_envio_email.json.
    Retorna resumo da integração.
    """
    ts  = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log = _configurar_log(ts)

    log.info("=" * 60)
    log.info(f"INTEGRADOR EMAIL [assistido] — {ts}")
    log.info("=" * 60)

    config_canal  = carregar_config_canal_email()
    modo          = config_canal.get("modo", "desativado")
    habilitado    = config_canal.get("habilitado", False)

    # Guard: modo=real exige todos os pré-requisitos de provisionamento
    if modo == "real":
        try:
            from core.provisionamento_canais import validar_modo_real_permitido, registrar_evento_provisionamento
            permitido, motivo = validar_modo_real_permitido()
            if not permitido:
                log.warning(f"modo=real BLOQUEADO: {motivo} — operando em modo=assistido")
                registrar_evento_provisionamento(
                    "ativacao_real_bloqueada",
                    f"Tentativa de modo=real bloqueada: {motivo}",
                    "integrador_email",
                )
                modo = "assistido"
        except Exception as _exc_prov:
            log.warning(f"Verificação de provisionamento falhou: {_exc_prov} — mantendo modo={modo}")

    if not habilitado or modo == "desativado":
        log.info(f"Canal email desativado (modo={modo}, habilitado={habilitado}) — pulando")
        return {
            "modo":              modo,
            "habilitado":        habilitado,
            "execucoes_lidas":   0,
            "preparados":        0,
            "bloqueados":        0,
            "ja_na_fila":        0,
            "limite_atingido":   False,
        }

    # Identidade da empresa
    identidade, guia, assinaturas, canais = _carregar_identidade_completa(log)

    # Governança: checar pausas
    governanca = _carregar_governanca_seguro()
    agentes_pausados = set(governanca.get("agentes_pausados", []))
    areas_pausadas   = set(governanca.get("areas_pausadas", []))
    modo_empresa     = governanca.get("modo_empresa", "normal")

    if _governanca_bloqueia_email(agentes_pausados, areas_pausadas, modo_empresa, log):
        return {
            "modo":              modo,
            "habilitado":        habilitado,
            "execucoes_lidas":   0,
            "preparados":        0,
            "bloqueados":        0,
            "ja_na_fila":        0,
            "limite_atingido":   False,
            "bloqueado_governanca": True,
        }

    execucoes     = carregar_execucoes_email_elegiveis()
    fila_email    = _carregar_json(_ARQ_FILA_EMAIL, [])
    historico     = _carregar_json(_ARQ_HISTORICO, [])
    estado        = _carregar_estado()

    # IDs já na fila para evitar duplicatas
    ids_na_fila   = {e["execucao_id"] for e in fila_email}

    limite     = config_canal.get("limite_preparos_por_ciclo", 50)
    n_preparados  = 0
    n_bloqueados  = 0
    n_ja_na_fila  = 0
    limite_atingido = False

    log.info(
        f"Execucoes elegiveis: {len(execucoes)} | "
        f"Ja na fila: {len(ids_na_fila)} | "
        f"Limite por ciclo: {limite}"
    )

    from conectores.canal_email_assistido import (
        preparar_email_para_execucao,
        registrar_historico_email,
    )

    for execucao in execucoes:
        exec_id = execucao["id"]

        if exec_id in ids_na_fila:
            log.info(f"  [ja_na_fila] {exec_id} — email já preparado anteriormente")
            n_ja_na_fila += 1
            continue

        if n_preparados >= limite:
            log.warning(f"  [limite] Limite de {limite} preparos por ciclo atingido — parando")
            limite_atingido = True
            break

        email = preparar_email_para_execucao(
            execucao, identidade, guia, assinaturas, canais, config_canal
        )
        fila_email.append(email)
        ids_na_fila.add(exec_id)

        if email["status"] == "preparado":
            atualizar_execucao_apos_preparo(execucao)
            n_preparados += 1
            evento = "email_assistido_preparado"
            log.info(
                f"  [preparado] {exec_id} | "
                f"{execucao.get('contraparte', '?')[:30]} | "
                f"destino={email['email_destino'] or '?'}"
            )
        else:
            n_bloqueados += 1
            evento = "email_assistido_bloqueado"
            log.info(
                f"  [bloqueado] {exec_id} | "
                f"{execucao.get('contraparte', '?')[:30]} | "
                f"motivo={email.get('motivo_bloqueio', '?')}"
            )

        registrar_historico_email(
            historico,
            tipo_evento=evento,
            execucao_id=exec_id,
            oportunidade_id=execucao.get("oportunidade_id", ""),
            descricao=(
                f"email_id={email['id']} | contraparte={execucao.get('contraparte', '?')} | "
                f"motivo_bloqueio={email.get('motivo_bloqueio') or '-'}"
            ),
            status=email["status"],
        )

    # Persistir
    _salvar_json(_ARQ_FILA_EMAIL, fila_email)
    _salvar_json(_ARQ_HISTORICO, historico)
    _salvar_fila_exec(execucoes)

    estado = atualizar_estado_canal_email(estado, n_preparados, n_bloqueados, fila_email, config_canal)
    _salvar_json(_ARQ_ESTADO, estado)

    log.info(
        f"Preparados: {n_preparados} | Bloqueados: {n_bloqueados} | "
        f"Ja na fila: {n_ja_na_fila} | Limite atingido: {limite_atingido}"
    )
    log.info("=" * 60)

    return {
        "modo":              modo,
        "habilitado":        habilitado,
        "execucoes_lidas":   len(execucoes),
        "preparados":        n_preparados,
        "bloqueados":        n_bloqueados,
        "ja_na_fila":        n_ja_na_fila,
        "limite_atingido":   limite_atingido,
    }


# ─── Funções públicas ─────────────────────────────────────────────────────────

def carregar_execucoes_email_elegiveis() -> list:
    """
    Carrega execuções com canal=email e pronto_para_integracao=True.
    Aceita status aguardando_integracao_canal ou email_preparado (para reprocessamento).
    """
    todas = _carregar_json(_ARQ_FILA_EXEC, [])
    return [
        e for e in todas
        if e.get("canal") == "email"
        and e.get("pronto_para_integracao")
        and e.get("status") == _STATUS_ELEGIVEL
    ]


def carregar_config_canal_email() -> dict:
    """Carrega config_canal_email.json. Cria com padrões se ausente."""
    arq = config.PASTA_DADOS / _ARQ_CONFIG
    if not arq.exists():
        cfg = dict(_CONFIG_PADRAO)
        agora = datetime.now().isoformat(timespec="seconds")
        cfg["criado_em"]    = agora
        cfg["atualizado_em"] = agora
        config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
        with open(arq, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return cfg
    with open(arq, "r", encoding="utf-8") as f:
        return json.load(f)


def gerar_fila_envio_email() -> list:
    """Retorna a fila_envio_email.json atual (leitura direta)."""
    return _carregar_json(_ARQ_FILA_EMAIL, [])


def atualizar_estado_canal_email(
    estado: dict,
    n_preparados: int,
    n_bloqueados: int,
    fila_email: list,
    config_canal: dict,
) -> dict:
    """Atualiza e retorna o dict de estado_canal_email."""
    agora = datetime.now().isoformat(timespec="seconds")

    total_na_fila         = len(fila_email)
    total_preparados      = sum(1 for e in fila_email if e.get("status") == "preparado")
    total_bloqueados      = sum(1 for e in fila_email if e.get("status") == "bloqueado")
    aguardando_revisao    = sum(1 for e in fila_email if e.get("status") in ("preparado", "pronto_para_revisao"))
    aprovados_futuro      = sum(1 for e in fila_email if e.get("status") == "aprovado_para_envio_futuro")

    estado["ultima_execucao"]      = agora
    estado["modo"]                 = config_canal.get("modo", "assistido")
    estado["habilitado"]           = config_canal.get("habilitado", False)
    estado["remetente_planejado"]  = (
        config_canal.get("email_remetente_planejado") or ""
    )
    estado["contadores"]           = {
        "total_na_fila":         total_na_fila,
        "preparados_acumulado":  total_preparados,
        "bloqueados_acumulado":  total_bloqueados,
        "aguardando_revisao":    aguardando_revisao,
        "aprovados_para_envio_futuro": aprovados_futuro,
    }
    estado["ultimo_ciclo"]         = {
        "preparados":    n_preparados,
        "bloqueados":    n_bloqueados,
        "registrado_em": agora,
    }
    return estado


def atualizar_execucao_apos_preparo(execucao: dict) -> None:
    """Atualiza status da execução in-place após preparo do email."""
    execucao["status"]                = _STATUS_PROCESSADO
    execucao["pronto_para_integracao"] = False
    execucao["atualizado_em"]         = datetime.now().isoformat(timespec="seconds")


def registrar_eventos_email_assistido(
    historico: list,
    evento: str,
    execucao_id: str,
    oportunidade_id: str,
    descricao: str,
    status: str,
) -> None:
    """Registra evento no historico_email.json (in-place). Wrapper para uso externo."""
    from conectores.canal_email_assistido import registrar_historico_email
    registrar_historico_email(historico, evento, execucao_id, oportunidade_id, descricao, status)


def respeitar_governanca_e_politicas(config_canal: dict, governanca: dict) -> tuple[bool, str]:
    """
    Verifica se o canal email deve processar dado o estado de governança.
    Retorna (pode_processar, motivo_bloqueio).
    """
    agentes_pausados = set(governanca.get("agentes_pausados", []))
    areas_pausadas   = set(governanca.get("areas_pausadas", []))
    modo_empresa     = governanca.get("modo_empresa", "normal")

    if "integrador_email" in agentes_pausados:
        return False, "integrador_email pausado pelo conselho"
    if "comercial" in areas_pausadas:
        return False, "area comercial pausada pelo conselho"
    if modo_empresa == "pausado":
        return False, f"empresa em modo_empresa='{modo_empresa}'"
    if not config_canal.get("habilitado", False):
        return False, "canal email habilitado=False em config_canal_email"
    if config_canal.get("modo", "desativado") == "desativado":
        return False, "canal email modo=desativado"
    return True, ""


# ─── Internos ─────────────────────────────────────────────────────────────────

def _carregar_identidade_completa(log) -> tuple[dict, dict, dict, dict]:
    """Carrega todos os dicts de identidade via core/identidade_empresa.py."""
    try:
        from core.identidade_empresa import (
            carregar_identidade,
            carregar_guia_comunicacao,
            carregar_assinaturas,
            carregar_canais,
        )
        identidade  = carregar_identidade()
        guia        = carregar_guia_comunicacao()
        assinaturas = carregar_assinaturas()
        canais      = carregar_canais()
        log.info(
            f"Identidade carregada: empresa='{identidade.get('nome_exibicao') or identidade.get('nome_oficial', '?')}'"
        )
        return identidade, guia, assinaturas, canais
    except Exception as exc:
        log.warning(f"Erro ao carregar identidade — usando vazios: {exc}")
        return {}, {}, {}, {}


def _governanca_bloqueia_email(
    agentes_pausados: set, areas_pausadas: set, modo_empresa: str, log
) -> bool:
    if "integrador_email" in agentes_pausados:
        log.info("integrador_email PAUSADO pela governança — pulando")
        return True
    if "comercial" in areas_pausadas:
        log.info("area 'comercial' PAUSADA pela governança — pulando email")
        return True
    if modo_empresa == "pausado":
        log.info(f"modo_empresa='{modo_empresa}' — pulando email")
        return True
    return False


def _carregar_governanca_seguro() -> dict:
    try:
        from core.governanca_conselho import carregar_estado_governanca
        return carregar_estado_governanca()
    except Exception:
        return {}


def _carregar_estado() -> dict:
    estado = _carregar_json(_ARQ_ESTADO, None)
    if estado is None:
        return {
            "ultima_execucao":     None,
            "modo":                "assistido",
            "habilitado":          False,
            "remetente_planejado": "",
            "contadores":          {},
            "ultimo_ciclo":        {},
        }
    return estado


def _salvar_fila_exec(execucoes_processadas: list) -> None:
    """
    Persiste execuções atualizadas na fila completa, preservando as não alteradas.
    """
    todas = _carregar_json(_ARQ_FILA_EXEC, [])
    idx   = {e["id"]: e for e in execucoes_processadas}
    for item in todas:
        if item["id"] in idx:
            item.update(idx[item["id"]])
    _salvar_json(_ARQ_FILA_EXEC, todas)


def _configurar_log(ts: str) -> logging.Logger:
    _PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    caminho = _PASTA_LOGS / f"integrador_email_{ts}.log"
    nome    = f"integrador_email_{ts}"
    log     = logging.getLogger(nome)
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        fh = logging.FileHandler(caminho, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        log.addHandler(sh)
    return log


def _carregar_json(nome: str, padrao):
    caminho = config.PASTA_DADOS / nome
    if not caminho.exists():
        return padrao
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def _salvar_json(nome: str, dados) -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = config.PASTA_DADOS / nome
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
