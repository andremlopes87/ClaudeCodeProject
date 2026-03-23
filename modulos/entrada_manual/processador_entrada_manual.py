"""
modulos/entrada_manual/processador_entrada_manual.py

Canal de entrada manual de empresas pelo conselho (v0.38).

O conselho pode inserir uma empresa diretamente, sem depender do fluxo OSM/prospeccao.
Três modos de operação:

  avaliacao_manual  → analisa a empresa, gera avaliação, retorna feedback. Não injeta.
  injetar_no_fluxo  → analisa + injeta na fila_execucao_comercial.json (agente_comercial pega).
  venda_manual      → registra negócio já fechado: cria oportunidade "ganho" + entrega.

Reutiliza:
  modulos/prospeccao_operacional/priorizador.py    → score_prontidao_ia
  modulos/prospeccao_operacional/abordabilidade.py → abordavel_agora
  modulos/comercial/planejador_comercial.py        → plano comercial completo

Arquivos gerenciados:
  dados/entrada_manual_empresas.json    → registro de todas as entradas
  dados/avaliacoes_manuais.json         → avaliações geradas
  dados/historico_entrada_manual.json   → trilha de auditoria
"""

import json
import logging
import socket
import uuid
from datetime import datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_ARQ_ENTRADAS  = config.PASTA_DADOS / "entrada_manual_empresas.json"
_ARQ_AVALIACOES = config.PASTA_DADOS / "avaliacoes_manuais.json"
_ARQ_HISTORICO  = config.PASTA_DADOS / "historico_entrada_manual.json"

_MODOS_VALIDOS = {"avaliacao_manual", "injetar_no_fluxo", "venda_manual"}

# Pesos de presença digital para avaliação manual (mesma lógica do diagnosticador_presenca)
_PESOS_PRESENCA = {
    "site":       20,
    "https":      10,
    "telefone":   20,
    "email":      15,
    "whatsapp":   15,
    "instagram":  10,
    "facebook":   5,
    "cta":        5,
}


# ─── I/O ─────────────────────────────────────────────────────────────────────

def _carregar(arq: Path, padrao) -> list | dict:
    if not arq.exists():
        return padrao
    try:
        return json.loads(arq.read_text(encoding="utf-8"))
    except Exception:
        return padrao


def _salvar(arq: Path, dados) -> None:
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ─── Normalização ─────────────────────────────────────────────────────────────

def normalizar_entrada_manual(entrada: dict) -> dict:
    """
    Normaliza campos da entrada: limpa nome, padroniza URL, formata telefone.
    Retorna cópia normalizada sem modificar o original.
    """
    e = dict(entrada)

    # Nome: strip e title case se tudo maiúsculo
    nome = (e.get("nome") or "").strip()
    if nome.isupper():
        nome = nome.title()
    e["nome"] = nome

    # Site: garantir schema
    site = (e.get("site") or "").strip()
    if site and not site.startswith("http"):
        site = "https://" + site
    e["site"] = site

    # Instagram: remover @ e URL base se presente
    ig = (e.get("instagram") or "").strip()
    ig = ig.replace("https://instagram.com/", "").replace("https://www.instagram.com/", "")
    ig = ig.lstrip("@").rstrip("/")
    e["instagram"] = ig

    # Facebook: similar
    fb = (e.get("facebook") or "").strip()
    fb = fb.replace("https://facebook.com/", "").replace("https://www.facebook.com/", "")
    fb = fb.lstrip("@").rstrip("/")
    e["facebook"] = fb

    # WhatsApp: apenas dígitos
    wa = (e.get("whatsapp") or "").strip()
    wa_digits = "".join(c for c in wa if c.isdigit())
    e["whatsapp"] = wa_digits or wa

    # Telefone: apenas dígitos
    tel = (e.get("telefone") or "").strip()
    tel_digits = "".join(c for c in tel if c.isdigit())
    e["telefone"] = tel_digits or tel

    # Email: lowercase
    e["email"] = (e.get("email") or "").strip().lower()

    # Cidade/estado: strip
    e["cidade"] = (e.get("cidade") or "").strip()
    e["estado"] = (e.get("estado") or "").strip().upper()

    # Modo padrão
    if e.get("modo") not in _MODOS_VALIDOS:
        e["modo"] = "avaliacao_manual"

    return e


