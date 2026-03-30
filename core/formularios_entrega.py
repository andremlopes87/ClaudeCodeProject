import logging
"""
core/formularios_entrega.py — Coleta estruturada de dados dos clientes via formulário web.

Fluxo:
  1. Vetor fecha contrato → painel gera link compartilhável (token) para o cliente
  2. Cliente acessa /f/{token} no celular/desktop e preenche o formulário
  3. Dados salvos em dados/formularios_entrega/{conta_id}_{tipo}.json
  4. Sistema notifica feed + avança checklist de entrega automaticamente

Tipos de formulário:
  - presenca_digital      — Google Meu Negócio, fotos, horários
  - atendimento_whatsapp  — FAQ, mensagens do bot, WhatsApp Business
  - agendamento_digital   — Serviços, profissionais, agenda
  - operacao_continua     — Instagram, frequência de posts, conteúdo

Tokens:
  - Validade: 7 dias
  - Armazenados em dados/formularios_entrega/tokens.json
  - Marcado como usado após preenchimento (formulário pode ser reeditado pelo admin)
"""

import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path

import config

PASTA_FORMULARIOS = config.PASTA_DADOS / "formularios_entrega"
PASTA_UPLOADS     = config.PASTA_DADOS / "uploads"
ARQ_TOKENS        = PASTA_FORMULARIOS / "tokens.json"

TIPOS_VALIDOS = {
    "presenca_digital",
    "atendimento_whatsapp",
    "agendamento_digital",
    "operacao_continua",
}

LABELS_TIPO = {
    "presenca_digital":     "Presença Digital",
    "atendimento_whatsapp": "Atendimento WhatsApp",
    "agendamento_digital":  "Agendamento Digital",
    "operacao_continua":    "Operação Contínua",
}

_FOTO_MAX_BYTES  = 5 * 1024 * 1024  # 5 MB
_FOTO_MAX_PIXELS = 720
_TOKEN_VALIDADE_DIAS = 7


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _garantir_pastas() -> None:
    PASTA_FORMULARIOS.mkdir(parents=True, exist_ok=True)
    PASTA_UPLOADS.mkdir(parents=True, exist_ok=True)


def _salvar_atomico(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, caminho)


# ─── Tokens ───────────────────────────────────────────────────────────────────

