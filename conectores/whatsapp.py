"""
conectores/whatsapp.py — Conector WhatsApp Business completo em dry-run (v1.0).

Lógica 100% implementada; envio real ativado trocando config:
  dados/config_canal_whatsapp.json  →  "modo": "real"  +  "api_token": "<token>"

Responsabilidades:
  - Normalizar e validar número de destino (+55DDNNNNNNNNN)
  - Validar janela de horário e dias permitidos
  - Verificar cooldown por contato (padrão: 24h)
  - Verificar limite diário de mensagens
  - Selecionar template conforme tipo de abordagem
  - Personalizar variáveis via LLM (fallback: valores genéricos)
  - Gerar preview completo do que SERIA enviado
  - Enfileirar na fila_envio_whatsapp.json (modo assistido)
  - POST real para WhatsApp Business API (modo real — futuro)

Segurança:
  - Se modo="real" mas api_token=null → opera como dry-run com alerta
  - Nunca envia sem configuração completa
  - Cooldown e limite diário aplicados independente do modo

Templates aprovados pelo Meta (modelados conforme regras da API):
  abordagem_inicial | followup | proposta | nps
"""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQUIVO_CONFIG  = config.PASTA_DADOS / "config_canal_whatsapp.json"
_ARQUIVO_FILA    = config.PASTA_DADOS / "fila_envio_whatsapp.json"
_ARQUIVO_ESTADO  = config.PASTA_DADOS / "estado_canais.json"

# Textos dos templates para preview local (não são enviados à API — a API usa templates aprovados)
_TEMPLATES_TEXTO: dict[str, str] = {
    "abordagem_inicial": (
        "Ola, {nome_contato}!\n\n"
        "Somos a Vetor — ajudamos {nome_empresa} a resolver {problema_principal} "
        "com automacoes simples e sem complicacao.\n\n"
        "Podemos conversar 5 minutinhos?"
    ),
    "followup": (
        "Ola, {nome_contato}!\n\n"
        "Tentei contato anteriormente sobre {contexto_anterior}.\n\n"
        "Se quiser conversar em outro momento, e so me avisar. "
        "Equipe Vetor."
    ),
    "proposta": (
        "Ola, {nome_contato}!\n\n"
        "Preparei a proposta para {nome_pacote}: {valor}.\n\n"
        "Posso enviar os detalhes por aqui?"
    ),
    "nps": (
        "Ola, {nome_contato}!\n\n"
        "Como voce avalia o servico que entregamos — {servico_entregue}?\n\n"
        "De 0 a 10, qual nota voce daria? Sua opiniao e muito importante para nos. "
        "Equipe Vetor."
    ),
}

# Mapeamento de tipo_acao/abordagem → nome do template
_TIPO_PARA_TEMPLATE: dict[str, str] = {
    "exploratoria":           "abordagem_inicial",
    "consultiva_diagnostica": "abordagem_inicial",
    "padrao":                 "abordagem_inicial",
    "followup_sem_resposta":  "followup",
    "reengajamento":          "followup",
    "proposta_comercial":     "proposta",
    "nps":                    "nps",
    "pos_entrega":            "nps",
}

# Dias da semana em português abreviado
_DIAS_PT: dict[int, str] = {0: "seg", 1: "ter", 2: "qua", 3: "qui", 4: "sex", 5: "sab", 6: "dom"}


# ─── Classe principal ─────────────────────────────────────────────────────────

