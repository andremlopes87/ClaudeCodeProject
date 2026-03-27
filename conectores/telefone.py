"""
conectores/telefone.py — Conector de telefone/voz completo em dry-run (v1.0).

Lógica 100% implementada; envio real ativado trocando config:
  dados/config_canal_telefone.json  →  "modo": "assistido"  ou  "modo": "real"

Modo assistido: humano vê roteiro no painel (/telefone), faz a ligação e registra resultado.
Modo real (futuro): integrar com VoIP (Twilio/Vonage) ou IA de voz (ElevenLabs + OpenAI Realtime).

Responsabilidades:
  - Normalizar e validar número de destino
  - Verificar janela horária comercial (9-18h, mais restritiva que WhatsApp)
  - Verificar cooldown por contato (7 dias — ligação é mais invasiva)
  - Verificar limite diário (20 chamadas/dia)
  - Selecionar roteiro conforme tipo de abordagem
  - Personalizar roteiro via LLM (variáveis de contexto)
  - Enfileirar em fila_chamadas_telefone.json (modo assistido)
  - Registrar resultado e criar ações consequentes

Ações após resultado:
  atendeu_interessado → criar follow-up por email
  nao_atendeu / ocupado → reagendar em 2 dias
  numero_invalido → marcar contato como inválido na fila
  caixa_postal → nota + reagendar em 3 dias
"""

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQUIVO_CONFIG   = config.PASTA_DADOS / "config_canal_telefone.json"
_ARQUIVO_FILA     = config.PASTA_DADOS / "fila_chamadas_telefone.json"
_ARQUIVO_RESULT   = config.PASTA_DADOS / "resultados_chamadas.json"
_ARQUIVO_ESTADO   = config.PASTA_DADOS / "estado_canais.json"

# Textos dos roteiros (preview local e guia para o operador/IA)
_ROTEIROS_TEXTO: dict[str, dict] = {
    "abordagem_fria": {
        "abertura": "Boa tarde, {nome_contato}! Aqui e da equipe Vetor. Tem um minuto?",
        "gancho": "{problema_principal}",
        "proposta": "A gente resolve isso com {solucao_curta}. Sem complicacao.",
        "fechamento": "Posso mandar uma proposta por email pra voce avaliar sem compromisso?",
        "objecoes_comuns": {
            "nao_tenho_interesse": "Entendo. Se mudar de ideia, o numero fica com voce.",
            "quanto_custa":        "Depende do que precisa. Mas a maioria dos nossos clientes começa com menos de R$500.",
            "ja_tenho_solucao":    "Otimo. Se no futuro quiser comparar, estamos a disposicao.",
            "nao_e_o_dono":        "Tudo bem. Posso ligar em outro horario pra falar com o responsavel?",
        },
    },
    "followup": {
        "abertura": "Boa tarde, {nome_contato}! Liguei na semana passada e mandei um email sobre {contexto_anterior}.",
        "gancho": "Queria saber se fez sentido pra voce ou se surgiu alguma duvida.",
        "fechamento": "Se ainda nao for o momento, tudo bem. So queria confirmar que recebeu.",
        "objecoes_comuns": {
            "nao_vi_o_email": "Vou reenviar agora. Qual email e melhor?",
            "nao_tenho_interesse": "Tudo certo. Obrigado pelo retorno.",
        },
    },
    "cobranca_gentil": {
        "abertura": "Boa tarde, {nome_contato}! Tudo bem? Ligando sobre a parcela de {mes_referencia}.",
        "gancho": "Vi que ficou em aberto. Aconteceu alguma coisa?",
        "fechamento": "Posso enviar o link de pagamento por WhatsApp ou email?",
        "objecoes_comuns": {
            "ja_paguei": "Perfeito. Vou verificar aqui e confirmo em seguida.",
            "dificuldade_financeira": "Entendo. Posso verificar opcoes de prazo com a equipe.",
        },
    },
}

# Mapeamento abordagem → tipo de roteiro
_TIPO_PARA_ROTEIRO: dict[str, str] = {
    "exploratoria":           "abordagem_fria",
    "consultiva_diagnostica": "abordagem_fria",
    "padrao":                 "abordagem_fria",
    "followup_sem_resposta":  "followup",
    "reengajamento":          "followup",
    "cobranca_gentil":        "cobranca_gentil",
    "cobranca":               "cobranca_gentil",
}