# ─── Deduplição ────────────────────────────────────────────────────────────────

def deduplicar_entrada_manual(entrada: dict) -> dict | None:
    """
    Verifica se já existe empresa similar no pipeline_comercial, fila_execucao ou entradas anteriores.

    Critérios (qualquer um que combine):
    - nome normalizado igual (case-insensitive, strip)
    - site igual (sem schema)
    - instagram igual (não vazio)
    - telefone igual (apenas dígitos, não vazio)

    Retorna o registro duplicado encontrado, ou None se não houver.
    """
    nome_n = (entrada.get("nome") or "").lower().strip()
    site_n = _normalizar_url(entrada.get("site") or "")
    ig_n   = (entrada.get("instagram") or "").lower().strip()
    tel_n  = "".join(c for c in (entrada.get("telefone") or "") if c.isdigit())

    def _match(candidato: dict) -> bool:
        nome_c = (candidato.get("nome") or candidato.get("contraparte") or "").lower().strip()
        site_c = _normalizar_url(candidato.get("site") or candidato.get("website") or "")
        ig_c   = (candidato.get("instagram") or "").lower().strip()
        tel_c  = "".join(c for c in (candidato.get("telefone") or "") if c.isdigit())

        if nome_n and nome_c and nome_n == nome_c:
            return True
        if site_n and site_c and site_n == site_c:
            return True
        if ig_n and ig_c and ig_n == ig_c:
            return True
        if tel_n and tel_c and len(tel_n) >= 8 and tel_n == tel_c:
            return True
        return False

    # Checar entradas manuais anteriores (não processadas = em loop)
    entradas = _carregar(_ARQ_ENTRADAS, [])
    for e in entradas:
        if e.get("id") != entrada.get("id") and _match(e):
            return e

    # Checar pipeline comercial
    arq_pipeline = config.PASTA_DADOS / "pipeline_comercial.json"
    pipeline = _carregar(arq_pipeline, [])
    for opp in pipeline:
        if opp.get("estagio") not in ("perdido",) and _match(opp):
            return opp

    # Checar fila de execução
    arq_fila = config.PASTA_DADOS / "fila_execucao_comercial.json"
    fila = _carregar(arq_fila, [])
    for item in fila:
        if _match(item):
            return item

    return None


def _normalizar_url(url: str) -> str:
    """Remove schema, www e trailing slash para comparação."""
    url = url.lower().strip()
    for prefix in ("https://www.", "http://www.", "https://", "http://"):
        if url.startswith(prefix):
            url = url[len(prefix):]
    return url.rstrip("/")


# ─── Avaliação ─────────────────────────────────────────────────────────────────

