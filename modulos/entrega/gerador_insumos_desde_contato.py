"""
modulos/entrega/gerador_insumos_desde_contato.py

Converte fatos comerciais/operacionais (resultados_contato, pipeline_comercial)
em insumos estruturados de entrega (insumos_entrega.json).

Nao inventa insumos. Aplica apenas regras explicitas e conservadoras.
Nao usa LLM. Nao decide estrategia.

Fontes permitidas:
  dados/resultados_contato.json
  dados/pipeline_comercial.json
  dados/pipeline_entrega.json   (para resolver entrega_id por oportunidade_id)

Saidas:
  dados/insumos_entrega.json            (insumos novos appendados)
  dados/historico_geracao_insumos_entrega.json

Regras de mapeamento:
  respondeu_interesse
    -> contato_confirmado  (sempre)
    -> canal_confirmado    (se mencionar canal especifico: WhatsApp, Instagram, etc.)
    -> ativo_digital_confirmado (se mencionar site/ativo/Instagram/Google + linha mkt)
    -> contexto_adicional  (resumo como contexto)

  pediu_proposta
    -> contato_confirmado  (sempre)
    -> objetivo_confirmado (pediu proposta = confirmou objetivo do servico)
    -> escopo_confirmado   (so se detalhes traz escopo claro + linha mkt + contexto_origem)
    -> contexto_adicional  (resumo como contexto)

  pediu_retorno_futuro
    -> nada (em geral)
    -> contexto_adicional apenas se detalhes trouxer fato novo util (criterio: len(detalhes)>80
       e mencionar canal/objetivo/ativo especifico)

  sem_resposta / respondeu_sem_interesse / contato_invalido
    -> nenhum insumo

Deduplicacao:
  chave = "{oportunidade_id}|{tipo_insumo}|{chave_item}"
  nao gera se chave ja existir em insumos_entrega (qualquer status)
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_TIPOS_RELEVANTES  = {"respondeu_interesse", "pediu_proposta"}
_PALAVRAS_CANAL    = {"whatsapp", "instagram", "facebook", "telegram", "email", "youtube", "tiktok"}
_PALAVRAS_DIGITAL  = {"site", "website", "google", "instagram", "digital", "ativo", "pagina", "maps"}
_PALAVRAS_ESCOPO   = {"escopo", "whatsapp", "google", "maps", "instagram", "botao", "agendamento",
                      "presenca", "digital", "implantacao"}


# ─── Ponto de entrada (chamado pelo orquestrador) ─────────────────────────────

def executar() -> dict:
    resultados        = _carregar_json("resultados_contato.json",               padrao=[])
    insumos_exist     = _carregar_json("insumos_entrega.json",                  padrao=[])
    pipeline_comercial = _carregar_json("pipeline_comercial.json",              padrao=[])
    pipeline_entrega  = _carregar_json("pipeline_entrega.json",                 padrao=[])
    historico_geracao = _carregar_json("historico_geracao_insumos_entrega.json", padrao=[])

    opp_por_id     = {o["id"]: o for o in pipeline_comercial}
    entrega_por_opp = {e["oportunidade_id"]: e["id"] for e in pipeline_entrega}
    chaves_exist   = _calcular_chaves_existentes(insumos_exist)

    relevantes = carregar_resultados_relevantes(resultados)
    logger.info(f"[gerador_insumos] resultados relevantes: {len(relevantes)}")

    novos_insumos = []
    for resultado in relevantes:
        opp_id    = resultado.get("oportunidade_id", "")
        opp       = opp_por_id.get(opp_id, {})
        entrega_id = entrega_por_opp.get(opp_id, "")
        contexto  = montar_contexto_para_geracao(resultado, opp, entrega_id)
        candidatos = detectar_insumos_geraveis(resultado, contexto, chaves_exist)

        for cand in candidatos:
            chave_dedup = _chave_dedup(opp_id, cand["tipo_insumo"], cand["chave"])
            if chave_dedup in chaves_exist:
                continue
            chaves_exist.add(chave_dedup)
            insumo = criar_insumo_entrega(cand, resultado, opp_id, entrega_id)
            novos_insumos.append(insumo)
            registrar_historico_geracao_insumo(insumo, resultado, historico_geracao, cand["regra"])
            logger.info(
                f"  [gerador] {cand['tipo_insumo']} | {opp_id[:30]} | regra={cand['regra']}"
            )

    if novos_insumos:
        insumos_exist.extend(novos_insumos)
        _salvar_json("insumos_entrega.json",                  insumos_exist)
        _salvar_json("historico_geracao_insumos_entrega.json", historico_geracao)
        logger.info(f"[gerador_insumos] {len(novos_insumos)} insumos gerados e salvos")

    return {
        "agente":               "gerador_insumos_desde_contato",
        "resultados_analisados": len(relevantes),
        "insumos_gerados":      len(novos_insumos),
    }


# ─── Carregamento e filtragem ─────────────────────────────────────────────────

def carregar_resultados_relevantes(resultados: list) -> list:
    """
    Filtra resultados com tipo relevante para geracao de insumo.
    Inclui pediu_retorno_futuro apenas com contexto suficiente.
    """
    saida = []
    for r in resultados:
        tipo = r.get("tipo_resultado", "")
        if tipo in _TIPOS_RELEVANTES:
            saida.append(r)
        elif tipo == "pediu_retorno_futuro":
            det = r.get("detalhes", "")
            if len(det) > 80 and any(p in det.lower() for p in _PALAVRAS_DIGITAL | _PALAVRAS_CANAL):
                saida.append(r)
    return saida


def carregar_insumos_existentes() -> list:
    return _carregar_json("insumos_entrega.json", padrao=[])


# ─── Contexto ─────────────────────────────────────────────────────────────────

def montar_contexto_para_geracao(resultado: dict, opp: dict, entrega_id: str) -> dict:
    """Consolida campos relevantes para decidir quais insumos gerar."""
    resumo  = resultado.get("resumo_resultado", "").lower()
    detalhes = resultado.get("detalhes", "").lower()
    texto   = resumo + " " + detalhes

    return {
        "entrega_id":       entrega_id,
        "linha_servico":    opp.get("linha_servico_sugerida", ""),
        "estagio":          opp.get("estagio", ""),
        "contexto_origem":  opp.get("contexto_origem", ""),
        "tipo_resultado":   resultado.get("tipo_resultado", ""),
        "tem_canal":        any(p in texto for p in _PALAVRAS_CANAL),
        "tem_digital":      any(p in texto for p in _PALAVRAS_DIGITAL),
        "tem_escopo":       any(p in texto for p in _PALAVRAS_ESCOPO),
        "texto_completo":   texto,
        "texto_original":   resultado.get("resumo_resultado", ""),
    }


# ─── Detecção de insumos geráveis ─────────────────────────────────────────────

def detectar_insumos_geraveis(resultado: dict, ctx: dict, chaves_exist: set) -> list:
    """
    Aplica regras conservadoras para decidir quais insumos gerar.
    Retorna lista de dicts candidatos com tipo_insumo, chave, valor, descricao, regra.
    """
    tipo = ctx["tipo_resultado"]
    linha = ctx["linha_servico"]
    candidatos = []

    resumo_orig = resultado.get("resumo_resultado", "")
    detalhes    = resultado.get("detalhes", "")
    opp_id      = resultado.get("oportunidade_id", "")

    if tipo == "respondeu_interesse":
        # contato_confirmado — sempre
        candidatos.append(_cand(
            "contato_confirmado", "ck_contato_principal",
            f"{resultado.get('contraparte','?')} respondeu via {resultado.get('canal','?')}",
            resumo_orig, "respondeu_interesse:contato",
        ))
        # canal_confirmado — se mencionar canal especifico
        if ctx["tem_canal"]:
            candidatos.append(_cand(
                "canal_confirmado", "ck_canais_existentes",
                _extrair_canais(ctx["texto_completo"]),
                resumo_orig, "respondeu_interesse:canal",
            ))
        # ativo_digital_confirmado — se mencionar ativo + linha mkt
        if ctx["tem_digital"] and linha == "marketing_presenca_digital":
            candidatos.append(_cand(
                "ativo_digital_confirmado", "ck_ativo_digital",
                _extrair_ativo_digital(ctx["texto_completo"]),
                resumo_orig, "respondeu_interesse:ativo_digital_mkt",
            ))
        # contexto_adicional — sempre
        candidatos.append(_cand(
            "contexto_adicional", "ck_objetivo_prioritario",
            resumo_orig, detalhes[:200], "respondeu_interesse:contexto",
        ))

    elif tipo == "pediu_proposta":
        # contato_confirmado — sempre
        candidatos.append(_cand(
            "contato_confirmado", "ck_contato_principal",
            f"{resultado.get('contraparte','?')} pediu proposta via {resultado.get('canal','?')}",
            resumo_orig, "pediu_proposta:contato",
        ))
        # objetivo_confirmado — pedir proposta confirma objetivo do servico
        candidatos.append(_cand(
            "objetivo_confirmado", "ck_objetivo_prioritario",
            resumo_orig, detalhes[:200], "pediu_proposta:objetivo",
        ))
        # escopo_confirmado — conservador: precisa de escopo claro + contexto + linha mkt
        if (ctx["tem_escopo"] and linha == "marketing_presenca_digital"
                and ctx["contexto_origem"] and len(detalhes) > 60):
            candidatos.append(_cand(
                "escopo_confirmado", "ck_escopo_inicial",
                _extrair_escopo(ctx["texto_completo"]),
                detalhes[:200], "pediu_proposta:escopo_mkt",
            ))
        # contexto_adicional
        candidatos.append(_cand(
            "contexto_adicional", "ck_objetivo_prioritario",
            resumo_orig, detalhes[:200], "pediu_proposta:contexto",
        ))

    elif tipo == "pediu_retorno_futuro":
        # Apenas contexto_adicional quando ha fato util
        if ctx["tem_canal"] or ctx["tem_digital"]:
            candidatos.append(_cand(
                "contexto_adicional", "ck_objetivo_prioritario",
                resumo_orig, detalhes[:150], "pediu_retorno_futuro:contexto_util",
            ))

    # Deduplicar candidatos internos (mesmo tipo+chave na mesma chamada)
    return deduplicar_insumos_gerados(candidatos, chaves_exist, opp_id)


# ─── Criação e registro ───────────────────────────────────────────────────────

def criar_insumo_entrega(cand: dict, resultado: dict, opp_id: str, entrega_id: str) -> dict:
    """Monta o dict de insumo no formato de insumos_entrega.json."""
    agora = datetime.now().isoformat(timespec="seconds")
    return {
        "id":                f"ins_auto_{resultado.get('id','')}_{cand['tipo_insumo']}",
        "entrega_id":        entrega_id,
        "oportunidade_id":   opp_id,
        "tipo_insumo":       cand["tipo_insumo"],
        "chave":             cand["chave"],
        "valor":             cand["valor"],
        "descricao":         cand["descricao"],
        "origem":            "resultado_contato",
        "resultado_contato_id": resultado.get("id", ""),
        "data_insumo":       resultado.get("data_resultado", agora),
        "status_aplicacao":  "pendente",
        "aplicado_em":       None,
    }


def registrar_historico_geracao_insumo(
    insumo: dict, resultado: dict, historico: list, regra: str
) -> None:
    """Adiciona entrada no historico_geracao_insumos_entrega.json (in-place)."""
    historico.append({
        "id":                    f"hger_{len(historico)}_{insumo['id']}",
        "resultado_contato_id":  resultado.get("id", ""),
        "oportunidade_id":       insumo.get("oportunidade_id", ""),
        "insumo_id":             insumo["id"],
        "tipo_insumo_gerado":    insumo["tipo_insumo"],
        "regra_aplicada":        regra,
        "origem":                "resultado_contato",
        "registrado_em":         datetime.now().isoformat(timespec="seconds"),
    })


def deduplicar_insumos_gerados(candidatos: list, chaves_exist: set, opp_id: str) -> list:
    """Remove candidatos cujo tipo+chave ja existe no conjunto atual."""
    vistos: set = set()
    saida = []
    for c in candidatos:
        k = _chave_dedup(opp_id, c["tipo_insumo"], c["chave"])
        if k not in chaves_exist and k not in vistos:
            vistos.add(k)
            saida.append(c)
    return saida


# ─── Auxiliares ───────────────────────────────────────────────────────────────

def _cand(tipo_insumo, chave, valor, descricao, regra) -> dict:
    return {
        "tipo_insumo": tipo_insumo,
        "chave":       chave,
        "valor":       str(valor)[:200],
        "descricao":   str(descricao)[:200],
        "regra":       regra,
    }


def _chave_dedup(opp_id: str, tipo_insumo: str, chave: str) -> str:
    return f"{opp_id}|{tipo_insumo}|{chave}"


def _calcular_chaves_existentes(insumos: list) -> set:
    return {
        _chave_dedup(i.get("oportunidade_id", ""), i.get("tipo_insumo", ""), i.get("chave", ""))
        for i in insumos
    }


def _extrair_canais(texto: str) -> str:
    encontrados = [p for p in _PALAVRAS_CANAL if p in texto]
    return ", ".join(encontrados) if encontrados else "canal mencionado na conversa"


def _extrair_ativo_digital(texto: str) -> str:
    encontrados = [p for p in _PALAVRAS_DIGITAL if p in texto]
    return ", ".join(encontrados) if encontrados else "ativo digital identificado na conversa"


def _extrair_escopo(texto: str) -> str:
    encontrados = [p for p in _PALAVRAS_ESCOPO if p in texto]
    return "Escopo identificado: " + ", ".join(encontrados) if encontrados else "escopo mencionado"


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