# Resultados válidos de uma chamada
RESULTADOS_VALIDOS = {
    "atendeu_interessado",
    "atendeu_recusou",
    "nao_atendeu",
    "caixa_postal",
    "numero_invalido",
    "ocupado",
}

_DIAS_PT: dict[int, str] = {0: "seg", 1: "ter", 2: "qua", 3: "qui", 4: "sex", 5: "sab", 6: "dom"}


# ─── Classe principal ─────────────────────────────────────────────────────────

class CanalTelefone:
    """
    Conector de telefone/voz.

    Implementa a interface de core.canais.CanalBase via duck typing para evitar
    importação circular. Registrado em core/canais.CANAIS_DISPONIVEIS["telefone"].
    """

    @property
    def nome(self) -> str:
        return "telefone"

    @property
    def modo(self) -> str:
        return _carregar_config().get("modo", "dry-run")

    # ── preparar_envio ────────────────────────────────────────────────────────

    def preparar_envio(self, payload: dict) -> dict:
        """
        Prepara chamada telefônica: valida, seleciona roteiro, personaliza via LLM.

        Retorna dict com:
          status           — "preparado" | "simulado" | "bloqueado" | "agendado"
          roteiro          — texto completo do roteiro para o operador/IA
          roteiro_id       — chave do template usado
          variaveis        — dict de variáveis preenchidas
          numero_normalizado
          agendado_para    — se fora de horário
          preparado_em
          motivo_bloqueio  — razão se bloqueado
        """
        agora = datetime.now()
        cfg   = _carregar_config()
        _modo = self.modo

        resultado = {
            "status":             "simulado",
            "roteiro":            "",
            "roteiro_id":         None,
            "variaveis":          {},
            "canal":              "telefone",
            "modo":               _modo,
            "simulado":           True,
            "pronto_para_envio":  False,
            "motivo_bloqueio":    None,
            "numero_normalizado": None,
            "agendado_para":      None,
            "preparado_em":       agora.isoformat(timespec="seconds"),
            "payload_original":   payload,
        }

        # 1. Validar número
        numero_raw = _extrair_numero(payload)
        numero, err = normalizar_numero(numero_raw)
        if err:
            resultado["status"]          = "bloqueado"
            resultado["motivo_bloqueio"] = f"numero_invalido: {err} (recebido: '{numero_raw}')"
            return resultado
        resultado["numero_normalizado"] = numero

        # 2. Verificar janela horária
        permitido, prox_horario = _verificar_janela_horario(cfg, agora)
        if not permitido:
            resultado["status"]          = "agendado"
            resultado["agendado_para"]   = prox_horario
            resultado["motivo_bloqueio"] = f"fora_da_janela: proximo horario permitido em {prox_horario}"

        # 3. Cooldown por contato (7 dias)
        fila = _carregar_fila()
        cooldown_dias = cfg.get("cooldown_mesmo_contato_dias", 7)
        em_cooldown, ultimo = _verificar_cooldown(numero, fila, cooldown_dias)
        if em_cooldown:
            resultado["status"]          = "bloqueado"
            resultado["motivo_bloqueio"] = (
                f"cooldown_ativo: ultima chamada para {numero} em {ultimo} "
                f"(cooldown={cooldown_dias} dias)"
            )
            return resultado

        # 4. Limite diário
        limite = cfg.get("max_chamadas_dia", 20)
        feitas_hoje = _contar_chamadas_hoje(fila)
        if feitas_hoje >= limite:
            resultado["status"]          = "bloqueado"
            resultado["motivo_bloqueio"] = f"limite_diario_atingido: {feitas_hoje}/{limite} chamadas hoje"
            return resultado

        # 5. Selecionar roteiro
        tipo_acao  = payload.get("abordagem_inicial_tipo") or payload.get("tipo_acao", "padrao")
        roteiro_id = _TIPO_PARA_ROTEIRO.get(tipo_acao, "abordagem_fria")
        resultado["roteiro_id"] = roteiro_id

        # 6. Montar variáveis e personalizar via LLM
        variaveis = _montar_variaveis(payload, roteiro_id)
        vars_llm, usou_llm = _tentar_llm_roteiro(payload, roteiro_id, variaveis)
        if usou_llm:
            variaveis = vars_llm
        resultado["variaveis"] = variaveis
        resultado["usou_llm"]  = usou_llm

        # 7. Montar roteiro completo (texto para operador ou IA)
        resultado["roteiro"] = _montar_roteiro_texto(roteiro_id, variaveis)

        # 8. Status final
        if resultado["status"] != "agendado":
            resultado["status"]           = "preparado" if _modo != "dry-run" else "simulado"
            resultado["pronto_para_envio"] = _modo != "dry-run"

        return resultado

    # ── enviar ────────────────────────────────────────────────────────────────

    def enviar(self, payload: dict) -> dict:
        """
        dry-run   → retorna roteiro sem efeito externo
        assistido → enfileira em fila_chamadas_telefone.json para operador humano
        real      → (futuro) integrar com Twilio/Vonage ou IA de voz
        """
        preparado = self.preparar_envio(payload)
        _modo = self.modo
        agora = datetime.now().isoformat(timespec="seconds")

        if preparado["status"] == "bloqueado":
            return {
                "executado":     False,
                "motivo":        preparado["motivo_bloqueio"],
                "modo":          _modo,
                "canal":         "telefone",
                "roteiro":       "",
                "registrado_em": agora,
            }

        if _modo == "dry-run":
            return {
                "executado":     False,
                "motivo":        "dry-run",
                "canal":         "telefone",
                "modo":          "dry-run",
                "simulado":      True,
                "roteiro":       preparado.get("roteiro", ""),
                "roteiro_id":    preparado.get("roteiro_id"),
                "variaveis":     preparado.get("variaveis", {}),
                "numero":        preparado.get("numero_normalizado"),
                "registrado_em": agora,
            }

        if _modo == "assistido":
            item = _montar_item_fila(preparado, payload, agora)
            fila = _carregar_fila()
            fila.append(item)
            _salvar_fila(fila)
            log.info(
                f"[telefone] enfileirado {item['chamada_id']} | "
                f"para={preparado['numero_normalizado']} | roteiro={preparado['roteiro_id']}"
            )
            return {
                "executado":     False,
                "motivo":        "aguardando_operador_humano",
                "canal":         "telefone",
                "modo":          "assistido",
                "chamada_id":    item["chamada_id"],
                "roteiro":       preparado.get("roteiro", ""),
                "registrado_em": agora,
            }

        if _modo == "real":
            # Placeholder — integração futura com Twilio ou IA de voz
            log.warning("[telefone] modo=real não implementado — operando como assistido")
            return self._enviar_real_placeholder(preparado, agora)

        return {"executado": False, "motivo": f"modo_desconhecido: {_modo}", "canal": "telefone"}

    # ── verificar_resposta ────────────────────────────────────────────────────

    def verificar_resposta(self) -> list:
        """
        Retorna chamadas com resultado registrado e não processado.
        Em dry-run: [].
        Em assistido: lê resultados_chamadas.json (preenchido via painel).
        """
        if self.modo == "dry-run":
            return []
        resultados = _carregar_resultados()
        return [r for r in resultados if not r.get("processado", False)]

    # ── registrar_resultado_chamada ───────────────────────────────────────────

    def registrar_resultado_chamada(self, chamada_id: str, resultado: str,
                                     observacoes: str = "") -> dict:
        """
        Registra o resultado de uma chamada e cria ações consequentes.

        Resultados:
          atendeu_interessado → follow-up por email
          atendeu_recusou     → registrar objeção
          nao_atendeu / ocupado → reagendar em 2 dias
          caixa_postal        → nota + reagendar em 3 dias
          numero_invalido     → marcar número como inválido

        Retorna dict com: chamada_id, resultado, acoes_criadas, atualizado_em
        """
        if resultado not in RESULTADOS_VALIDOS:
            return {
                "chamada_id":  chamada_id,
                "resultado":   resultado,
                "erro":        f"resultado_invalido — use um de: {sorted(RESULTADOS_VALIDOS)}",
                "atualizado_em": datetime.now().isoformat(timespec="seconds"),
            }

        agora   = datetime.now().isoformat(timespec="seconds")
        fila    = _carregar_fila()
        item    = next((c for c in fila if c.get("chamada_id") == chamada_id), None)
        acoes   = []

        # Atualizar item da fila
        if item:
            item["status"]       = "concluida"
            item["resultado"]    = resultado
            item["observacoes"]  = observacoes
            item["atualizado_em"] = agora
            _salvar_fila(fila)

        # Ações consequentes
        if resultado == "atendeu_interessado":
            acoes.append(_criar_followup_email(chamada_id, item, observacoes))

        elif resultado in ("nao_atendeu", "ocupado"):
            dt_retry = (datetime.now() + timedelta(days=2)).isoformat(timespec="minutes")
            acoes.append({"tipo": "retentativa", "agendado_para": dt_retry, "chamada_id_origem": chamada_id})
            if item:
                item["retentativa_agendada"] = dt_retry

        elif resultado == "caixa_postal":
            dt_retry = (datetime.now() + timedelta(days=3)).isoformat(timespec="minutes")
            acoes.append({"tipo": "retentativa_caixa_postal", "agendado_para": dt_retry, "chamada_id_origem": chamada_id})

        elif resultado == "numero_invalido":
            if item:
                item["numero_invalido"] = True
            acoes.append({"tipo": "marcar_numero_invalido", "numero": item.get("telefone") if item else ""})

        # Persistir na lista de resultados
        resultados = _carregar_resultados()
        resultados.append({
            "chamada_id":    chamada_id,
            "resultado":     resultado,
            "observacoes":   observacoes,
            "acoes_criadas": acoes,
            "processado":    True,
            "registrado_em": agora,
        })
        _salvar_resultados(resultados)
        _salvar_fila(fila)

        log.info(f"[telefone] resultado registrado: {chamada_id} → {resultado} | acoes={len(acoes)}")
        return {
            "chamada_id":    chamada_id,
            "resultado":     resultado,
            "acoes_criadas": acoes,
            "atualizado_em": agora,
        }

    # ── status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        cfg  = _carregar_config()
        fila = _carregar_fila()
        hoje = datetime.now().strftime("%Y-%m-%d")

        chamadas_hoje = sum(
            1 for c in fila
            if c.get("registrado_em", "").startswith(hoje)
        )
        pendentes    = sum(1 for c in fila if c.get("status") in ("pendente", "agendado"))
        concluidas   = sum(1 for c in fila if c.get("status") == "concluida")
        interessados = sum(1 for c in fila if c.get("resultado") == "atendeu_interessado")
        ultimo_envio = max(
            (c.get("registrado_em", "") for c in fila if c.get("registrado_em")),
            default=None,
        )
        taxa = round(interessados / concluidas, 3) if concluidas > 0 else 0.0

        estado = _carregar_estado_canais().get("telefone", {})
        return {
            "modo":            self.modo,
            "configurado":     bool(cfg.get("provedor") and cfg.get("numero_saida")),
            "chamadas_hoje":   chamadas_hoje,
            "limite_diario":   cfg.get("max_chamadas_dia", 20),
            "fila_pendente":   pendentes,
            "fila_concluidas": concluidas,
            "taxa_interesse":  taxa,
            "ultimo_envio":    ultimo_envio,
            "pre_requisitos":  estado.get("pre_requisitos", []) if self.modo == "dry-run" else [],
        }

    # ── Internos ──────────────────────────────────────────────────────────────

    def _enviar_real_placeholder(self, preparado: dict, agora: str) -> dict:
        """
        Placeholder para integração futura com VoIP/IA de voz.

        Para implementar com Twilio:
          import twilio.rest; client = twilio.rest.Client(account_sid, auth_token)
          call = client.calls.create(to=numero, from_=numero_saida, url=twiml_url)

        Para implementar com IA de voz:
          1. ElevenLabs: sintetizar roteiro como áudio
          2. Twilio/Vonage: realizar chamada reproduzindo áudio
          3. OpenAI Realtime API: conversa bidirecional por voz

        O roteiro em preparado["roteiro"] já está pronto para qualquer uma dessas integrações.
        """
        item = _montar_item_fila(preparado, preparado.get("payload_original", {}), agora)
        fila = _carregar_fila()
        fila.append(item)
        _salvar_fila(fila)
        return {
            "executado":     False,
            "motivo":        "modo_real_nao_implementado — enfileirado como assistido",
            "canal":         "telefone",
            "modo":          "real",
            "chamada_id":    item["chamada_id"],
            "roteiro":       preparado.get("roteiro", ""),
            "registrado_em": agora,
        }