class CanalWhatsApp:
    """
    Conector WhatsApp Business.

    Implementa a interface de core.canais.CanalBase via duck typing para evitar
    importação circular. Registrado em core/canais.CANAIS_DISPONIVEIS["whatsapp"].
    """

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def nome(self) -> str:
        return "whatsapp"

    @property
    def modo(self) -> str:
        cfg = _carregar_config()
        _modo = cfg.get("modo", "dry-run")
        # Segurança: forçar dry-run se token ausente no modo real
        if _modo == "real" and not cfg.get("api_token"):
            log.warning("[whatsapp] modo=real mas api_token=null — operando como dry-run")
            return "dry-run"
        return _modo

    # ── preparar_envio ────────────────────────────────────────────────────────

    def preparar_envio(self, payload: dict) -> dict:
        """
        Prepara envio WhatsApp. Valida, seleciona template, personaliza via LLM.

        Retorna dict com:
          status           — "preparado" | "simulado" | "bloqueado" | "agendado"
          preview          — mensagem completa que seria enviada
          canal, modo, simulado, pronto_para_envio
          motivo_bloqueio  — razão se não preparado
          template_nome    — nome do template Meta selecionado
          variaveis        — dict com variáveis preenchidas
          numero_normalizado
          agendado_para    — ISO 8601 se fora de horário
          preparado_em
        """
        agora  = datetime.now()
        cfg    = _carregar_config()
        _modo  = self.modo

        resultado = {
            "status":             "simulado",
            "preview":            "",
            "canal":              "whatsapp",
            "modo":               _modo,
            "simulado":           True,
            "pronto_para_envio":  False,
            "motivo_bloqueio":    None,
            "template_nome":      None,
            "variaveis":          {},
            "numero_normalizado": None,
            "agendado_para":      None,
            "preparado_em":       agora.isoformat(timespec="seconds"),
            "payload_original":   payload,
        }

        # 1. Validar número de destino
        numero_raw = _extrair_numero(payload)
        numero, err_numero = normalizar_numero(numero_raw)
        if err_numero:
            resultado["status"]          = "bloqueado"
            resultado["motivo_bloqueio"] = f"numero_invalido: {err_numero} (recebido: '{numero_raw}')"
            return resultado
        resultado["numero_normalizado"] = numero

        # 2. Verificar horário e dias permitidos
        permitido, prox_horario = _verificar_janela_horario(cfg, agora)
        if not permitido:
            resultado["status"]        = "agendado"
            resultado["agendado_para"] = prox_horario
            resultado["motivo_bloqueio"] = (
                f"fora_da_janela_horario: proximo envio permitido em {prox_horario}"
            )
            # Mesmo agendado, montar preview
            resultado["pronto_para_envio"] = False

        # 3. Verificar cooldown por contato
        fila = _carregar_fila()
        cooldown_h = cfg.get("cooldown_mesmo_contato_horas", 24)
        em_cooldown, ultimo_envio = _verificar_cooldown(numero, fila, cooldown_h)
        if em_cooldown:
            resultado["status"]          = "bloqueado"
            resultado["motivo_bloqueio"] = (
                f"cooldown_ativo: ultimo envio para {numero} em {ultimo_envio} "
                f"(cooldown={cooldown_h}h)"
            )
            return resultado

        # 4. Verificar limite diário
        limite_dia = cfg.get("max_mensagens_dia", 50)
        enviados_hoje = _contar_enviados_hoje(fila)
        if enviados_hoje >= limite_dia:
            resultado["status"]          = "bloqueado"
            resultado["motivo_bloqueio"] = (
                f"limite_diario_atingido: {enviados_hoje}/{limite_dia} mensagens hoje"
            )
            return resultado

        # 5. Selecionar template
        tipo_acao   = payload.get("abordagem_inicial_tipo") or payload.get("tipo_acao", "padrao")
        template_id = _TIPO_PARA_TEMPLATE.get(tipo_acao, "abordagem_inicial")
        template_cfg = cfg.get("templates_aprovados", {}).get(template_id, {})
        resultado["template_nome"] = template_cfg.get("nome_template", f"vetor_{template_id}_v1")

        # 6. Personalizar variáveis via LLM (fallback: genéricas)
        variaveis = _montar_variaveis(payload, template_id)
        variaveis_llm, usou_llm = _tentar_llm_variaveis(payload, template_id, variaveis)
        if usou_llm:
            variaveis = variaveis_llm
        resultado["variaveis"] = variaveis
        resultado["usou_llm"]  = usou_llm

        # 7. Montar preview da mensagem
        template_texto = _TEMPLATES_TEXTO.get(template_id, "")
        try:
            preview = template_texto.format(**variaveis)
        except KeyError as ke:
            preview = template_texto  # usa template sem substituição se faltar variável
            log.debug(f"[whatsapp] variavel ausente no template: {ke}")
        resultado["preview"] = preview

        # 8. Definir status final
        if resultado["status"] != "agendado":
            resultado["status"]           = "preparado" if _modo != "dry-run" else "simulado"
            resultado["pronto_para_envio"] = _modo != "dry-run"

        return resultado

    # ── enviar ────────────────────────────────────────────────────────────────

    def enviar(self, payload: dict) -> dict:
        """
        Executa envio conforme modo:
          dry-run   → simula, retorna resultado sem efeito externo
          assistido → enfileira em fila_envio_whatsapp.json para aprovação humana
          real      → POST WhatsApp Business API (requer api_token configurado)
        """
        preparado = self.preparar_envio(payload)
        _modo = self.modo
        agora = datetime.now().isoformat(timespec="seconds")

        if preparado["status"] == "bloqueado":
            return {
                "enviado":         False,
                "motivo":          preparado["motivo_bloqueio"],
                "modo":            _modo,
                "canal":           "whatsapp",
                "preview":         "",
                "registrado_em":   agora,
            }

        if _modo == "dry-run":
            return {
                "enviado":         False,
                "motivo":          "dry-run",
                "canal":           "whatsapp",
                "modo":            "dry-run",
                "simulado":        True,
                "preview":         preparado.get("preview", ""),
                "template_nome":   preparado.get("template_nome"),
                "variaveis":       preparado.get("variaveis", {}),
                "numero":          preparado.get("numero_normalizado"),
                "registrado_em":   agora,
            }

        if _modo == "assistido":
            item_fila = _montar_item_fila(preparado, payload, agora)
            fila = _carregar_fila()
            fila.append(item_fila)
            _salvar_fila(fila)
            log.info(
                f"[whatsapp] enfileirado {item_fila['id']} | "
                f"para={preparado['numero_normalizado']} | "
                f"template={preparado['template_nome']}"
            )
            return {
                "enviado":       False,
                "motivo":        "aguardando_aprovacao_humana",
                "canal":         "whatsapp",
                "modo":          "assistido",
                "fila_id":       item_fila["id"],
                "preview":       preparado.get("preview", ""),
                "registrado_em": agora,
            }

        if _modo == "real":
            cfg = _carregar_config()
            token   = cfg.get("api_token", "")
            api_url = cfg.get("api_url", "https://graph.facebook.com/v18.0/")
            numero_negocio = cfg.get("numero_comercial", "")
            return _enviar_api_real(preparado, token, api_url, numero_negocio, agora)

        return {"enviado": False, "motivo": f"modo_desconhecido: {_modo}", "canal": "whatsapp"}

    # ── verificar_resposta ────────────────────────────────────────────────────

    def verificar_resposta(self) -> list:
        """
        Em dry-run/assistido: retorna [].
        Em real (futuro): consulta webhook de respostas do WhatsApp Business API.

        Estrutura de resposta esperada quando implementado:
          [{"de": "+5517...", "mensagem": "...", "timestamp": "...", "tipo": "text"}]
        """
        if self.modo in ("dry-run", "assistido"):
            return []
        # Placeholder para implementação futura com webhooks
        log.debug("[whatsapp] verificar_resposta: webhook não implementado — retornando []")
        return []

    # ── status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Estado atual: modo, mensagens hoje, fila pendente, último envio."""
        cfg  = _carregar_config()
        fila = _carregar_fila()

        hoje_str    = datetime.now().strftime("%Y-%m-%d")
        enviadas_hoje = sum(
            1 for item in fila
            if item.get("registrado_em", "").startswith(hoje_str)
        )
        pendentes_fila = sum(
            1 for item in fila if item.get("status") in ("pendente", "agendado")
        )
        ultimo_envio = max(
            (item.get("registrado_em", "") for item in fila if item.get("registrado_em")),
            default=None,
        )

        estado = _carregar_estado_canais().get("whatsapp", {})

        return {
            "modo":             self.modo,
            "configurado":      bool(cfg.get("api_token") and cfg.get("numero_comercial")),
            "mensagens_hoje":   enviadas_hoje,
            "limite_diario":    cfg.get("max_mensagens_dia", 50),
            "fila_pendente":    pendentes_fila,
            "fila_total":       len(fila),
            "ultimo_envio":     ultimo_envio,
            "taxa_resposta":    estado.get("taxa_resposta", 0.0),
            "pre_requisitos":   estado.get("pre_requisitos", []) if self.modo == "dry-run" else [],
        }


