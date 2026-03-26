"""
core/orquestrador_multi_cidade.py — Orquestrador multi-cidade.

Expande prospecção e marketing para múltiplas cidades de forma autônoma.
Controla ritmo, priorização, deduplicação cross-cidade e consolidação.

Camada ACIMA de executor_marketing.py — consome os mesmos módulos de pipeline.
Não altera main.py nem executor_marketing.py (prospecção local continua intacta).

Arquivos gerenciados:
  dados/estado_multi_cidade.json    — estado por cidade (status, contadores, nichos)
  dados/consolidado_multi_cidade.json — rankings e estatísticas cross-cidade
"""

import json
import logging
import time
from datetime import datetime
from hashlib import md5
from pathlib import Path

import config
from core.llm_router import LLMRouter

# Pipeline — mesmos módulos usados em executor_marketing.py
from conectores.overpass import buscar_por_tag
from modulos.prospeccao_operacional.analisador import analisar_empresas
from modulos.prospeccao_operacional.priorizador import priorizar_empresas
from modulos.prospeccao_operacional.abordabilidade import calcular_abordabilidade
from modulos.presenca_digital.analisador_web import analisar_presenca_web
from modulos.presenca_digital.diagnosticador_presenca import diagnosticar_presenca
from modulos.presenca_digital.enriquecedor_canais import enriquecer_canais
from modulos.presenca_digital.consolidador_presenca import consolidar_presenca, gerar_fila_marketing
from modulos.presenca_digital.planejador_marketing import planejar_marketing, gerar_fila_propostas
from modulos.comercial.planejador_comercial import planejar_comercial, gerar_fila_execucao

log = logging.getLogger(__name__)

_ARQ_ESTADO      = config.PASTA_DADOS / "estado_multi_cidade.json"
_ARQ_CONSOLIDADO = config.PASTA_DADOS / "consolidado_multi_cidade.json"

_DEFAULTS_CFG = {
    "max_cidades_por_ciclo": 2,
    "pausa_entre_cidades_seg": 30,
    "max_nichos_por_cidade_por_ciclo": 3,
}

_NICHOS_TODOS = list(config.CATEGORIAS.keys())


# ─── Ponto de entrada ─────────────────────────────────────────────────────────