def avaliar_empresa_manual(entrada: dict) -> dict:
    """
    Avalia a empresa com base nos dados fornecidos manualmente.

    Constrói um dict sintético compatível com o pipeline de módulos existentes,
    calcula score de presença, prioridade e plano comercial.

    Retorna avaliação completa.
    """
    entrada_id = entrada.get("id", "")
    agora = _agora()

    # 1. Construir candidata sintética
    candidata = _construir_candidata(entrada)

    # 2. Calcular score de presença
    score_presenca = _calcular_score_presenca(candidata)
    candidata["score_presenca_digital"] = score_presenca

    # 3. Classificar comercialmente
    cls = _classificar_presenca(candidata)
    candidata["classificacao_presenca_comercial"] = cls

    # 4. Definir campos de marketing mínimos para planejador_comercial
    _preencher_campos_marketing(candidata, cls)

    # 5. Priorização
    from modulos.prospeccao_operacional.priorizador import _priorizar
    candidata = _priorizar(candidata)

    # 6. Abordabilidade
    from modulos.prospeccao_operacional.abordabilidade import _calcular as _calc_abord
    candidata = _calc_abord(candidata)

    # 7. Plano comercial
    from modulos.comercial.planejador_comercial import planejar_comercial
    [candidata] = planejar_comercial([candidata])

    # 8. Montar avaliação
    avaliacao = {
        "id":              f"aval_{entrada_id}",
        "entrada_id":      entrada_id,
        "empresa_nome":    entrada.get("nome", ""),
        "modo":            entrada.get("modo", "avaliacao_manual"),
        "avaliado_em":     agora,
        "score_presenca":  score_presenca,
        "classificacao_presenca_comercial": cls,
        "score_prontidao_ia":   candidata.get("score_prontidao_ia", 0),
        "classificacao_comercial": candidata.get("classificacao_comercial", ""),
        "prioridade_abordagem":  candidata.get("prioridade_abordagem", "nula"),
        "motivo_prioridade":     candidata.get("motivo_prioridade", ""),
        "abordavel_agora":       candidata.get("abordavel_agora", False),
        "canal_abordagem_sugerido": candidata.get("canal_abordagem_sugerido", ""),
        "contato_principal":     candidata.get("contato_principal", ""),
        "plano_comercial_gerado": candidata.get("plano_comercial_gerado", False),
        "oferta_principal_comercial": candidata.get("oferta_principal_comercial", ""),
        "motivo_oferta_principal":    candidata.get("motivo_oferta_principal", ""),
        "abordagem_comercial_inicial": candidata.get("abordagem_comercial_inicial", ""),
        "proxima_acao_comercial":      candidata.get("proxima_acao_comercial", ""),
        "status_comercial_sugerido":   candidata.get("status_comercial_sugerido", ""),
        "nivel_prioridade_comercial":  candidata.get("nivel_prioridade_comercial", "sem_dados"),
        "candidata_completa":          candidata,
    }

    return avaliacao


def _construir_candidata(entrada: dict) -> dict:
    """
    Monta dict sintético de empresa a partir dos campos do formulário,
    compatível com os módulos priorizador, abordabilidade e planejador_comercial.
    """
    nome    = entrada.get("nome", "")
    site    = entrada.get("site", "")
    telefone = entrada.get("telefone", "")
    email   = entrada.get("email", "")
    whatsapp = entrada.get("whatsapp", "")
    instagram = entrada.get("instagram", "")
    facebook  = entrada.get("facebook", "")
    categoria = entrada.get("categoria", "")
    cidade   = entrada.get("cidade", "")
    estado   = entrada.get("estado", "")

    tem_site      = bool(site)
    tem_telefone  = bool(telefone)
    tem_email     = bool(email)
    tem_whatsapp  = bool(whatsapp)
    tem_instagram = bool(instagram)
    tem_facebook  = bool(facebook)
    usa_https     = site.startswith("https://") if site else False

    # sinais: compatível com priorizador e abordabilidade
    sinais = {
        "tem_website":  tem_site,
        "tem_telefone": tem_telefone,
        "tem_email":    tem_email,
        "tem_whatsapp": tem_whatsapp,
        "tem_instagram": tem_instagram,
        "tem_facebook": tem_facebook,
        "tem_horario":  False,  # não informado no formulário
    }

    # confianca_* = "alta" para tudo que foi fornecido manualmente (ground truth do conselho)
    confiancas = {}
    for canal, val in [
        ("telefone", tem_telefone), ("email", tem_email),
        ("whatsapp", tem_whatsapp), ("instagram", tem_instagram),
        ("facebook", tem_facebook), ("website", tem_site),
    ]:
        confiancas[f"confianca_{canal}"] = "alta" if val else "nao_identificado"

    # campos de confirmação para _canal_principal e _gap_codigo
    confirmados = {
        "telefone_confirmado":  telefone if tem_telefone else None,
        "email_confirmado":     email if tem_email else None,
        "whatsapp_confirmado":  whatsapp if tem_whatsapp else None,
        "instagram_confirmado": instagram if tem_instagram else None,
        "facebook_confirmado":  facebook if tem_facebook else None,
        "website_confirmado":   site if tem_site else None,
        "site_acessivel":       tem_site,   # assume acessível se fornecido
        "tem_site":             tem_site,
        "usa_https":            usa_https,
        "tem_cta_clara":        False,      # não verificável pelo formulário
    }

    # campos_osm_preenchidos: número de canais fornecidos (análogo ao OSM)
    campos_preenchidos = sum([
        tem_telefone, tem_email, tem_whatsapp,
        tem_instagram, tem_facebook, tem_site,
    ])

    cat_id = _normalizar_categoria_id(categoria)

    candidata = {
        "nome":                 nome,
        "categoria":            categoria or "estabelecimento",
        "categoria_id":         cat_id,
        "cidade":               cidade,
        "estado":               estado,
        "telefone":             telefone,
        "email":                email,
        "whatsapp":             whatsapp,
        "instagram":            instagram,
        "facebook":             facebook,
        "website":              site,
        "sinais":               sinais,
        "tem_instagram":        tem_instagram,
        "campos_osm_preenchidos": campos_preenchidos,
        "origem_oportunidade":  "manual_conselho",
        **confiancas,
        **confirmados,
    }

    return candidata