def _ler_tokens() -> dict:
    if not ARQ_TOKENS.exists():
        return {}
    try:
        return json.loads(ARQ_TOKENS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _salvar_tokens(tokens: dict) -> None:
    _garantir_pastas()
    _salvar_atomico(ARQ_TOKENS, tokens)


def gerar_token(conta_id: str, tipo: str) -> dict:
    """Gera token único com validade de 7 dias."""
    if tipo not in TIPOS_VALIDOS:
        raise ValueError(f"Tipo inválido: {tipo}")

    _garantir_pastas()
    token  = secrets.token_urlsafe(16)
    expira = (datetime.now() + timedelta(days=_TOKEN_VALIDADE_DIAS)).isoformat(timespec="seconds")

    registro = {
        "token":      token,
        "conta_id":   conta_id,
        "tipo":       tipo,
        "criado_em":  _agora(),
        "expira_em":  expira,
        "usado_em":   None,
    }

    tokens = _ler_tokens()
    tokens[token] = registro
    _salvar_tokens(tokens)
    return registro


def verificar_token(token: str) -> dict | None:
    """Retorna dados do token se válido e não expirado, None caso contrário."""
    tokens = _ler_tokens()
    reg = tokens.get(token)
    if not reg:
        return None
    try:
        expira = datetime.fromisoformat(reg["expira_em"])
        if datetime.now() > expira:
            return None
    except Exception:
        return None
    return reg


def marcar_token_usado(token: str) -> None:
    tokens = _ler_tokens()
    if token in tokens:
        tokens[token]["usado_em"] = _agora()
        _salvar_tokens(tokens)


def listar_tokens_ativos() -> list:
    """Lista tokens válidos (não expirados, independente de ter sido usado)."""
    tokens = _ler_tokens()
    agora  = datetime.now()
    ativos = []
    for reg in tokens.values():
        try:
            expira = datetime.fromisoformat(reg["expira_em"])
            if agora <= expira:
                ativos.append(reg)
        except Exception:
            continue
    return sorted(ativos, key=lambda x: x["criado_em"], reverse=True)


# ─── Formulários ──────────────────────────────────────────────────────────────

def _caminho_formulario(conta_id: str, tipo: str) -> Path:
    return PASTA_FORMULARIOS / f"{conta_id}_{tipo}.json"


def salvar_formulario(conta_id: str, tipo: str, dados: dict,
                      token: str | None = None, fotos: list | None = None) -> dict:
    """Salva formulário preenchido. Dispara feed + avança checklist."""
    _garantir_pastas()

    registro = {
        "conta_id":      conta_id,
        "tipo":          tipo,
        "preenchido_em": _agora(),
        "dados":         dados,
        "status":        "preenchido",
        "token":         token,
        "fotos":         fotos or [],
    }

    _salvar_atomico(_caminho_formulario(conta_id, tipo), registro)

    if token:
        marcar_token_usado(token)

    _notificar_feed(conta_id, tipo)
    _avancar_checklist(conta_id, tipo)

    return registro


def salvar_rascunho(conta_id: str, tipo: str, dados: dict) -> None:
    """Salva rascunho parcial. Não sobrescreve formulário já finalizado."""
    _garantir_pastas()
    caminho = _caminho_formulario(conta_id, tipo)
    atual   = obter_formulario(conta_id, tipo) or {}

    if atual.get("status") == "preenchido":
        return

    rascunho = {
        **atual,
        "conta_id":     conta_id,
        "tipo":         tipo,
        "dados":        dados,
        "status":       "rascunho",
        "atualizado_em": _agora(),
    }
    _salvar_atomico(caminho, rascunho)


def obter_formulario(conta_id: str, tipo: str) -> dict | None:
    caminho = _caminho_formulario(conta_id, tipo)
    if not caminho.exists():
        return None
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except Exception:
        return None


def listar_formularios() -> list:
    """Lista todos os formulários com status e nome da conta."""
    _garantir_pastas()
    formularios = []

    for arq in sorted(PASTA_FORMULARIOS.glob("*.json")):
        if arq.name == "tokens.json":
            continue
        try:
            d = json.loads(arq.read_text(encoding="utf-8"))
            formularios.append({
                "conta_id":     d.get("conta_id", ""),
                "tipo":         d.get("tipo", ""),
                "tipo_label":   LABELS_TIPO.get(d.get("tipo", ""), d.get("tipo", "")),
                "status":       d.get("status", ""),
                "data":         d.get("preenchido_em") or d.get("atualizado_em", ""),
                "n_fotos":      len(d.get("fotos", [])),
                "nome_conta":   d.get("conta_id", ""),
            })
        except Exception:
            continue

    # Enriquecer com nome real da conta
    try:
        from core.persistencia import carregar_json_fixo
        contas = carregar_json_fixo("contas_clientes.json", padrao=[])
        mapa   = {c["id"]: c.get("nome_empresa", c["id"]) for c in contas}
        for f in formularios:
            f["nome_conta"] = mapa.get(f["conta_id"], f["conta_id"])
    except Exception as _err:
        logging.warning("erro ignorado: %s", _err)

    return formularios


# ─── Upload de fotos ──────────────────────────────────────────────────────────

def processar_upload_foto(conta_id: str, filename: str, conteudo: bytes) -> str:
    """
    Salva foto e redimensiona para 720px máx (se Pillow disponível).
    Retorna nome do arquivo salvo.
    """
    if len(conteudo) > _FOTO_MAX_BYTES:
        raise ValueError(
            f"Foto muito grande: {len(conteudo) // (1024*1024):.1f}MB (max 5MB)"
        )

    ext = Path(filename).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise ValueError(f"Formato nao aceito: {ext}. Use jpg ou png.")

    pasta = PASTA_UPLOADS / conta_id
    pasta.mkdir(parents=True, exist_ok=True)

    ts         = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:20]
    stem_safe  = "".join(c for c in Path(filename).stem if c.isalnum() or c in "-_")[:30]
    nome_final = f"{ts}_{stem_safe}.jpg"
    caminho    = pasta / nome_final

    try:
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(conteudo))
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        w, h = img.size
        if w > _FOTO_MAX_PIXELS or h > _FOTO_MAX_PIXELS:
            ratio = _FOTO_MAX_PIXELS / max(w, h)
            img   = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        img.save(caminho, "JPEG", quality=85, optimize=True)

    except ImportError:
        # Pillow não instalado — salvar como recebido
        nome_final = f"{ts}_{stem_safe}{ext}"
        caminho    = pasta / nome_final
        caminho.write_bytes(conteudo)

    except Exception:
        # Falha no processamento — salvar original
        nome_final = f"{ts}_{stem_safe}{ext}"
        caminho    = pasta / nome_final
        caminho.write_bytes(conteudo)

    return nome_final