# ─── Normalização de número ────────────────────────────────────────────────────

def normalizar_numero(numero_raw: str) -> tuple[str, str]:
    """
    Normaliza número de telefone para formato internacional +55DDNNNNNNNNN.

    Retorna (numero_normalizado, erro). Se erro != "", o número é inválido.

    Aceita:
      +5517999998888  → +5517999998888 (já normalizado)
      5517999998888   → +5517999998888
      (17) 9 9999-8888 → +5517999998888
      (17) 99999-8888 → +5517999998888
      17 99999-8888   → +5517999998888

    Rejeita:
      menos de 10 dígitos
      não numérico após limpeza
    """
    if not numero_raw:
        return "", "numero_ausente"

    # Remover formatação: espaços, parênteses, traços, pontos
    limpo = re.sub(r"[\s\(\)\-\.]", "", str(numero_raw))

    # Remover prefixo + para contar dígitos
    sem_plus = limpo.lstrip("+")

    if not sem_plus.isdigit():
        return "", f"caractere_invalido ('{limpo}')"

    n_digitos = len(sem_plus)

    if n_digitos < 10:
        return "", f"muito_curto ({n_digitos} digitos)"

    if n_digitos > 15:
        return "", f"muito_longo ({n_digitos} digitos)"

    # Já tem código do país
    if limpo.startswith("+55") or sem_plus.startswith("55") and n_digitos >= 12:
        if limpo.startswith("+"):
            return limpo, ""
        return f"+{sem_plus}", ""

    # Apenas DDD + número (10 ou 11 dígitos) → assume Brasil
    if n_digitos in (10, 11):
        return f"+55{sem_plus}", ""

    # 12+ dígitos sem prefixo de país → assume +55 faltando
    if n_digitos == 12 and sem_plus.startswith("55"):
        return f"+{sem_plus}", ""

    return f"+55{sem_plus}", ""