def _calcular_score_presenca(candidata: dict) -> int:
    """Calcula score de presença digital (0-100) a partir dos campos fornecidos."""
    score = 0
    sinais = candidata.get("sinais", {})

    if sinais.get("tem_website"):
        score += _PESOS_PRESENCA["site"]
        if candidata.get("usa_https"):
            score += _PESOS_PRESENCA["https"]
    if sinais.get("tem_telefone"):
        score += _PESOS_PRESENCA["telefone"]
    if sinais.get("tem_email"):
        score += _PESOS_PRESENCA["email"]
    if sinais.get("tem_whatsapp"):
        score += _PESOS_PRESENCA["whatsapp"]
    if sinais.get("tem_instagram"):
        score += _PESOS_PRESENCA["instagram"]
    if sinais.get("tem_facebook"):
        score += _PESOS_PRESENCA["facebook"]

    return min(score, 100)


def _classificar_presenca(candidata: dict) -> str:
    """
    Classifica oportunidade de presença digital para a empresa.
    Espelha a lógica do consolidador_presenca.py.
    """
    nome = candidata.get("nome", "")
    if not nome or nome == "(sem nome registrado)":
        return "pouca_utilidade_presenca"

    score = candidata.get("score_presenca_digital", 0)
    sinais = candidata.get("sinais", {})
    tem_qualquer_canal = any([
        sinais.get("tem_website"), sinais.get("tem_telefone"),
        sinais.get("tem_email"), sinais.get("tem_whatsapp"),
        sinais.get("tem_instagram"), sinais.get("tem_facebook"),
    ])

    if not tem_qualquer_canal:
        return "oportunidade_alta_presenca"  # empresa completamente offline
    if not sinais.get("tem_website"):
        return "oportunidade_alta_presenca"  # sem site = grande oportunidade
    if score < 45:
        return "oportunidade_alta_presenca"
    if score < 70:
        return "oportunidade_media_presenca"
    if score < 90:
        return "oportunidade_baixa_presenca"
    return "presenca_otimizavel"