def executar(cidade_forcada: str = None) -> dict:
    """
    Executa um ciclo multi-cidade.

    Seleciona até max_cidades_por_ciclo cidades da fila, processa cada uma
    com a pipeline completa de prospecção + marketing, deduplica cross-cidade
    e consolida resultados.

    cidade_forcada: processa apenas esta cidade (ignora priorização).
    """
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    log.info("=" * 60)
    log.info(f"ORQUESTRADOR MULTI-CIDADE — {ts}")
    log.info("=" * 60)

    estado = _carregar_estado()
    cfg = {**_DEFAULTS_CFG, **estado.get("configuracao", {})}

    # Selecionar cidades do ciclo
    if cidade_forcada:
        if cidade_forcada not in estado["cidades"]:
            estado["cidades"][cidade_forcada] = _cidade_nova(cidade_forcada)
        cidades_ciclo = [cidade_forcada]
        log.info(f"Cidade forcada: {cidade_forcada}")
    else:
        cidades_ciclo = _selecionar_cidades(estado, cfg)

    if not cidades_ciclo:
        log.info("Nenhuma cidade disponivel para processar neste ciclo.")
        return {"cidades_processadas": [], "motivo": "fila_vazia"}

    log.info(f"Cidades do ciclo: {cidades_ciclo}")

    # Chaves globais para dedup cross-cidade (acumula entre cidades do ciclo)
    chaves_globais: set = _carregar_chaves_globais()
    resultados_ciclo: dict = {}
    rate_limitado = False

    for idx, cidade in enumerate(cidades_ciclo):
        if rate_limitado:
            log.warning("Rate limited — abortando cidades restantes do ciclo.")
            break

        info = estado["cidades"].setdefault(cidade, _cidade_nova(cidade))
        nichos = _selecionar_nichos(info, cfg["max_nichos_por_cidade_por_ciclo"])

        log.info(f"[{idx+1}/{len(cidades_ciclo)}] {cidade} — nichos: {nichos}")

        info["status"] = "em_andamento"
        _salvar_estado(estado)

        try:
            resultado = _executar_cidade(cidade, nichos, chaves_globais)

            if resultado.get("rate_limited"):
                rate_limitado = True
                info["status"] = "pendente"
                log.warning(f"  Rate limited ao processar {cidade} — retomando no proximo ciclo.")
            else:
                _atualizar_estado_cidade(info, resultado, nichos)
                resultados_ciclo[cidade] = resultado
                chaves_globais.update(resultado.get("chaves_novas", set()))
                log.info(
                    f"  {cidade}: {resultado['leads_encontrados']} leads, "
                    f"{resultado['oportunidades_geradas']} oportunidades"
                )

        except Exception as exc:
            log.error(f"  Erro ao processar {cidade}: {exc}")
            info["status"] = "erro"
            info["ultimo_erro"] = str(exc)[:200]

        _salvar_estado(estado)

        # Pausa entre cidades (exceto na ultima)
        if idx < len(cidades_ciclo) - 1 and not rate_limitado:
            log.info(f"  Pausa de {cfg['pausa_entre_cidades_seg']}s antes da proxima cidade...")
            time.sleep(cfg["pausa_entre_cidades_seg"])

    # Consolidar cross-cidade e salvar
    consolidado = _consolidar(estado, resultados_ciclo)
    _salvar_consolidado(consolidado)

    # LLM — recomendacao estrategica
    recomendacao = _analisar_llm(consolidado)
    if recomendacao:
        consolidado["recomendacao_llm"] = recomendacao
        consolidado["recomendacao_ts"] = datetime.now().isoformat(timespec="seconds")
        _salvar_consolidado(consolidado)

    estado["ultima_execucao_ciclo"] = datetime.now().isoformat(timespec="seconds")
    estado["total_ciclos"] = estado.get("total_ciclos", 0) + 1
    _salvar_estado(estado)

    resumo = {
        "cidades_processadas": list(resultados_ciclo.keys()),
        "leads_total_ciclo": sum(r["leads_encontrados"] for r in resultados_ciclo.values()),
        "oportunidades_total_ciclo": sum(r["oportunidades_geradas"] for r in resultados_ciclo.values()),
        "rate_limitado": rate_limitado,
        "timestamp": ts,
    }

    log.info("=" * 60)
    log.info(f"Ciclo concluido: {resumo}")
    log.info("=" * 60)

    return resumo


# ─── Selecao de cidades ───────────────────────────────────────────────────────

def _selecionar_cidades(estado: dict, cfg: dict) -> list:
    """
    Retorna lista de cidades priorizadas para o ciclo.

    Prioridade:
      1. Nunca processadas (ultima_execucao=None) — processa novas primeiro
      2. Mais antigas (ultima_execucao mais distante)
      3. Com mais leads (maior volume de oportunidade)

    Filtra status "em_andamento" (possivel crash anterior → trata como pendente).
    """
    max_por_ciclo = cfg.get("max_cidades_por_ciclo", 2)
    cidades = estado.get("cidades", {})

    candidatas = []
    for nome, info in cidades.items():
        status = info.get("status", "pendente")
        # Ignora apenas cidades explicitamente "concluida" sem nichos pendentes
        if status == "concluida" and not info.get("nichos_pendentes"):
            candidatas.append((nome, info, True))  # (nome, info, is_concluida)
        elif status not in ("em_andamento",):
            candidatas.append((nome, info, False))

    def _chave(item):
        nome, info, concluida = item
        ultima = info.get("ultima_execucao")
        # None → prioridade maxima (nunca processada)
        if not ultima:
            return (0, 0, 0)
        try:
            dt = datetime.fromisoformat(ultima)
            idade_dias = (datetime.now() - dt).days
        except Exception:
            idade_dias = 0
        leads = info.get("leads_encontrados", 0)
        # concluidas sem pendentes ficam por ultimo
        return (2 if concluida else 1, -idade_dias, -leads)

    candidatas.sort(key=_chave)
    return [nome for nome, _, _ in candidatas[:max_por_ciclo]]