# ─── Internos ─────────────────────────────────────────────────────────────────

def _extrair_numero(payload: dict) -> str:
    """Extrai número de destino de múltiplos campos possíveis do payload."""
    return (
        payload.get("contato_destino")
        or payload.get("telefone")
        or payload.get("whatsapp")
        or payload.get("numero")
        or ""
    )


def _verificar_janela_horario(cfg: dict, agora: datetime) -> tuple[bool, str | None]:
    """
    Verifica se o momento atual está dentro da janela de envio.

    Retorna (permitido, proximo_horario_iso).
    proximo_horario_iso é None se já está dentro da janela.
    """
    dia_semana = _DIAS_PT.get(agora.weekday(), "")
    dias_perm  = cfg.get("dias_permitidos", ["seg", "ter", "qua", "qui", "sex"])

    horario = cfg.get("horario_permitido", {"inicio": "08:00", "fim": "20:00"})
    h_ini   = _parse_hhmm(horario.get("inicio", "08:00"))
    h_fim   = _parse_hhmm(horario.get("fim", "20:00"))
    hora_atual = (agora.hour, agora.minute)

    dia_ok  = dia_semana in dias_perm
    hora_ok = h_ini <= hora_atual < h_fim

    if dia_ok and hora_ok:
        return True, None

    # Calcular próximo horário permitido
    prox = _calcular_proximo_horario(agora, dias_perm, h_ini)
    return False, prox.isoformat(timespec="minutes")