def _preencher_campos_marketing(candidata: dict, cls: str) -> None:
    """
    Preenche campos de marketing mínimos necessários para planejador_comercial.
    Apenas para compatibilidade — o conselho já forneceu os dados diretamente.
    """
    if cls == "pouca_utilidade_presenca":
        candidata["plano_marketing_gerado"] = False
        candidata["nivel_complexidade_execucao"] = "alta"
        return

    # Determinar complexidade: sem site = baixa (simples de resolver),
    # com site mas gaps = média
    sinais = candidata.get("sinais", {})
    if not sinais.get("tem_website"):
        candidata["nivel_complexidade_execucao"] = "baixa"
    elif not sinais.get("tem_whatsapp") or not sinais.get("tem_email"):
        candidata["nivel_complexidade_execucao"] = "baixa"
    else:
        candidata["nivel_complexidade_execucao"] = "media"

    # score_presenca_consolidado: mesmo valor que score_presenca_digital para manual
    candidata["score_presenca_consolidado"] = candidata.get("score_presenca_digital", 0)
    candidata["plano_marketing_gerado"] = True

    # Campos de resumo de marketing (texto genérico)
    candidata["gargalo_principal_marketing"] = _derivar_gargalo(sinais)
    candidata["resumo_oportunidade_marketing"] = ""
    candidata["proposta_resumida_marketing"]   = ""


def _derivar_gargalo(sinais: dict) -> str:
    if not sinais.get("tem_website"):
        return "sem presença digital própria"
    if not sinais.get("tem_whatsapp"):
        return "sem canal de mensagem imediato"
    if not sinais.get("tem_email"):
        return "sem e-mail público de contato"
    if not sinais.get("tem_instagram"):
        return "sem presença em redes sociais"
    return "presença digital pode ser otimizada"


def _normalizar_categoria_id(categoria: str) -> str:
    """Normaliza a string de categoria para o ID usado nos planejadores."""
    mapa = {
        "barbearia": "barbearia",
        "salão de beleza": "salao_de_beleza", "salao de beleza": "salao_de_beleza",
        "oficina mecânica": "oficina_mecanica", "oficina mecanica": "oficina_mecanica",
        "borracharia": "borracharia",
        "açougue": "acougue", "acougue": "acougue",
        "padaria": "padaria",
        "autopeças": "autopecas", "autopecas": "autopecas",
        "restaurante": "restaurante",
        "farmácia": "farmacia", "farmacia": "farmacia",
    }
    return mapa.get((categoria or "").lower().strip(), "default")


# ─── Registro e persistência ─────────────────────────────────────────────────

def registrar_historico_entrada_manual(
    entrada_id: str,
    evento: str,
    descricao: str,
    origem: str = "sistema",
) -> None:
    """Registra evento no histórico de auditoria."""
    historico = _carregar(_ARQ_HISTORICO, [])
    historico.append({
        "id":         str(uuid.uuid4())[:8],
        "entrada_id": entrada_id,
        "evento":     evento,
        "descricao":  descricao,
        "origem":     origem,
        "registrado_em": _agora(),
    })
    _salvar(_ARQ_HISTORICO, historico[-500:])


def _salvar_entrada(entrada: dict) -> None:
    entradas = _carregar(_ARQ_ENTRADAS, [])
    # Substituir se já existe, senão append
    idx = next((i for i, e in enumerate(entradas) if e.get("id") == entrada.get("id")), None)
    if idx is not None:
        entradas[idx] = entrada
    else:
        entradas.append(entrada)
    _salvar(_ARQ_ENTRADAS, entradas)


def _salvar_avaliacao(avaliacao: dict) -> None:
    avaliacoes = _carregar(_ARQ_AVALIACOES, [])
    idx = next((i for i, a in enumerate(avaliacoes) if a.get("id") == avaliacao.get("id")), None)
    if idx is not None:
        avaliacoes[idx] = avaliacao
    else:
        avaliacoes.append(avaliacao)
    _salvar(_ARQ_AVALIACOES, avaliacoes[-500:])


# ─── Injeção no fluxo comercial ───────────────────────────────────────────────