def _selecionar_nichos(info: dict, max_nichos: int) -> list:
    """
    Seleciona nichos a processar para a cidade.

    Prioriza nichos_pendentes; se esgotados, recicla todos (novo ciclo completo).
    """
    pendentes = list(info.get("nichos_pendentes", _NICHOS_TODOS))
    if not pendentes:
        # Ciclo completo concluido — recicla todos os nichos
        pendentes = list(_NICHOS_TODOS)

    return pendentes[:max_nichos]


# ─── Execucao por cidade ──────────────────────────────────────────────────────

def _executar_cidade(cidade: str, nichos: list, chaves_globais: set) -> dict:
    """
    Executa a pipeline completa de prospecção + marketing para uma cidade.

    Reutiliza os mesmos modulos de executor_marketing.py com parametros explicitos.
    Retorna dict com resultados e metadados.

    rate_limited=True no retorno indica que o ciclo deve ser abortado.
    """
    estado_uf = config.ESTADO_POR_CIDADE.get(cidade, "")
    limite = config.LIMITE_EMPRESAS_POR_CIDADE_NICHO

    empresas_cidade: list = []
    chaves_novas: set = set()

    # ETAPA 1: Coleta OSM por nicho
    for nicho in nichos:
        lista_tags = config.CATEGORIAS.get(nicho)
        if not lista_tags:
            log.warning(f"    Nicho '{nicho}' nao encontrado em CATEGORIAS — pulando.")
            continue

        nome_nicho = config.NOMES_CATEGORIAS.get(nicho, nicho)
        log.info(f"    Nicho: {nome_nicho}")

        for tags_dict in lista_tags:
            for tag_chave, tag_valor in tags_dict.items():
                try:
                    resultados = buscar_por_tag(cidade, tag_chave, tag_valor)
                except Exception as exc:
                    msg = str(exc)
                    if "429" in msg or "rate" in msg.lower() or "too many" in msg.lower():
                        log.warning(f"    Rate limit detectado em {cidade}/{nicho}: {msg}")
                        return {"rate_limited": True}
                    log.error(f"    Erro em buscar_por_tag({cidade}, {tag_chave}={tag_valor}): {exc}")
                    continue

                for empresa_raw in resultados:
                    empresa = _padronizar(empresa_raw, nicho, nome_nicho, cidade, estado_uf)
                    chave = _chave_dedup(empresa)

                    # Dedup intra-ciclo (esta cidade) e cross-cidade
                    if chave in chaves_globais or chave in chaves_novas:
                        continue
                    chaves_novas.add(chave)

                    if len(empresas_cidade) < limite:
                        empresas_cidade.append(empresa)

    if not empresas_cidade:
        log.info(f"    Nenhuma empresa encontrada em {cidade}.")
        return {
            "leads_encontrados": 0,
            "oportunidades_geradas": 0,
            "chaves_novas": chaves_novas,
            "rate_limited": False,
        }

    log.info(f"    {cidade}: {len(empresas_cidade)} empresas coletadas — executando pipeline...")

    # ETAPA 2: Pipeline de analise (igual executor_marketing.py)
    empresas_cidade = analisar_empresas(empresas_cidade)
    empresas_cidade = priorizar_empresas(empresas_cidade)
    empresas_cidade = calcular_abordabilidade(empresas_cidade)
    empresas_cidade = analisar_presenca_web(empresas_cidade)
    empresas_cidade = diagnosticar_presenca(empresas_cidade)
    empresas_cidade = enriquecer_canais(empresas_cidade)
    empresas_cidade = consolidar_presenca(empresas_cidade)
    empresas_cidade = planejar_marketing(empresas_cidade)
    empresas_cidade = planejar_comercial(empresas_cidade)

    fila_mkt = gerar_fila_marketing(empresas_cidade)
    fila_prop = gerar_fila_propostas(empresas_cidade)
    fila_exec = gerar_fila_execucao(empresas_cidade)

    # Salvar arquivos por cidade
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    slug = _slug(cidade)
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)

    _salvar_json(f"multi_cidade_{slug}_empresas_{ts}.json", empresas_cidade)
    _salvar_json(f"multi_cidade_{slug}_fila_mkt.json", fila_mkt)
    _salvar_json(f"multi_cidade_{slug}_fila_prop.json", fila_prop)
    _salvar_json(f"multi_cidade_{slug}_fila_exec.json", fila_exec)

    return {
        "leads_encontrados": len(empresas_cidade),
        "oportunidades_geradas": len(fila_mkt),
        "fila_propostas": len(fila_prop),
        "fila_exec": len(fila_exec),
        "chaves_novas": chaves_novas,
        "nichos_processados": nichos,
        "rate_limited": False,
        "timestamp": ts,
    }