def _parse_hhmm(hhmm: str) -> tuple[int, int]:
    """Converte 'HH:MM' para (horas, minutos)."""
    try:
        h, m = hhmm.split(":")
        return int(h), int(m)
    except Exception:
        return 8, 0


def _calcular_proximo_horario(agora: datetime, dias_perm: list, h_ini: tuple) -> datetime:
    """Retorna o próximo datetime dentro da janela de envio."""
    # Tentar hoje a partir do horário inicial
    candidato = agora.replace(hour=h_ini[0], minute=h_ini[1], second=0, microsecond=0)
    for _ in range(7):
        dia = _DIAS_PT.get(candidato.weekday(), "")
        if dia in dias_perm and candidato > agora:
            return candidato
        candidato += timedelta(days=1)
        candidato = candidato.replace(hour=h_ini[0], minute=h_ini[1], second=0, microsecond=0)
    return candidato


def _verificar_cooldown(numero: str, fila: list, cooldown_horas: int) -> tuple[bool, str | None]:
    """
    Verifica se já foi enviada mensagem para este número dentro do período de cooldown.
    Retorna (em_cooldown, data_ultimo_envio_iso).
    """
    corte = datetime.now() - timedelta(hours=cooldown_horas)
    for item in reversed(fila):  # mais recente primeiro
        if item.get("numero_destino") != numero:
            continue
        if item.get("status") in ("cancelado", "rejeitado"):
            continue
        data_str = item.get("registrado_em", "")
        try:
            data = datetime.fromisoformat(data_str)
        except Exception:
            continue
        if data >= corte:
            return True, data_str
    return False, None


def _contar_enviados_hoje(fila: list) -> int:
    """Conta mensagens enviadas ou enfileiradas hoje."""
    hoje = datetime.now().strftime("%Y-%m-%d")
    return sum(
        1 for item in fila
        if item.get("registrado_em", "").startswith(hoje)
        and item.get("status") not in ("cancelado", "rejeitado")
    )


def _montar_variaveis(payload: dict, template_id: str) -> dict:
    """
    Extrai/constrói variáveis para o template a partir do payload.
    Usa valores genéricos como fallback para variáveis ausentes.
    """
    ctx         = payload.get("contexto_oportunidade") or {}
    contraparte = ctx.get("contraparte") or payload.get("contraparte", "")
    categoria   = ctx.get("categoria", "")
    linha       = payload.get("linha_servico_sugerida", "")

    # Tentar extrair nome do contato do contato_destino (fallback: "equipe")
    contato_raw = payload.get("contato_destino", "")
    nome_contato = _inferir_nome_contato(contato_raw) or "equipe"

    if template_id == "abordagem_inicial":
        prob = _inferir_problema(payload, ctx, categoria, linha)
        return {
            "nome_contato":      nome_contato,
            "nome_empresa":      contraparte or "sua empresa",
            "problema_principal": prob,
        }

    if template_id == "followup":
        roteiro = payload.get("roteiro_base", "")[:80]
        return {
            "nome_contato":     nome_contato,
            "contexto_anterior": roteiro or "nossa conversa anterior",
        }

    if template_id == "proposta":
        return {
            "nome_contato": nome_contato,
            "nome_pacote":  payload.get("oferta_id", "nosso servico").replace("_", " "),
            "valor":        f"R$ {payload.get('valor_estimado', '?')}",
        }

    if template_id == "nps":
        return {
            "nome_contato":     nome_contato,
            "servico_entregue": payload.get("oferta_id", "o servico entregue").replace("_", " "),
        }

    return {"nome_contato": nome_contato, "nome_empresa": contraparte}