def injetar_no_fluxo_comercial(entrada: dict, avaliacao: dict) -> dict:
    """
    Injeta a empresa na fila_execucao_comercial.json.
    O agente_comercial vai processar na próxima execução.

    Retorna o registro injetado.
    """
    arq_fila = config.PASTA_DADOS / "fila_execucao_comercial.json"
    fila = _carregar(arq_fila, [])

    candidata = avaliacao.get("candidata_completa", {})
    agora = _agora()

    registro = {
        "id":                        f"manual_{entrada['id']}",
        "origem_oportunidade":       "manual_conselho",
        "nome":                      entrada.get("nome", ""),
        "contraparte":               entrada.get("nome", ""),
        "categoria":                 entrada.get("categoria", ""),
        "categoria_id":              candidata.get("categoria_id", "default"),
        "cidade":                    entrada.get("cidade", ""),
        "estado":                    entrada.get("estado", ""),
        "telefone":                  entrada.get("telefone", ""),
        "email":                     entrada.get("email", ""),
        "whatsapp":                  entrada.get("whatsapp", ""),
        "instagram":                 entrada.get("instagram", ""),
        "facebook":                  entrada.get("facebook", ""),
        "website":                   entrada.get("site", ""),
        "score_presenca_digital":    avaliacao.get("score_presenca", 0),
        "score_prontidao_ia":        avaliacao.get("score_prontidao_ia", 0),
        "classificacao_comercial":   avaliacao.get("classificacao_comercial", ""),
        "prioridade_abordagem":      avaliacao.get("prioridade_abordagem", "media"),
        "canal_abordagem_sugerido":  avaliacao.get("canal_abordagem_sugerido", ""),
        "contato_principal":         avaliacao.get("contato_principal", ""),
        "oferta_principal_comercial": avaliacao.get("oferta_principal_comercial", ""),
        "abordagem_comercial_inicial": avaliacao.get("abordagem_comercial_inicial", ""),
        "proxima_acao_comercial":    avaliacao.get("proxima_acao_comercial", ""),
        "status_comercial_sugerido": avaliacao.get("status_comercial_sugerido", "identificado"),
        "nivel_prioridade_comercial": avaliacao.get("nivel_prioridade_comercial", "media"),
        "observacoes_conselho":      entrada.get("observacoes", ""),
        "injetado_em":               agora,
        "entrada_manual_id":         entrada["id"],
    }

    # Dedup por id
    if not any(f.get("id") == registro["id"] for f in fila):
        fila.append(registro)
        _salvar(arq_fila, fila)
        logger.info(f"[entrada_manual] Empresa '{registro['nome']}' injetada na fila comercial")

    return registro