# ─── Deduplicacao e consolidacao ──────────────────────────────────────────────

def _carregar_chaves_globais() -> set:
    """
    Carrega chaves de dedup do consolidado_multi_cidade.json.
    Evita reprocessar empresas ja vistas em ciclos anteriores.
    """
    consolidado = _carregar_consolidado()
    return set(consolidado.get("chaves_dedup_globais", []))


def _atualizar_estado_cidade(info: dict, resultado: dict, nichos: list) -> None:
    """Atualiza estado de uma cidade apos execucao bem-sucedida (in-place)."""
    agora = datetime.now().isoformat(timespec="seconds")
    todos_nichos = set(_NICHOS_TODOS)

    processados_antes = set(info.get("nichos_processados", []))
    processados_agora = processados_antes | set(nichos)
    pendentes = list(todos_nichos - processados_agora)

    info["status"] = "concluida" if not pendentes else "pendente"
    info["ultima_execucao"] = agora
    info["execucoes_total"] = info.get("execucoes_total", 0) + 1
    info["leads_encontrados"] = info.get("leads_encontrados", 0) + resultado["leads_encontrados"]
    info["oportunidades_geradas"] = info.get("oportunidades_geradas", 0) + resultado["oportunidades_geradas"]
    info["nichos_processados"] = sorted(processados_agora)
    info["nichos_pendentes"] = sorted(pendentes)
    info.pop("ultimo_erro", None)


def _consolidar(estado: dict, resultados_ciclo: dict) -> dict:
    """
    Produz consolidado_multi_cidade.json com rankings e estatísticas cross-cidade.
    """
    consolidado_anterior = _carregar_consolidado()
    chaves_globais = set(consolidado_anterior.get("chaves_dedup_globais", []))

    # Adicionar chaves novas do ciclo
    for resultado in resultados_ciclo.values():
        chaves_globais.update(resultado.get("chaves_novas", set()))

    cidades = estado.get("cidades", {})

    # Rankings
    ranking_leads = sorted(
        [(nome, info.get("leads_encontrados", 0)) for nome, info in cidades.items()],
        key=lambda x: -x[1],
    )
    ranking_oportunidades = sorted(
        [(nome, info.get("oportunidades_geradas", 0)) for nome, info in cidades.items()],
        key=lambda x: -x[1],
    )

    # Redes detectadas cross-cidade (mesmo nome+telefone em cidades diferentes)
    redes = _detectar_redes(cidades)

    # Por nicho: quais nichos geraram mais oportunidades
    nichos_stats: dict = {}
    for resultado in resultados_ciclo.values():
        for nicho in resultado.get("nichos_processados", []):
            nichos_stats[nicho] = nichos_stats.get(nicho, 0) + 1

    return {
        "atualizado_em": datetime.now().isoformat(timespec="seconds"),
        "total_cidades": len(cidades),
        "total_leads": sum(info.get("leads_encontrados", 0) for info in cidades.values()),
        "total_oportunidades": sum(info.get("oportunidades_geradas", 0) for info in cidades.values()),
        "ranking_leads": ranking_leads[:10],
        "ranking_oportunidades": ranking_oportunidades[:10],
        "nichos_processados_ciclo": nichos_stats,
        "redes_detectadas": redes,
        "chaves_dedup_globais": sorted(chaves_globais),
        "resumo_cidades": {
            nome: {
                "status": info.get("status"),
                "ultima_execucao": info.get("ultima_execucao"),
                "leads_encontrados": info.get("leads_encontrados", 0),
                "oportunidades_geradas": info.get("oportunidades_geradas", 0),
                "execucoes_total": info.get("execucoes_total", 0),
                "nichos_pendentes": len(info.get("nichos_pendentes", [])),
            }
            for nome, info in cidades.items()
        },
    }