# ─── Normalização de número ────────────────────────────────────────────────────

def normalizar_numero(numero_raw: str) -> tuple[str, str]:
    """Reusa lógica do conector WhatsApp. Normaliza para +55DDNNNNNNNNN."""
    try:
        from conectores.whatsapp import normalizar_numero as _wpp_norm
        return _wpp_norm(numero_raw)
    except ImportError:
        pass
    if not numero_raw:
        return "", "numero_ausente"
    limpo = re.sub(r"[\s\(\)\-\.]", "", str(numero_raw)).lstrip("+")
    if not limpo.isdigit():
        return "", f"caractere_invalido ('{limpo}')"
    n = len(limpo)
    if n < 10:
        return "", f"muito_curto ({n} digitos)"
    if n in (10, 11):
        return f"+55{limpo}", ""
    if n >= 12 and limpo.startswith("55"):
        return f"+{limpo}", ""
    return f"+55{limpo}", ""


# ─── Internos ─────────────────────────────────────────────────────────────────

def _extrair_numero(payload: dict) -> str:
    return (
        payload.get("contato_destino")
        or payload.get("telefone")
        or payload.get("numero")
        or ""
    )


def _verificar_janela_horario(cfg: dict, agora: datetime) -> tuple[bool, str | None]:
    dia = _DIAS_PT.get(agora.weekday(), "")
    dias_perm = cfg.get("dias_permitidos", ["seg", "ter", "qua", "qui", "sex"])
    h = cfg.get("horario_permitido", {"inicio": "09:00", "fim": "18:00"})
    h_ini = _parse_hhmm(h.get("inicio", "09:00"))
    h_fim = _parse_hhmm(h.get("fim", "18:00"))
    hora_atual = (agora.hour, agora.minute)

    if dia in dias_perm and h_ini <= hora_atual < h_fim:
        return True, None

    # Próximo horário comercial
    candidato = agora.replace(hour=h_ini[0], minute=h_ini[1], second=0, microsecond=0)
    for _ in range(7):
        d = _DIAS_PT.get(candidato.weekday(), "")
        if d in dias_perm and candidato > agora:
            return False, candidato.isoformat(timespec="minutes")
        candidato += timedelta(days=1)
        candidato = candidato.replace(hour=h_ini[0], minute=h_ini[1], second=0, microsecond=0)
    return False, candidato.isoformat(timespec="minutes")


