"""
core/canais.py — Framework unificado de canais de comunicação (v1.0).

Abstrai email, WhatsApp, telefone e futuros canais atrás de uma interface única.
Quando um canal real for ativado, só o conector muda — o agente não percebe.

Hierarquia:
  CanalBase (abstrata)
    ├── CanalEmail         — email em modo assistido (usa canal_email_assistido.py)
    ├── CanalWhatsApp      — WhatsApp (dry-run até API contratada)
    ├── CanalTelefone      — telefone (dry-run até integração VoIP)
    └── _CanalDryRunGenerico — fallback para canais desconhecidos

Registry:
  CANAIS_DISPONIVEIS = {"email": CanalEmail, "whatsapp": CanalWhatsApp, ...}

Funções públicas:
  obter_canal(nome)                          → CanalBase
  canais_ativos()                            → list[str]
  melhor_canal_para_contato(contato, prio)   → str
  preparar_envio(nome_canal, payload)        → dict
  registrar_resultado(nome_canal, id, res)   → None

Estado persistido em dados/estado_canais.json (criado automaticamente se ausente).

Relação com conectores/:
  conectores/canal_base.py  → interface de baixo nível (execucao → mundo real)
  core/canais.py            → interface de alto nível (executor → canal → preparar)
  Não há conflito: camadas diferentes do mesmo pipeline.
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger(__name__)

_ARQUIVO_ESTADO = config.PASTA_DADOS / "estado_canais.json"

_ESTADO_PADRAO = {
    "email": {
        "modo":           "assistido",
        "configurado":    True,
        "ultimo_envio":   None,
        "envios_total":   0,
        "taxa_resposta":  0.0,
    },
    "whatsapp": {
        "modo":           "dry-run",
        "configurado":    False,
        "motivo":         "API não contratada",
        "pre_requisitos": [
            "WhatsApp Business API",
            "número verificado",
            "template aprovado",
        ],
    },
    "telefone": {
        "modo":           "dry-run",
        "configurado":    False,
        "motivo":         "Integração VoIP não implementada",
        "pre_requisitos": [
            "Provedor VoIP",
            "número comercial",
            "script de chamada",
        ],
    },
}

_estado_cache: dict | None = None


# ─── Estado ───────────────────────────────────────────────────────────────────

def _carregar_estado_canais() -> dict:
    global _estado_cache
    if _estado_cache is None:
        if _ARQUIVO_ESTADO.exists():
            with open(_ARQUIVO_ESTADO, "r", encoding="utf-8") as f:
                _estado_cache = json.load(f)
        else:
            _estado_cache = dict(_ESTADO_PADRAO)
    return _estado_cache


def _salvar_estado_canais(estado: dict) -> None:
    import os
    global _estado_cache
    _estado_cache = estado
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    conteudo = json.dumps(estado, ensure_ascii=False, indent=2)
    tmp = _ARQUIVO_ESTADO.with_suffix(_ARQUIVO_ESTADO.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(conteudo)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, _ARQUIVO_ESTADO)


# ─── Interface base ───────────────────────────────────────────────────────────

class CanalBase(ABC):
    """
    Interface unificada para qualquer canal de comunicação.

    Separação de responsabilidades:
      preparar_envio — monta estrutura de envio (dry-run ou assistido: sem efeito externo)
      enviar         — executa envio real (só modo 'real'); em outros modos equivale a preparar
      verificar_resposta — lista respostas recebidas (retorna [] em dry-run)
      status         — estado atual do canal (modo, métricas)
    """

    @property
    @abstractmethod
    def nome(self) -> str:
        """Nome do canal: 'email', 'whatsapp', 'telefone', ..."""
        ...

    @property
    @abstractmethod
    def modo(self) -> str:
        """Modo de operação: 'dry-run' | 'assistido' | 'real'"""
        ...

    @abstractmethod
    def preparar_envio(self, payload: dict) -> dict:
        """
        Prepara envio no canal sem efeito externo (dry-run/assistido).

        Retorna dict com campos mínimos garantidos:
          status           — "preparado" | "simulado" | "bloqueado"
          preview          — texto do que seria enviado (pode ser vazio)
          canal            — nome do canal
          modo             — modo de operação atual
          simulado         — True se não houve envio real
          pronto_para_envio — bool
          motivo_bloqueio  — str | None
          preparado_em     — ISO 8601
          payload_original — cópia do payload recebido
        """
        ...

    @abstractmethod
    def enviar(self, payload: dict) -> dict:
        """
        Envia de verdade (modo 'real').
        Em dry-run/assistido: delega para preparar_envio.
        """
        ...

    @abstractmethod
    def verificar_resposta(self) -> list:
        """Respostas recebidas no canal pendentes de processamento. [] em dry-run."""
        ...

    @abstractmethod
    def status(self) -> dict:
        """Estado atual do canal: modo, configurado, métricas."""
        ...


# ─── CanalEmail ───────────────────────────────────────────────────────────────

class CanalEmail(CanalBase):
    """
    Canal de email.

    Modos:
      dry-run   — preview simulado, sem montar email real
      assistido — monta email estruturado via canal_email_assistido.py e tenta LLM
      real      — (futuro) envia via SMTP/API

    Inclui enriquecimento LLM automático no modo assistido:
      Se LLM retornar corpo personalizado, injeta em payload["corpo_email_llm"]
      e em payload["roteiro_base"] para compatibilidade com integradores downstream.
    """

    @property
    def nome(self) -> str:
        return "email"

    @property
    def modo(self) -> str:
        return _carregar_estado_canais().get("email", {}).get("modo", "dry-run")

    def preparar_envio(self, payload: dict) -> dict:
        agora = datetime.now().isoformat(timespec="seconds")
        _modo = self.modo

        if _modo == "dry-run":
            return _resultado_dry_run("email", payload, agora)

        # Modo assistido ou real
        resultado = _resultado_base("email", _modo, agora, payload)

        # Enriquecimento LLM
        corpo_llm, usou_llm = _tentar_llm_email(payload)
        if usou_llm and corpo_llm:
            payload["corpo_email_llm"] = corpo_llm
            payload["roteiro_base"]    = corpo_llm
            resultado["corpo_email_llm"] = corpo_llm
            resultado["usou_llm"]        = True

        # Montagem completa via canal_email_assistido
        try:
            email_dict = _montar_email_assistido(payload)
            resultado["status"]           = email_dict.get("status", "simulado")
            resultado["preview"]          = email_dict.get("corpo_texto", "")
            resultado["assunto"]          = email_dict.get("assunto", "")
            resultado["pronto_para_envio"] = email_dict.get("pronto_para_envio", False)
            resultado["motivo_bloqueio"]   = email_dict.get("motivo_bloqueio")
            resultado["email_id"]          = email_dict.get("id", "")
            resultado["resultado_completo"] = email_dict
        except Exception as exc:
            log.warning(f"[CanalEmail] montagem falhou: {exc}")
            resultado["status"]          = "simulado"
            resultado["preview"]         = payload.get("roteiro_base", "")[:300]
            resultado["pronto_para_envio"] = False
            resultado["motivo_bloqueio"] = f"montagem_parcial: {exc}"

        return resultado

    def enviar(self, payload: dict) -> dict:
        return self.preparar_envio(payload)

    def verificar_resposta(self) -> list:
        return []

    def status(self) -> dict:
        return _carregar_estado_canais().get("email", {"modo": "dry-run", "configurado": False})


# ─── CanalWhatsApp ────────────────────────────────────────────────────────────

class CanalWhatsApp(CanalBase):
    """
    Canal WhatsApp — delega para conectores/whatsapp.py (implementação completa).

    Importação lazy para evitar circular import: core.canais ↔ conectores.whatsapp.
    """

    def _conector(self):
        from conectores.whatsapp import CanalWhatsApp as _Impl
        return _Impl()

    @property
    def nome(self) -> str:
        return "whatsapp"

    @property
    def modo(self) -> str:
        return self._conector().modo

    def preparar_envio(self, payload: dict) -> dict:
        return self._conector().preparar_envio(payload)

    def enviar(self, payload: dict) -> dict:
        return self._conector().enviar(payload)

    def verificar_resposta(self) -> list:
        return self._conector().verificar_resposta()

    def status(self) -> dict:
        return self._conector().status()


# ─── CanalTelefone ────────────────────────────────────────────────────────────

class CanalTelefone(CanalBase):
    """
    Canal telefone — delega para conectores/telefone.py (implementação completa).

    Importação lazy para evitar circular import: core.canais ↔ conectores.telefone.
    """

    def _conector(self):
        from conectores.telefone import CanalTelefone as _Impl
        return _Impl()

    @property
    def nome(self) -> str:
        return "telefone"

    @property
    def modo(self) -> str:
        return self._conector().modo

    def preparar_envio(self, payload: dict) -> dict:
        return self._conector().preparar_envio(payload)

    def enviar(self, payload: dict) -> dict:
        return self._conector().enviar(payload)

    def verificar_resposta(self) -> list:
        return self._conector().verificar_resposta()

    def status(self) -> dict:
        return self._conector().status()


# ─── Fallback genérico ────────────────────────────────────────────────────────

class _CanalDryRunGenerico(CanalBase):
    """Fallback para canais não registrados. Nunca levanta exceção."""

    def __init__(self, nome_canal: str) -> None:
        self._nome_canal = nome_canal

    @property
    def nome(self) -> str:
        return self._nome_canal

    @property
    def modo(self) -> str:
        return "dry-run"

    def preparar_envio(self, payload: dict) -> dict:
        agora = datetime.now().isoformat(timespec="seconds")
        return _resultado_dry_run(self._nome_canal, payload, agora)

    def enviar(self, payload: dict) -> dict:
        return self.preparar_envio(payload)

    def verificar_resposta(self) -> list:
        return []

    def status(self) -> dict:
        return {
            "modo":        "dry-run",
            "configurado": False,
            "motivo":      f"Canal '{self._nome_canal}' não registrado em CANAIS_DISPONIVEIS",
        }


# ─── Registry ─────────────────────────────────────────────────────────────────

CANAIS_DISPONIVEIS: dict[str, type[CanalBase]] = {
    "email":    CanalEmail,
    "whatsapp": CanalWhatsApp,
    "telefone": CanalTelefone,
}


# ─── API pública ──────────────────────────────────────────────────────────────

def obter_canal(nome: str) -> CanalBase:
    """
    Retorna instância do canal pelo nome.
    Se canal não existe, retorna _CanalDryRunGenerico sem erro.
    """
    cls = CANAIS_DISPONIVEIS.get(nome)
    if cls:
        return cls()
    log.debug(f"[canais] '{nome}' não registrado — usando dry-run genérico")
    return _CanalDryRunGenerico(nome)


def canais_ativos() -> list[str]:
    """Nomes dos canais com modo != 'dry-run'."""
    return [nome for nome, cls in CANAIS_DISPONIVEIS.items() if cls().modo != "dry-run"]


def melhor_canal_para_contato(
    contato: dict,
    prioridade: list[str] | None = None,
) -> str:
    """
    Sugere o melhor canal para um contato dado.

    Prioridade padrão: email > whatsapp > telefone.
    Se o contato tem canal_preferido e tem dado de contato para ele, usa esse.
    Retorna o primeiro da prioridade como fallback mesmo sem dado de contato.
    """
    if prioridade is None:
        prioridade = ["email", "whatsapp", "telefone"]

    # Respeitar preferência do contato se houver dado de contato
    canal_pref = contato.get("canal_preferido", "")
    if canal_pref and _contato_tem_dado(contato, canal_pref):
        return canal_pref

    # Percorrer prioridade
    for canal in prioridade:
        if _contato_tem_dado(contato, canal):
            return canal

    return prioridade[0]


def preparar_envio(nome_canal: str, payload: dict) -> dict:
    """
    Interface conveniente: prepara envio sem instanciar o canal manualmente.
    Equivale a obter_canal(nome).preparar_envio(payload).
    """
    return obter_canal(nome_canal).preparar_envio(payload)


def registrar_resultado(nome_canal: str, envio_id: str, resultado: dict) -> None:
    """
    Registra resultado de um envio.
    Atualiza último envio, total e taxa de resposta do canal.
    """
    estado = _carregar_estado_canais()
    canal_estado = estado.setdefault(nome_canal, {})

    agora = datetime.now().isoformat(timespec="seconds")
    canal_estado["ultimo_envio"] = agora
    canal_estado["envios_total"] = canal_estado.get("envios_total", 0) + 1

    if resultado.get("respondeu"):
        n = canal_estado.get("_n_respostas", 0) + 1
        canal_estado["_n_respostas"] = n
        total = canal_estado["envios_total"]
        canal_estado["taxa_resposta"] = round(n / total, 4)

    _salvar_estado_canais(estado)


# ─── Internos ─────────────────────────────────────────────────────────────────

def _resultado_dry_run(canal: str, payload: dict, agora: str) -> dict:
    """Resultado padrão de dry-run: preview simulado, sem efeito externo."""
    contato  = payload.get("contato_destino", "?")
    empresa  = (payload.get("contexto_oportunidade") or {}).get("contraparte", "")
    roteiro  = payload.get("roteiro_base", "")[:120]
    abord    = payload.get("abordagem_inicial_tipo", "padrao")

    preview = (
        f"[DRY-RUN/{canal.upper()}] para={contato}"
        + (f" | empresa={empresa}" if empresa else "")
        + f" | abordagem={abord}"
        + (f" | roteiro='{roteiro}...'" if roteiro else "")
    )

    return {
        "status":           "simulado",
        "preview":          preview,
        "canal":            canal,
        "modo":             "dry-run",
        "simulado":         True,
        "pronto_para_envio": False,
        "motivo_bloqueio":  None,
        "preparado_em":     agora,
        "payload_original": payload,
    }


def _resultado_base(canal: str, modo: str, agora: str, payload: dict) -> dict:
    """Base para resultados em modo assistido/real."""
    return {
        "status":           "simulado",
        "preview":          "",
        "canal":            canal,
        "modo":             modo,
        "simulado":         True,
        "pronto_para_envio": False,
        "motivo_bloqueio":  None,
        "preparado_em":     agora,
        "payload_original": payload,
        "usou_llm":         False,
    }


def _tentar_llm_email(payload: dict) -> tuple[str, bool]:
    """
    Gera corpo de email via sistema de templates (core/templates_email.py).
    Retorna (corpo, usou_llm). Nunca levanta exceção.
    """
    try:
        from core.templates_email import gerar_email as _gerar_tmpl
        ctx = payload.get("contexto_oportunidade") or {}

        tipo = payload.get("tipo_template", "abordagem_inicial")

        variaveis = {
            "nome_contato":      (
                ctx.get("contato_nome")
                or ctx.get("contato")
                or payload.get("contato_destino", "cliente")
            ),
            "nome_empresa":      ctx.get("contraparte", payload.get("empresa", "")),
            "categoria":         payload.get("categoria_empresa", ctx.get("categoria", "")),
            "problema_principal": payload.get("problema_principal", ctx.get("problema", "")),
            "solucao_curta":     payload.get("linha_servico_sugerida", "automação de atendimento"),
            "dias_desde_ultimo": str(payload.get("dias_desde_ultimo", "7")),
            "nome_oferta":       payload.get("oferta_nome", ""),
            "valor":             str(payload.get("valor", "")),
            "prazo":             str(payload.get("prazo", "")),
        }

        empresa_id = (
            payload.get("empresa_id")
            or ctx.get("empresa_id")
            or ctx.get("oportunidade_id", "")
        )

        resultado = _gerar_tmpl(tipo, variaveis, empresa_id=empresa_id or None)
        corpo = resultado.get("corpo", "")
        usou_llm = resultado.get("fonte") == "llm"
        if corpo:
            return corpo, usou_llm
    except Exception as exc:
        log.debug(f"[CanalEmail] template_email falhou: {exc}")
    return "", False


def _montar_email_assistido(payload: dict) -> dict:
    """
    Chama preparar_email_para_execucao com contextos carregados do disco.
    Constrói execucao_compat a partir do payload plano do executor.
    """
    from conectores.canal_email_assistido import preparar_email_para_execucao
    from datetime import datetime as _dt

    identidade, guia, assinaturas, canais_cfg, config_canal = _carregar_contexto_email()

    # Mapear payload plano → estrutura execucao esperada pelo módulo de email
    execucao_compat = {
        "id":                     payload.get("_exec_id", f"canal_email_{_dt.now().strftime('%Y%m%d%H%M%S')}"),
        "abordagem_inicial_tipo": payload.get("abordagem_inicial_tipo", "padrao"),
        "linha_servico_sugerida": payload.get("linha_servico_sugerida", ""),
        "contraparte":            (payload.get("contexto_oportunidade") or {}).get("contraparte", ""),
        "canal":                  "email",
        "oportunidade_id":        payload.get("oportunidade_id", ""),
        "payload_execucao":       payload,
    }

    return preparar_email_para_execucao(
        execucao_compat, identidade, guia, assinaturas, canais_cfg, config_canal
    )


def _carregar_contexto_email() -> tuple:
    """
    Carrega os 5 arquivos de contexto necessários para canal_email_assistido.
    Retorna (identidade, guia, assinaturas, canais, config_canal).
    Usa dicts vazios como fallback para cada arquivo ausente.
    """
    def _ler(nome: str) -> dict:
        caminho = config.PASTA_DADOS / nome
        if caminho.exists():
            with open(caminho, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    identidade   = _ler("identidade_empresa.json")
    guia         = _ler("guia_comunicacao_empresa.json")
    assinaturas  = _ler("assinaturas_empresa.json")
    canais_cfg   = _ler("canais_empresa.json")
    config_canal = _ler("config_canal_email.json")

    return identidade, guia, assinaturas, canais_cfg, config_canal


def _contato_tem_dado(contato: dict, canal: str) -> bool:
    """True se o contato tem a informação necessária para o canal."""
    if canal == "email":
        return bool(contato.get("email") or contato.get("email_principal"))
    if canal == "whatsapp":
        return bool(contato.get("whatsapp") or contato.get("whatsapp_principal"))
    if canal == "telefone":
        return bool(contato.get("telefone") or contato.get("telefone_principal"))
    return False