def _inferir_nome_contato(contato_raw: str) -> str:
    """
    Tenta extrair nome de um contato. Se for número, retorna vazio.
    Se for 'Nome / número' ou 'Nome (email)', extrai o nome.
    """
    if not contato_raw:
        return ""
    # Se começa com + ou é só dígitos: é número
    limpo = contato_raw.strip()
    if limpo.startswith("+") or re.match(r"^[\d\s\(\)\-]+$", limpo):
        return ""
    # Pegar primeira parte antes de / ou ( ou ,
    parte = re.split(r"[/\(,]", limpo)[0].strip()
    # Capitalizar e pegar só o primeiro nome
    palavras = parte.split()
    if palavras:
        return palavras[0].capitalize()
    return ""


def _inferir_problema(payload: dict, ctx: dict, categoria: str, linha: str) -> str:
    """Infere o problema principal a destacar na abordagem."""
    # Diagnóstico explícito
    diagnostico = (
        ctx.get("diagnostico_resumo")
        or ctx.get("observacoes", "")[:80]
        or payload.get("roteiro_base", "")[:80]
    )
    if diagnostico:
        return diagnostico

    # Por categoria / linha de serviço
    _PROBLEMAS = {
        "barbearia":          "a dificuldade de agendar horarios pelo celular",
        "salao_de_beleza":    "a dificuldade de agendar horarios pelo celular",
        "oficina_mecanica":   "o excesso de ligacoes para saber precos e prazos",
        "padaria":            "a dificuldade de clientes acharem seus horarios no Google",
        "acougue":            "clientes que nao sabem seus horarios ou especiais do dia",
        "autopecas":          "o tempo perdido respondendo as mesmas perguntas por WhatsApp",
        "borracharia":        "clientes que nao sabem se voce esta aberto antes de ir",
    }
    if categoria in _PROBLEMAS:
        return _PROBLEMAS[categoria]
    if "presenca" in linha:
        return "a baixa visibilidade no Google"
    if "atendimento" in linha:
        return "o atendimento repetitivo que consome tempo do dono"
    return "os gargalos operacionais do dia a dia"


def _tentar_llm_variaveis(payload: dict, template_id: str, variaveis_base: dict) -> tuple[dict, bool]:
    """
    Chama LLM para personalizar variáveis do template.
    Retorna (variaveis, usou_llm). Nunca levanta exceção.
    """
    try:
        from core.llm_router import LLMRouter
        router = LLMRouter()
        ctx = payload.get("contexto_oportunidade") or {}
        _ctx_llm = {
            "empresa":       ctx.get("contraparte", ""),
            "abordagem":     payload.get("abordagem_inicial_tipo", "padrao"),
            "canal":         "whatsapp",
            "template_id":   template_id,
            "variaveis_base": variaveis_base,
            "roteiro_base":  payload.get("roteiro_base", "")[:200],
            "instrucao": (
                f"Personalizar as variaveis do template WhatsApp '{template_id}' "
                f"para esta empresa especifica. "
                f"Retornar JSON com as mesmas chaves de variaveis_base, "
                f"mas com valores mais especificos e persuasivos. "
                f"Maximo 10 palavras por variavel."
            ),
        }
        _res = router.redigir(_ctx_llm)
        if _res.get("sucesso") and not _res.get("fallback_usado"):
            import json as _json
            resultado_str = _res.get("resultado", "")
            # Tentar extrair JSON da resposta
            match = re.search(r"\{[^{}]+\}", resultado_str, re.DOTALL)
            if match:
                vars_llm = _json.loads(match.group())
                # Garantir que todas as chaves originais estão presentes
                merged = dict(variaveis_base)
                for k, v in vars_llm.items():
                    if k in variaveis_base and isinstance(v, str) and v.strip():
                        merged[k] = v.strip()[:120]
                return merged, True
    except Exception as exc:
        log.debug(f"[whatsapp] LLM falhou: {exc}")
    return variaveis_base, False