def _parse_hhmm(hhmm: str) -> tuple[int, int]:
    try:
        h, m = hhmm.split(":")
        return int(h), int(m)
    except Exception:
        return 9, 0


def _verificar_cooldown(numero: str, fila: list, cooldown_dias: int) -> tuple[bool, str | None]:
    corte = datetime.now() - timedelta(days=cooldown_dias)
    for item in reversed(fila):
        if item.get("telefone") != numero:
            continue
        if item.get("status") in ("cancelada", "rejeitada"):
            continue
        data_str = item.get("registrado_em", "")
        try:
            data = datetime.fromisoformat(data_str)
        except Exception:
            continue
        if data >= corte:
            return True, data_str
    return False, None


def _contar_chamadas_hoje(fila: list) -> int:
    hoje = datetime.now().strftime("%Y-%m-%d")
    return sum(
        1 for c in fila
        if c.get("registrado_em", "").startswith(hoje)
        and c.get("status") not in ("cancelada", "rejeitada")
    )


def _montar_variaveis(payload: dict, roteiro_id: str) -> dict:
    ctx         = payload.get("contexto_oportunidade") or {}
    contraparte = ctx.get("contraparte") or payload.get("contraparte", "")
    categoria   = ctx.get("categoria", "")
    linha       = payload.get("linha_servico_sugerida", "")

    contato_raw  = payload.get("contato_destino", "")
    nome_contato = _inferir_nome_contato(contato_raw) or "responsavel"

    if roteiro_id == "abordagem_fria":
        problema = _inferir_problema(payload, ctx, categoria, linha)
        solucao  = _inferir_solucao(linha)
        return {
            "nome_contato":      nome_contato,
            "nome_empresa":      contraparte or "sua empresa",
            "problema_principal": problema,
            "solucao_curta":     solucao,
        }
    if roteiro_id == "followup":
        roteiro_base = payload.get("roteiro_base", "")[:60]
        return {
            "nome_contato":     nome_contato,
            "contexto_anterior": roteiro_base or "nossa proposta de digitalizacao",
        }
    if roteiro_id == "cobranca_gentil":
        mes = payload.get("mes_referencia") or datetime.now().strftime("%B de %Y")
        return {
            "nome_contato":   nome_contato,
            "mes_referencia": mes,
        }
    return {"nome_contato": nome_contato, "nome_empresa": contraparte}