def _detectar_redes(cidades: dict) -> list:
    """
    Detecta possiveis redes/franquias: mesma empresa em multiplas cidades.

    Critério simplificado: nome normalizado idêntico em 2+ cidades distintas.
    Nao descarta — franqueados podem ser clientes individuais.
    """
    # Carrega arquivos de fila por cidade para comparar nomes
    nomes_por_cidade: dict = {}
    for nome_cidade in cidades:
        slug = _slug(nome_cidade)
        arq = config.PASTA_DADOS / f"multi_cidade_{slug}_fila_mkt.json"
        if arq.exists():
            try:
                with open(arq, encoding="utf-8") as f:
                    fila = json.load(f)
                nomes_por_cidade[nome_cidade] = {
                    _normalizar_nome(e.get("nome", "")) for e in fila if e.get("nome")
                }
            except Exception:
                pass

    # Encontrar nomes presentes em 2+ cidades
    contagem_nome: dict = {}
    for nome_cidade, nomes in nomes_por_cidade.items():
        for nome in nomes:
            if nome not in contagem_nome:
                contagem_nome[nome] = []
            contagem_nome[nome].append(nome_cidade)

    redes = []
    for nome, cidades_lista in contagem_nome.items():
        if len(cidades_lista) >= 2:
            redes.append({
                "nome_normalizado": nome,
                "cidades": sorted(cidades_lista),
                "tipo": "rede_detectada",
                "observacao": "Franqueados podem ser clientes individuais — nao descartar",
            })

    return redes[:50]  # limite para nao inchar o arquivo


def _analisar_llm(consolidado: dict) -> str:
    """
    LLM: qual cidade tem melhor oportunidade? Qual nicho priorizar?
    Fallback: retorna string vazia (dry-run padrao).
    """
    try:
        router = LLMRouter()
        ctx = {
            "total_cidades": consolidado.get("total_cidades", 0),
            "total_leads": consolidado.get("total_leads", 0),
            "top_5_oportunidades": consolidado.get("ranking_oportunidades", [])[:5],
            "nichos_processados": consolidado.get("nichos_processados_ciclo", {}),
            "instrucao": (
                "Analisar resultados multi-cidade. "
                "Recomendar: qual cidade priorizar no proximo ciclo e qual nicho tem mais potencial. "
                "Resposta objetiva em 3 linhas."
            ),
        }
        res = router.analisar(ctx)
        if res.get("sucesso") and not res.get("fallback_usado"):
            return res["resultado"]
    except Exception as exc:
        log.warning(f"[llm] analisar_multi_cidade: {exc}")
    return ""


# ─── Estado ───────────────────────────────────────────────────────────────────