def encaminhar_para_entrega_se_manual_sale(entrada: dict, avaliacao: dict) -> dict:
    """
    Para modo venda_manual:
    1. Cria oportunidade no pipeline_comercial com estagio="ganho"
    2. Cria entrega no pipeline_entrega

    O agente_operacao_entrega pegará na próxima execução para criar o checklist.
    """
    arq_pipeline   = config.PASTA_DADOS / "pipeline_comercial.json"
    arq_entrega    = config.PASTA_DADOS / "pipeline_entrega.json"

    pipeline  = _carregar(arq_pipeline, [])
    p_entrega = _carregar(arq_entrega, [])

    agora      = _agora()
    entrada_id = entrada["id"]
    opp_id     = f"man_opp_{entrada_id}"
    ent_id     = f"ent_{opp_id}"

    valor = entrada.get("valor_venda")
    try:
        valor = float(valor) if valor else None
    except (TypeError, ValueError):
        valor = None

    servico = entrada.get("servico_vendido", "") or avaliacao.get("oferta_principal_comercial", "")
    linha   = _inferir_linha_servico(servico)

    # Oportunidade "ganho" no pipeline comercial
    opp = {
        "id":                     opp_id,
        "contraparte":            entrada.get("nome", ""),
        "nome":                   entrada.get("nome", ""),
        "categoria":              entrada.get("categoria", ""),
        "cidade":                 entrada.get("cidade", ""),
        "estado":                 entrada.get("estado", ""),
        "telefone":               entrada.get("telefone", ""),
        "email":                  entrada.get("email", ""),
        "whatsapp":               entrada.get("whatsapp", ""),
        "estagio":                "ganho",
        "status_operacional":     "onboarding",
        "origem_oportunidade":    "manual_conselho",
        "linha_servico_sugerida": linha,
        "servico_contratado":     servico,
        "valor_estimado":         valor,
        "contato_principal":      avaliacao.get("contato_principal", ""),
        "canal_abordagem_sugerido": avaliacao.get("canal_abordagem_sugerido", ""),
        "prioridade":             "alta",
        "observacoes_conselho":   entrada.get("observacoes", ""),
        "entrada_manual_id":      entrada_id,
        "criado_em":              agora,
        "atualizado_em":          agora,
    }

    # Entrega correspondente
    entrega = {
        "id":               ent_id,
        "oportunidade_id":  opp_id,
        "contraparte":      entrada.get("nome", ""),
        "linha_servico":    linha,
        "tipo_entrega":     _tipo_entrega_por_linha(linha),
        "status_entrega":   "nova",
        "prioridade":       "alta",
        "etapa_atual":      "onboarding",
        "checklist_id":     None,
        "bloqueios":        [],
        "depende_de":       None,
        "origem_comercial": "manual_conselho_venda_direta",
        "contato_principal": avaliacao.get("contato_principal", ""),
        "valor_estimado":   valor,
        "cidade":           entrada.get("cidade", ""),
        "registrado_em":    agora,
        "atualizado_em":    agora,
    }

    # Dedup por id
    if not any(o.get("id") == opp_id for o in pipeline):
        pipeline.append(opp)
        _salvar(arq_pipeline, pipeline)
        logger.info(f"[entrada_manual] Oportunidade '{opp['contraparte']}' registrada como ganho")

    if not any(e.get("id") == ent_id for e in p_entrega):
        p_entrega.append(entrega)
        _salvar(arq_entrega, p_entrega)
        logger.info(f"[entrada_manual] Entrega '{ent_id}' criada no pipeline de entrega")

    return {"oportunidade": opp, "entrega": entrega}


def _inferir_linha_servico(servico: str) -> str:
    servico_l = (servico or "").lower()
    if any(k in servico_l for k in ("site", "instagram", "presença", "presenca", "marketing", "digital")):
        return "marketing_presenca_digital"
    if any(k in servico_l for k in ("whatsapp", "atendimento", "chatbot", "automação", "automacao")):
        return "automacao_atendimento"
    return "marketing_presenca_digital"


def _tipo_entrega_por_linha(linha: str) -> str:
    return {
        "marketing_presenca_digital": "implantacao_presenca_digital",
        "automacao_atendimento":      "implantacao_automacao",
    }.get(linha, "entrega_padrao")


# ─── Ponto de entrada principal ───────────────────────────────────────────────