def _inferir_nome_contato(contato_raw: str) -> str:
    if not contato_raw:
        return ""
    limpo = contato_raw.strip()
    if limpo.startswith("+") or re.match(r"^[\d\s\(\)\-]+$", limpo):
        return ""
    parte = re.split(r"[/\(,]", limpo)[0].strip()
    palavras = parte.split()
    return palavras[0].capitalize() if palavras else ""


def _inferir_problema(payload: dict, ctx: dict, categoria: str, linha: str) -> str:
    diag = ctx.get("diagnostico_resumo") or ctx.get("observacoes", "")[:80] or payload.get("roteiro_base", "")[:80]
    if diag:
        return diag
    _PROBLEMAS = {
        "barbearia":       "clientes que nao conseguem agendar pelo celular",
        "salao_de_beleza": "agenda cheia de ligacoes e recados para confirmar horario",
        "oficina_mecanica": "clientes que ligam toda hora pra saber preco e prazo",
        "padaria":         "clientes que nao sabem seu horario antes de ir ate voce",
        "acougue":         "duvidas repetitivas que tomam tempo do atendimento",
        "autopecas":       "whatsapp lotado de perguntas que poderiam ser automaticas",
        "borracharia":     "clientes que nao sabem se voce esta aberto",
    }
    if categoria in _PROBLEMAS:
        return _PROBLEMAS[categoria]
    return "o atendimento manual que consome o seu tempo"