def listar_fotos_conta(conta_id: str) -> list:
    pasta = PASTA_UPLOADS / conta_id
    if not pasta.exists():
        return []
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    return sorted(f.name for f in pasta.iterdir() if f.suffix.lower() in exts)


# ─── Parser de campos dinâmicos ───────────────────────────────────────────────

def _parse_lista(dados_raw: dict, prefixo_campos: list, campo_id: str) -> list:
    """
    Extrai lista de objetos de campos com índice numérico.

    Ex: prefixo_campos = [("pergunta", "faq_pergunta_{}"), ("resposta", "faq_resposta_{}")]
    Gera: [{"pergunta": "...", "resposta": "..."}, ...]
    """
    resultado = []
    i = 0
    while True:
        item = {}
        algum = False
        for campo_dest, template in prefixo_campos:
            chave = template.format(i)
            if chave in dados_raw:
                val = dados_raw[chave].strip() if isinstance(dados_raw[chave], str) else dados_raw[chave]
                item[campo_dest] = val
                if val:
                    algum = True
            else:
                break
        else:
            if algum:
                resultado.append(item)
            i += 1
            continue
        break
    return resultado


def parse_dados_formulario(tipo: str, raw: dict) -> dict:
    """
    Converte campos planos do form (str keys/values) em estrutura semântica.
    raw: dict de campo -> valor (strings simples, sem UploadFile).
    """
    dados: dict = {}

    # ── Campos comuns a todos os tipos ────────────────────────────────────────
    for campo in [
        "nome_negocio", "endereco_rua", "endereco_numero", "endereco_bairro",
        "endereco_cidade", "endereco_cep", "telefone_principal", "whatsapp",
        "categoria", "servicos", "descricao_curta",
        "email_responsavel", "nome_responsavel",
    ]:
        if campo in raw:
            dados[campo] = raw[campo].strip()

    # Formas de pagamento (checkboxes → lista)
    dados["formas_pagamento"] = [
        v.strip() for k, v in raw.items() if k.startswith("pgto_") and v
    ]

    # Horário de funcionamento
    dias = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
    horarios = {}
    for dia in dias:
        fechado   = raw.get(f"horario_{dia}_fechado") == "on"
        abertura  = raw.get(f"horario_{dia}_abertura", "").strip()
        fechamento = raw.get(f"horario_{dia}_fechamento", "").strip()
        horarios[dia] = {
            "fechado":    fechado,
            "abertura":   "" if fechado else abertura,
            "fechamento": "" if fechado else fechamento,
        }
    dados["horario_funcionamento"] = horarios

    if tipo == "presenca_digital":
        pass  # só campos comuns

    elif tipo == "atendimento_whatsapp":
        # FAQs
        faqs = []
        i = 0
        while f"faq_pergunta_{i}" in raw:
            p = raw.get(f"faq_pergunta_{i}", "").strip()
            r = raw.get(f"faq_resposta_{i}", "").strip()
            if p or r:
                faqs.append({"pergunta": p, "resposta": r})
            i += 1
        dados["perguntas_frequentes"] = faqs

        dados["mensagem_boas_vindas"]     = raw.get("mensagem_boas_vindas", "").strip()
        dados["boas_vindas_vetor_criar"]  = raw.get("boas_vindas_vetor_criar") == "on"
        dados["mensagem_fora_horario"]    = raw.get("mensagem_fora_horario", "").strip()
        dados["fora_horario_vetor_criar"] = raw.get("fora_horario_vetor_criar") == "on"
        dados["encaminhar_para"]          = raw.get("encaminhar_para", "").strip()
        dados["whatsapp_business"]        = raw.get("whatsapp_business", "").strip()
        dados["whatsapp_business_novo"]   = raw.get("whatsapp_business_novo") == "on"

    elif tipo == "agendamento_digital":
        # Serviços com duração
        servicos = []
        i = 0
        while f"servico_nome_{i}" in raw:
            nome = raw.get(f"servico_nome_{i}", "").strip()
            dur  = raw.get(f"servico_duracao_{i}", "").strip()
            if nome:
                servicos.append({"nome": nome, "duracao_min": dur})
            i += 1
        dados["servicos_agendamento"] = servicos

        # Profissionais
        profissionais = []
        i = 0
        while f"prof_nome_{i}" in raw:
            nome    = raw.get(f"prof_nome_{i}", "").strip()
            horario = raw.get(f"prof_horario_{i}", "").strip()
            folga   = raw.get(f"prof_folga_{i}", "").strip()
            if nome:
                profissionais.append({"nome": nome, "horario": horario, "folga": folga})
            i += 1
        dados["profissionais"] = profissionais

        dados["intervalo_atendimentos_min"] = raw.get("intervalo_atendimentos", "").strip()
        dados["conta_google"]               = raw.get("conta_google", "").strip()
        dados["conta_google_nova"]          = raw.get("conta_google_nova") == "on"

    elif tipo == "operacao_continua":
        dados["instagram"]            = raw.get("instagram", "").strip()
        dados["instagram_criar_novo"] = raw.get("instagram_criar_novo") == "on"
        dados["frequencia_posts"]     = raw.get("frequencia_posts", "").strip()
        dados["tom_comunicacao"]      = raw.get("tom_comunicacao", "").strip()
        dados["tipo_conteudo"]        = [
            v.strip() for k, v in raw.items() if k.startswith("conteudo_") and v
        ]

    return dados