def _montar_item_fila(preparado: dict, payload: dict, agora: str) -> dict:
    """Monta item para fila_envio_whatsapp.json."""
    exec_id = payload.get("_exec_id", "")
    return {
        "id":               f"wa_{exec_id}_{agora.replace(':', '').replace('-', '')[:15]}",
        "execucao_id":      exec_id,
        "oportunidade_id":  payload.get("oportunidade_id", ""),
        "contraparte":      (payload.get("contexto_oportunidade") or {}).get("contraparte", ""),
        "numero_destino":   preparado.get("numero_normalizado", ""),
        "template_nome":    preparado.get("template_nome", ""),
        "variaveis":        preparado.get("variaveis", {}),
        "preview":          preparado.get("preview", ""),
        "status":           "pendente",
        "agendado_para":    preparado.get("agendado_para"),
        "simulado":         preparado.get("simulado", True),
        "modo":             preparado.get("modo", "dry-run"),
        "motivo_bloqueio":  None,
        "registrado_em":    agora,
        "atualizado_em":    agora,
    }


def _enviar_api_real(preparado: dict, token: str, api_url: str, numero_negocio: str, agora: str) -> dict:
    """
    Envia mensagem via WhatsApp Business Cloud API.
    Chamado apenas quando modo="real" e api_token configurado.

    Endpoint: POST {api_url}{numero_negocio}/messages
    Auth: Bearer {token}
    Body: template message format

    NOTA: Este método está preparado mas não testado em produção.
    Ativar apenas após:
      1. Número verificado no Meta Business Manager
      2. Templates aprovados pelo Meta
      3. api_token configurado em config_canal_whatsapp.json
    """
    try:
        import urllib.request
        import urllib.error

        numero_dest = preparado.get("numero_normalizado", "").lstrip("+")
        template    = preparado.get("template_nome", "")
        variaveis   = preparado.get("variaveis", {})
        idioma      = "pt_BR"

        # Montar componentes do template (parâmetros posicionais)
        parametros = [{"type": "text", "text": str(v)} for v in variaveis.values()]
        corpo = {
            "messaging_product": "whatsapp",
            "to":                numero_dest,
            "type":              "template",
            "template": {
                "name":     template,
                "language": {"code": idioma},
                "components": [
                    {"type": "body", "parameters": parametros}
                ] if parametros else [],
            },
        }
        corpo_bytes = json.dumps(corpo).encode("utf-8")
        url = f"{api_url.rstrip('/')}/{numero_negocio}/messages"
        req = urllib.request.Request(
            url,
            data=corpo_bytes,
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resposta = json.loads(resp.read().decode("utf-8"))
            msg_id = resposta.get("messages", [{}])[0].get("id", "")
            log.info(f"[whatsapp] enviado para {numero_dest} | msg_id={msg_id}")
            return {
                "enviado":       True,
                "msg_id":        msg_id,
                "canal":         "whatsapp",
                "modo":          "real",
                "simulado":      False,
                "numero":        preparado.get("numero_normalizado"),
                "template_nome": template,
                "registrado_em": agora,
            }
    except Exception as exc:
        log.error(f"[whatsapp] falha no envio real: {exc}")
        return {
            "enviado":       False,
            "motivo":        f"erro_api: {exc}",
            "canal":         "whatsapp",
            "modo":          "real",
            "simulado":      True,
            "registrado_em": agora,
        }


# ─── Persistência ─────────────────────────────────────────────────────────────

_config_cache: dict | None = None


def _carregar_config() -> dict:
    global _config_cache
    if _config_cache is None:
        if _ARQUIVO_CONFIG.exists():
            with open(_ARQUIVO_CONFIG, "r", encoding="utf-8") as f:
                _config_cache = json.load(f)
        else:
            _config_cache = {"modo": "dry-run"}
    return _config_cache


def _carregar_fila() -> list:
    if _ARQUIVO_FILA.exists():
        with open(_ARQUIVO_FILA, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _salvar_fila(fila: list) -> None:
    import os
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    conteudo = json.dumps(fila, ensure_ascii=False, indent=2)
    tmp = _ARQUIVO_FILA.with_suffix(_ARQUIVO_FILA.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, _ARQUIVO_FILA)


def _carregar_estado_canais() -> dict:
    if _ARQUIVO_ESTADO.exists():
        with open(_ARQUIVO_ESTADO, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