def processar_entrada_manual(dados_form: dict) -> dict:
    """
    Processa uma entrada manual de empresa submetida pelo conselho.

    Fluxo:
    1. Normalizar dados do formulário
    2. Verificar duplicata
    3. Gerar avaliação (prioridade, plano comercial)
    4. Persistir entrada + avaliação
    5. Rotear conforme modo (avaliacao_manual / injetar_no_fluxo / venda_manual)
    6. Registrar histórico

    Retorna dict com resultado completo.
    """
    agora = _agora()

    # 1. Normalizar
    entrada = normalizar_entrada_manual(dados_form)
    entrada["id"]          = entrada.get("id") or str(uuid.uuid4())[:12]
    entrada["submetido_em"] = entrada.get("submetido_em") or agora
    entrada["status"]      = "processando"
    entrada["submetido_por"] = entrada.get("submetido_por") or "conselho"

    # 2. Verificar duplicata
    duplicata = deduplicar_entrada_manual(entrada)
    if duplicata and not dados_form.get("forcar_insercao"):
        entrada["status"] = "duplicata_detectada"
        entrada["duplicata_ref"] = duplicata.get("id") or duplicata.get("nome", "?")
        _salvar_entrada(entrada)
        registrar_historico_entrada_manual(
            entrada["id"], "duplicata_detectada",
            f"Empresa '{entrada['nome']}' já existe: {duplicata.get('nome', '?')}",
        )
        return {
            "status":    "duplicata",
            "entrada":   entrada,
            "duplicata": duplicata,
            "mensagem":  f"Empresa já existe no sistema: {duplicata.get('nome', '?')}",
        }

    # 3. Avaliação
    avaliacao = avaliar_empresa_manual(entrada)
    _salvar_avaliacao(avaliacao)

    # 4. Persistir entrada
    entrada["status"]      = "avaliado"
    entrada["avaliacao_id"] = avaliacao["id"]
    _salvar_entrada(entrada)
    registrar_historico_entrada_manual(
        entrada["id"], "entrada_registrada",
        f"Empresa '{entrada['nome']}' avaliada | score={avaliacao['score_presenca']} "
        f"| prioridade={avaliacao['prioridade_abordagem']}",
    )

    resultado: dict = {
        "status":    "ok",
        "entrada":   entrada,
        "avaliacao": avaliacao,
        "injetado":  False,
        "entrega":   None,
        "mensagem":  "",
    }

    modo = entrada.get("modo", "avaliacao_manual")

    # 5. Roteamento por modo
    if modo == "injetar_no_fluxo":
        registro_fila = injetar_no_fluxo_comercial(entrada, avaliacao)
        entrada["status"] = "injetado_comercial"
        _salvar_entrada(entrada)
        registrar_historico_entrada_manual(
            entrada["id"], "injetado_comercial",
            f"Empresa injetada na fila comercial | id={registro_fila['id']}",
        )
        resultado["injetado"] = True
        resultado["registro_fila"] = registro_fila
        resultado["mensagem"] = (
            f"'{entrada['nome']}' injetada na fila comercial. "
            f"Prioridade: {avaliacao['prioridade_abordagem']} | "
            f"Canal: {avaliacao['canal_abordagem_sugerido'] or 'a definir'}"
        )

    elif modo == "venda_manual":
        entrega_resultado = encaminhar_para_entrega_se_manual_sale(entrada, avaliacao)
        entrada["status"] = "venda_registrada"
        _salvar_entrada(entrada)
        registrar_historico_entrada_manual(
            entrada["id"], "venda_registrada",
            f"Venda manual registrada | opp={entrega_resultado['oportunidade']['id']} "
            f"| entrega={entrega_resultado['entrega']['id']}",
        )
        resultado["entrega"] = entrega_resultado
        resultado["injetado"] = True
        resultado["mensagem"] = (
            f"Venda de '{entrada['nome']}' registrada. "
            f"Entrega criada: {entrega_resultado['entrega']['id']} | "
            f"Linha: {entrega_resultado['entrega']['linha_servico']}"
        )

    else:  # avaliacao_manual
        resultado["mensagem"] = (
            f"'{entrada['nome']}' avaliada. "
            f"Score presença: {avaliacao['score_presenca']}/100 | "
            f"Prioridade: {avaliacao['prioridade_abordagem']} | "
            f"Canal sugerido: {avaliacao['canal_abordagem_sugerido'] or 'sem canal direto'}"
        )

    return resultado


# ─── Consultas para o painel ──────────────────────────────────────────────────

def carregar_entradas_manuais_pendentes() -> list:
    """Retorna entradas com status pendente ou avaliado (não injetadas ainda)."""
    entradas = _carregar(_ARQ_ENTRADAS, [])
    return [e for e in entradas if e.get("status") in ("pendente", "avaliado")]


def carregar_todas_entradas_manuais() -> list:
    """Retorna todas as entradas ordenadas pela mais recente."""
    entradas = _carregar(_ARQ_ENTRADAS, [])
    return sorted(entradas, key=lambda e: e.get("submetido_em", ""), reverse=True)


def carregar_avaliacao_por_entrada(entrada_id: str) -> dict | None:
    """Retorna avaliação associada a uma entrada, ou None."""
    avaliacoes = _carregar(_ARQ_AVALIACOES, [])
    return next((a for a in avaliacoes if a.get("entrada_id") == entrada_id), None)