def _carregar_estado() -> dict:
    if _ARQ_ESTADO.exists():
        try:
            with open(_ARQ_ESTADO, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return _estado_inicial()


def _salvar_estado(estado: dict) -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    with open(_ARQ_ESTADO, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def _carregar_consolidado() -> dict:
    if _ARQ_CONSOLIDADO.exists():
        try:
            with open(_ARQ_CONSOLIDADO, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _salvar_consolidado(dados: dict) -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    with open(_ARQ_CONSOLIDADO, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def _estado_inicial() -> dict:
    """Estado padrao com as cidades de CIDADES_MARKETING mais candidatas do ESTADO_POR_CIDADE."""
    todas = list(config.CIDADES_MARKETING)
    # Adicionar cidades do ESTADO_POR_CIDADE que nao estejam em CIDADES_MARKETING
    for c in config.ESTADO_POR_CIDADE:
        if c not in todas:
            todas.append(c)

    cidades = {}
    for cidade in todas:
        cidades[cidade] = _cidade_nova(cidade)

    return {
        "cidades": cidades,
        "configuracao": dict(_DEFAULTS_CFG),
        "ultima_execucao_ciclo": None,
        "total_ciclos": 0,
    }


def _cidade_nova(cidade: str) -> dict:
    return {
        "estado": config.ESTADO_POR_CIDADE.get(cidade, ""),
        "status": "pendente",
        "ultima_execucao": None,
        "execucoes_total": 0,
        "leads_encontrados": 0,
        "oportunidades_geradas": 0,
        "nichos_processados": [],
        "nichos_pendentes": list(_NICHOS_TODOS),
    }


# ─── Funcoes de exibicao (para main_multi_cidade.py) ─────────────────────────

def obter_status() -> dict:
    """Retorna estado atual de todas as cidades."""
    return _carregar_estado()


def obter_ranking() -> list:
    """Retorna ranking de cidades por oportunidades geradas."""
    consolidado = _carregar_consolidado()
    return consolidado.get("ranking_oportunidades", [])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _padronizar(empresa: dict, categoria_id: str, nome_categoria: str, cidade: str, estado: str) -> dict:
    """Mesmo formato de executor_marketing._padronizar."""
    return {
        "osm_id":       empresa.get("osm_id"),
        "nome":         empresa.get("nome") or "(sem nome registrado)",
        "categoria":    nome_categoria,
        "categoria_id": categoria_id,
        "cidade":       cidade,
        "estado":       estado,
        "website":      empresa.get("website"),
        "telefone":     empresa.get("telefone"),
        "horario":      empresa.get("horario"),
        "email":        empresa.get("email"),
        "instagram":    empresa.get("instagram"),
        "endereco":     empresa.get("endereco"),
        "lat":          empresa.get("lat"),
        "lon":          empresa.get("lon"),
        "fonte_dados":  empresa.get("fonte_dados", "OpenStreetMap/Overpass"),
    }


def _chave_dedup(empresa: dict) -> str:
    osm_id = empresa.get("osm_id")
    if osm_id:
        return f"osm:{osm_id}"
    nome     = (empresa.get("nome") or "").strip().lower()
    cidade   = (empresa.get("cidade") or "").strip().lower()
    categoria = (empresa.get("categoria_id") or "").strip().lower()
    return f"ncc:{nome}|{cidade}|{categoria}"


def _normalizar_nome(nome: str) -> str:
    """Normaliza nome para comparacao cross-cidade (lowercase, sem acentos)."""
    import unicodedata
    s = unicodedata.normalize("NFD", nome.lower().strip())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _slug(cidade: str) -> str:
    """Converte nome de cidade para slug de arquivo seguro."""
    import unicodedata
    s = unicodedata.normalize("NFD", cidade.lower().strip())
    s = "".join(c if c.isalnum() else "_" for c in s if unicodedata.category(c) != "Mn")
    return s.strip("_")


def _salvar_json(nome: str, dados) -> None:
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    with open(config.PASTA_DADOS / nome, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