def _inferir_solucao(linha: str) -> str:
    if "presenca" in linha:
        return "Google e WhatsApp organizados em 3 dias"
    if "atendimento" in linha:
        return "bot que responde automaticamente 24h"
    if "agendamento" in linha:
        return "agenda pelo WhatsApp sem ligacao"
    return "automacao simples e sem mensalidade"


def _montar_roteiro_texto(roteiro_id: str, variaveis: dict) -> str:
    """Monta texto completo do roteiro para operador ou IA de voz."""
    roteiro_cfg = _ROTEIROS_TEXTO.get(roteiro_id, {})
    partes = []

    for campo in ("abertura", "gancho", "proposta", "fechamento"):
        texto = roteiro_cfg.get(campo, "")
        if texto:
            try:
                partes.append(texto.format(**variaveis))
            except KeyError:
                partes.append(texto)

    objecoes = roteiro_cfg.get("objecoes_comuns", {})
    if objecoes:
        partes.append("\n--- Respostas para objeccoes ---")
        for objecao, resposta in objecoes.items():
            partes.append(f"[{objecao}] {resposta}")

    return "\n".join(partes)


def _tentar_llm_roteiro(payload: dict, roteiro_id: str, variaveis_base: dict) -> tuple[dict, bool]:
    """Personaliza variáveis do roteiro via LLM. Retorna (variaveis, usou_llm)."""
    try:
        from core.llm_router import LLMRouter
        router = LLMRouter()
        ctx = payload.get("contexto_oportunidade") or {}
        _ctx_llm = {
            "empresa":        ctx.get("contraparte", ""),
            "abordagem":      payload.get("abordagem_inicial_tipo", "padrao"),
            "canal":          "telefone",
            "roteiro_id":     roteiro_id,
            "variaveis_base": variaveis_base,
            "roteiro_base":   payload.get("roteiro_base", "")[:200],
            "instrucao": (
                f"Personalizar as variaveis do roteiro de telefone '{roteiro_id}' "
                f"para esta empresa especifica. Retornar JSON com as mesmas chaves "
                f"de variaveis_base, com valores especificos e naturais. "
                f"Maximo 15 palavras por variavel. Tom direto, sem buzzwords."
            ),
        }
        _res = router.redigir(_ctx_llm)
        if _res.get("sucesso") and not _res.get("fallback_usado"):
            match = re.search(r"\{[^{}]+\}", _res.get("resultado", ""), re.DOTALL)
            if match:
                vars_llm = json.loads(match.group())
                merged = dict(variaveis_base)
                for k, v in vars_llm.items():
                    if k in variaveis_base and isinstance(v, str) and v.strip():
                        merged[k] = v.strip()[:150]
                return merged, True
    except Exception as exc:
        log.debug(f"[telefone] LLM falhou: {exc}")
    return variaveis_base, False