# ─── Integrações internas ──────────────────────────────────────────────────────

def _notificar_feed(conta_id: str, tipo: str) -> None:
    try:
        from core.persistencia import carregar_json_fixo, salvar_json_fixo
        feed = carregar_json_fixo("feed_eventos_empresa.json", padrao=[])
        feed.append({
            "tipo":             "formulario_preenchido",
            "conta_id":         conta_id,
            "tipo_formulario":  tipo,
            "label":            LABELS_TIPO.get(tipo, tipo),
            "descricao":        f"Formulário '{LABELS_TIPO.get(tipo, tipo)}' preenchido — conta {conta_id}",
            "timestamp":        _agora(),
        })
        salvar_json_fixo(feed[-500:], "feed_eventos_empresa.json")
    except Exception as _err:
        logging.warning("erro ignorado: %s", _err)


def _avancar_checklist(conta_id: str, tipo: str) -> None:
    """Marca item de checklist de entrega correspondente como concluído."""
    _MAPEAMENTO = {
        "presenca_digital":     "formulario_presenca_digital",
        "atendimento_whatsapp": "formulario_atendimento_whatsapp",
        "agendamento_digital":  "formulario_agendamento_digital",
        "operacao_continua":    "formulario_operacao_continua",
    }
    item_id = _MAPEAMENTO.get(tipo)
    if not item_id:
        return

    try:
        from core.persistencia import carregar_json_fixo, salvar_json_fixo
        pipeline  = carregar_json_fixo("pipeline_entrega.json", padrao=[])
        alterado  = False

        for entrega in pipeline:
            if entrega.get("conta_id") != conta_id:
                continue
            for item in entrega.get("checklist", []):
                match = (
                    item.get("id") == item_id
                    or item_id.replace("_", " ") in item.get("descricao", "").lower()
                    or "formulario" in item.get("descricao", "").lower()
                )
                if match and item.get("status") != "concluido":
                    item["status"]       = "concluido"
                    item["concluido_em"] = _agora()
                    alterado = True

        if alterado:
            salvar_json_fixo(pipeline, "pipeline_entrega.json")
    except Exception as _err:
        logging.warning("erro ignorado: %s", _err)


# ─── Snapshot para o painel ───────────────────────────────────────────────────

def resumir_para_painel(conta_id: str | None = None) -> dict:
    """Snapshot para a página /formularios do painel."""
    formularios   = listar_formularios()
    tokens_ativos = listar_tokens_ativos()

    if conta_id:
        formularios   = [f for f in formularios   if f["conta_id"] == conta_id]
        tokens_ativos = [t for t in tokens_ativos if t["conta_id"] == conta_id]

    pendentes    = [f for f in formularios if f["status"] == "rascunho"]
    preenchidos  = [f for f in formularios if f["status"] == "preenchido"]

    return {
        "formularios":    formularios,
        "tokens_ativos":  tokens_ativos,
        "n_pendentes":    len(pendentes),
        "n_preenchidos":  len(preenchidos),
        "n_tokens":       len(tokens_ativos),
        "tipos_validos":  list(TIPOS_VALIDOS),
        "labels_tipo":    LABELS_TIPO,
    }