def _montar_item_fila(preparado: dict, payload: dict, agora: str) -> dict:
    exec_id = payload.get("_exec_id", "")
    return {
        "chamada_id":    f"call_{exec_id}_{agora.replace(':', '').replace('-', '')[:15]}",
        "execucao_id":   exec_id,
        "oportunidade_id": payload.get("oportunidade_id", ""),
        "contato_nome":  preparado.get("variaveis", {}).get("nome_contato", ""),
        "empresa":       (payload.get("contexto_oportunidade") or {}).get("contraparte", ""),
        "telefone":      preparado.get("numero_normalizado", ""),
        "tipo":          preparado.get("roteiro_id", "abordagem_fria"),
        "roteiro":       preparado.get("roteiro", ""),
        "variaveis":     preparado.get("variaveis", {}),
        "status":        "pendente",
        "resultado":     None,
        "observacoes":   "",
        "data_agendada": preparado.get("agendado_para"),
        "simulado":      preparado.get("simulado", True),
        "modo":          preparado.get("modo", "dry-run"),
        "registrado_em": agora,
        "atualizado_em": agora,
    }


def _criar_followup_email(chamada_id: str, item: dict | None, observacoes: str) -> dict:
    """
    Cria uma entrada em fila_followups.json para follow-up por email após interesse.
    Retorna dict da ação criada.
    """
    agora = datetime.now().isoformat(timespec="seconds")
    empresa  = item.get("empresa", "") if item else ""
    telefone = item.get("telefone", "") if item else ""
    opp_id   = item.get("oportunidade_id", "") if item else ""

    followup = {
        "tipo":          "followup_pos_ligacao",
        "canal":         "email",
        "origem":        "resultado_chamada_telefone",
        "chamada_id":    chamada_id,
        "oportunidade_id": opp_id,
        "empresa":       empresa,
        "observacoes":   observacoes or "Cliente demonstrou interesse na ligacao",
        "criado_em":     agora,
    }

    # Tentar persistir na fila de follow-ups
    try:
        _arq = config.PASTA_DADOS / "fila_followups.json"
        fus  = json.loads(_arq.read_text(encoding="utf-8")) if _arq.exists() else []
        followup["id"] = f"fu_pos_ligacao_{chamada_id}"
        followup["status"] = "pendente"
        followup["contraparte"] = empresa
        followup["descricao"] = f"Follow-up por email apos ligacao. Empresa: {empresa}. Obs: {observacoes}"
        followup["tipo_acao"] = "followup_sem_resposta"
        followup["canal"] = "email"
        fus.append(followup)
        import os as _os
        _arq.parent.mkdir(parents=True, exist_ok=True)
        _conteudo = json.dumps(fus, ensure_ascii=False, indent=2)
        _tmp = _arq.with_suffix(_arq.suffix + ".tmp")
        with open(_tmp, "w", encoding="utf-8") as _f:
            _f.write(_conteudo)
            _f.flush()
            _os.fsync(_f.fileno())
        _os.replace(_tmp, _arq)
    except Exception as exc:
        log.warning(f"[telefone] nao foi possivel criar followup email: {exc}")

    return {"tipo": "followup_email_criado", "empresa": empresa, "chamada_id": chamada_id}


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


def _carregar_resultados() -> list:
    if _ARQUIVO_RESULT.exists():
        with open(_ARQUIVO_RESULT, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _salvar_resultados(resultados: list) -> None:
    import os
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    conteudo = json.dumps(resultados, ensure_ascii=False, indent=2)
    tmp = _ARQUIVO_RESULT.with_suffix(_ARQUIVO_RESULT.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, _ARQUIVO_RESULT)


def _carregar_estado_canais() -> dict:
    if _ARQUIVO_ESTADO.exists():
        with open(_ARQUIVO_ESTADO, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
