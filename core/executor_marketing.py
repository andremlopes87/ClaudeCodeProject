"""
core/executor_marketing.py — Linha de marketing: análise de presença digital em escala.

Diferenças em relação ao executor operacional (executor.py):
  - Itera sobre múltiplas cidades e nichos configurados em config.py
  - Não executa: diagnóstico narrativo, abordagem, histórico
  - Produz arquivos de presença com contexto geográfico (cidade + nicho + estado)
  - Deduplicação global por osm_id ou nome+cidade+categoria

Arquivos gerados por execução (com timestamp):
  resultado_TIMESTAMP_presenca_marketing.json   — todas as empresas analisadas
  fila_oportunidades_marketing_TIMESTAMP.json   — oportunidade_alta + media, com contexto

Arquivos persistentes (sobrescritos a cada execução):
  fila_oportunidades_marketing.json             — latest da fila (referência rápida)
"""

import logging
import time
from datetime import datetime

import config
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
from core.persistencia import salvar_resultados, salvar_json_fixo

logger = logging.getLogger(__name__)

_NOME_FILA_MARKETING_FIXO = "fila_oportunidades_marketing.json"
_NOME_FILA_PROPOSTAS_FIXO = "fila_propostas_marketing.json"
_NOME_FILA_EXECUCAO_FIXO  = "fila_execucao_comercial.json"


def configurar_logs() -> str:
    """Configura logging para terminal e arquivo. Retorna caminho do log."""
    config.PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    arquivo_log = config.PASTA_LOGS / f"marketing_{timestamp}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(arquivo_log), encoding="utf-8"),
        ],
    )
    return str(arquivo_log)


def executar_marketing() -> None:
    """Executa a linha de marketing sobre todas as cidades e nichos configurados."""
    arquivo_log = configurar_logs()
    inicio = datetime.now()

    cidades = config.CIDADES_MARKETING
    nichos = config.NICHOS_MARKETING or list(config.CATEGORIAS.keys())
    limite = config.LIMITE_EMPRESAS_POR_CIDADE_NICHO

    logger.info("=" * 60)
    logger.info("INICIANDO LINHA DE MARKETING")
    logger.info(f"Cidades  : {', '.join(cidades)}")
    logger.info(f"Nichos   : {', '.join(nichos)}")
    logger.info(f"Limite   : {limite} empresas por cidade/nicho")
    logger.info("=" * 60)

    # Coleta global com deduplicação
    todas_empresas: list = []
    chaves_vistas: set = set()  # osm_id ou nome+cidade+categoria
    contagem_por_cidade: dict = {}

    # ETAPA 1: Busca por cidade e nicho
    for idx_cidade, cidade in enumerate(cidades):
        logger.info(f"[{idx_cidade + 1}/{len(cidades)}] Processando cidade: {cidade}")
        estado = config.ESTADO_POR_CIDADE.get(cidade, "")
        empresas_cidade: list = []

        for nicho in nichos:
            lista_tags = config.CATEGORIAS.get(nicho)
            if not lista_tags:
                logger.warning(f"Nicho '{nicho}' não encontrado em CATEGORIAS. Pulando.")
                continue

            nome_nicho = config.NOMES_CATEGORIAS.get(nicho, nicho)
            logger.info(f"  Nicho: {nome_nicho}")

            for tags_dict in lista_tags:
                for tag_chave, tag_valor in tags_dict.items():
                    resultados = buscar_por_tag(cidade, tag_chave, tag_valor)

                    for empresa_raw in resultados:
                        empresa = _padronizar(empresa_raw, nicho, nome_nicho, cidade, estado)

                        chave = _chave_dedup(empresa)
                        if chave in chaves_vistas:
                            continue
                        chaves_vistas.add(chave)

                        if len(empresas_cidade) < limite:
                            empresas_cidade.append(empresa)

        contagem_por_cidade[cidade] = len(empresas_cidade)
        logger.info(f"  {cidade}: {len(empresas_cidade)} empresas únicas coletadas.")
        todas_empresas.extend(empresas_cidade)

        if idx_cidade < len(cidades) - 1:
            logger.info(f"  Pausa de {config.PAUSA_ENTRE_CIDADES}s antes da próxima cidade...")
            time.sleep(config.PAUSA_ENTRE_CIDADES)

    logger.info(f"ETAPA 1 concluída: {len(todas_empresas)} empresas únicas no total.")

    if not todas_empresas:
        logger.warning("Nenhuma empresa encontrada. Encerrando.")
        print("\nNenhuma empresa encontrada. Verifique os logs.")
        return

    # ETAPA 2: Pipeline de análise (sem diagnóstico narrativo, abordagem ou histórico)
    logger.info("ETAPA 2 - Analisando dados OSM...")
    todas_empresas = analisar_empresas(todas_empresas)

    logger.info("ETAPA 3 - Calculando prioridade comercial...")
    todas_empresas = priorizar_empresas(todas_empresas)

    logger.info("ETAPA 4 - Calculando abordabilidade...")
    todas_empresas = calcular_abordabilidade(todas_empresas)

    logger.info("ETAPA 5 - Analisando presença web...")
    todas_empresas = analisar_presenca_web(todas_empresas)
    todas_empresas = diagnosticar_presenca(todas_empresas)

    logger.info("ETAPA 6 - Enriquecendo canais digitais...")
    todas_empresas = enriquecer_canais(todas_empresas)

    logger.info("ETAPA 7 - Consolidando presença comercial...")
    todas_empresas = consolidar_presenca(todas_empresas)

    logger.info("ETAPA 8 - Gerando plano de marketing e propostas...")
    todas_empresas = planejar_marketing(todas_empresas)

    logger.info("ETAPA 9 - Gerando plano comercial...")
    todas_empresas = planejar_comercial(todas_empresas)

    fila_marketing = gerar_fila_marketing(todas_empresas)
    fila_propostas = gerar_fila_propostas(todas_empresas)
    fila_execucao  = gerar_fila_execucao(todas_empresas)

    logger.info(
        f"Pipeline concluído: {len(todas_empresas)} analisadas, "
        f"{len(fila_marketing)} oportunidades, "
        f"{len(fila_propostas)} propostas, "
        f"{len(fila_execucao)} na fila de execução comercial."
    )

    # ETAPA 5: Salvamento
    logger.info("ETAPA 10 - Salvando resultados...")
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")

    caminho_resultado = salvar_resultados(
        todas_empresas,
        sufixo="presenca_marketing",
    )
    caminho_fila_ts = config.PASTA_DADOS / f"fila_oportunidades_marketing_{timestamp}.json"
    import json
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    with open(caminho_fila_ts, "w", encoding="utf-8") as f:
        json.dump(fila_marketing, f, ensure_ascii=False, indent=2)
    logger.info(f"Arquivo salvo: {caminho_fila_ts} ({len(fila_marketing)} registros)")

    caminho_fila_fixo = salvar_json_fixo(fila_marketing, _NOME_FILA_MARKETING_FIXO)

    caminho_plano_ts = config.PASTA_DADOS / f"fila_propostas_marketing_{timestamp}.json"
    with open(caminho_plano_ts, "w", encoding="utf-8") as f:
        json.dump(fila_propostas, f, ensure_ascii=False, indent=2)
    logger.info(f"Arquivo salvo: {caminho_plano_ts} ({len(fila_propostas)} registros)")

    caminho_candidatas_plano = salvar_resultados(todas_empresas, sufixo="candidatas_com_plano_comercial")
    caminho_fila_propostas_fixo = salvar_json_fixo(fila_propostas, _NOME_FILA_PROPOSTAS_FIXO)

    caminho_execucao_ts = config.PASTA_DADOS / f"fila_execucao_comercial_{timestamp}.json"
    with open(caminho_execucao_ts, "w", encoding="utf-8") as f:
        json.dump(fila_execucao, f, ensure_ascii=False, indent=2)
    logger.info(f"Arquivo salvo: {caminho_execucao_ts} ({len(fila_execucao)} registros)")

    caminho_execucao_fixo = salvar_json_fixo(fila_execucao, _NOME_FILA_EXECUCAO_FIXO)

    # Resumo final
    duracao = int((datetime.now() - inicio).total_seconds())
    contagem_cls = _contar_por_campo(todas_empresas, "classificacao_presenca_comercial")

    logger.info("=" * 60)
    logger.info("MARKETING CONCLUÍDO")
    logger.info(f"  Cidades processadas        : {len(cidades)}")
    for cidade, n in contagem_por_cidade.items():
        estado = config.ESTADO_POR_CIDADE.get(cidade, "")
        sufixo = f" ({estado})" if estado else ""
        logger.info(f"    {cidade}{sufixo}: {n} empresas")
    logger.info(f"  Total analisado            : {len(todas_empresas)}")
    logger.info(f"  oportunidade_alta_presenca : {contagem_cls.get('oportunidade_alta_presenca', 0)}")
    logger.info(f"  oportunidade_media_presenca: {contagem_cls.get('oportunidade_media_presenca', 0)}")
    logger.info(f"  oportunidade_baixa_presenca: {contagem_cls.get('oportunidade_baixa_presenca', 0)}")
    logger.info(f"  pouca_utilidade_presenca   : {contagem_cls.get('pouca_utilidade_presenca', 0)}")
    logger.info(f"  Fila de oportunidades      : {len(fila_marketing)}")
    logger.info(f"  Fila de propostas          : {len(fila_propostas)}")
    logger.info(f"  Fila de execução comercial : {len(fila_execucao)}")
    logger.info(f"  Resultado completo         : {caminho_resultado}")
    logger.info(f"  Candidatas com plano       : {caminho_candidatas_plano}")
    logger.info(f"  Fila oportunidades ts      : {caminho_fila_ts}")
    logger.info(f"  Fila oportunidades fixo    : {caminho_fila_fixo}")
    logger.info(f"  Fila propostas ts          : {caminho_plano_ts}")
    logger.info(f"  Fila propostas fixo        : {caminho_fila_propostas_fixo}")
    logger.info(f"  Fila execucao ts           : {caminho_execucao_ts}")
    logger.info(f"  Fila execucao fixo         : {caminho_execucao_fixo}")
    logger.info(f"  Log                        : {arquivo_log}")
    logger.info(f"  Duração total              : {duracao}s")
    logger.info("=" * 60)

    contagem_status = _contar_por_campo(todas_empresas, "status_comercial_sugerido")
    contagem_prio_c = _contar_por_campo(todas_empresas, "nivel_prioridade_comercial")

    print("\n" + "=" * 58)
    print("LINHA DE MARKETING CONCLUÍDA v0.11")
    print("=" * 58)
    print(f"Cidades processadas        : {len(cidades)}")
    for cidade, n in contagem_por_cidade.items():
        estado = config.ESTADO_POR_CIDADE.get(cidade, "")
        sufixo = f" ({estado})" if estado else ""
        print(f"  {cidade}{sufixo}: {n} empresas")
    print(f"Total analisado            : {len(todas_empresas)}")
    print(f"---")
    print(f"oportunidade_alta          : {contagem_cls.get('oportunidade_alta_presenca', 0)}")
    print(f"oportunidade_media         : {contagem_cls.get('oportunidade_media_presenca', 0)}")
    print(f"oportunidade_baixa         : {contagem_cls.get('oportunidade_baixa_presenca', 0)}")
    print(f"pouca_utilidade            : {contagem_cls.get('pouca_utilidade_presenca', 0)}")
    print(f"---")
    print(f"COMERCIAL:")
    for s in ("pronto_para_contato", "identificado", "aguardando_dados", "descartado"):
        n = contagem_status.get(s, 0)
        if n:
            print(f"  {s:<28}: {n}")
    for p in ("alta", "media", "baixa", "sem_dados"):
        n = contagem_prio_c.get(p, 0)
        if n:
            print(f"  prioridade_{p:<20}: {n}")
    print(f"---")
    print(f"Fila de oportunidades      : {len(fila_marketing)}")
    print(f"Fila de propostas          : {len(fila_propostas)}")
    print(f"Fila de execução comercial : {len(fila_execucao)}")
    _exibir_exemplos_fila(fila_execucao)
    print(f"---")
    print(f"Candidatas com plano       : {caminho_candidatas_plano}")
    print(f"Fila execução timestamped  : {caminho_execucao_ts}")
    print(f"Fila execução latest       : {caminho_execucao_fixo}")
    print(f"Duração                    : {duracao}s")
    print("=" * 58)


def _padronizar(empresa: dict, categoria_id: str, nome_categoria: str, cidade: str, estado: str) -> dict:
    """Padroniza empresa com campos de contexto geográfico incluídos."""
    return {
        "osm_id": empresa.get("osm_id"),
        "nome": empresa.get("nome") or "(sem nome registrado)",
        "categoria": nome_categoria,
        "categoria_id": categoria_id,
        "cidade": cidade,
        "estado": estado,
        "website": empresa.get("website"),
        "telefone": empresa.get("telefone"),
        "horario": empresa.get("horario"),
        "email": empresa.get("email"),
        "instagram": empresa.get("instagram"),
        "endereco": empresa.get("endereco"),
        "lat": empresa.get("lat"),
        "lon": empresa.get("lon"),
        "fonte_dados": empresa.get("fonte_dados", "OpenStreetMap/Overpass"),
    }


def _chave_dedup(empresa: dict) -> str:
    """
    Chave para deduplicação global.
    Usa osm_id quando disponível; caso contrário, nome+cidade+categoria.
    """
    osm_id = empresa.get("osm_id")
    if osm_id:
        return f"osm:{osm_id}"
    nome = (empresa.get("nome") or "").strip().lower()
    cidade = (empresa.get("cidade") or "").strip().lower()
    categoria = (empresa.get("categoria_id") or "").strip().lower()
    return f"ncc:{nome}|{cidade}|{categoria}"


def _contar_por_campo(empresas: list, campo: str) -> dict:
    contagens: dict = {}
    for e in empresas:
        v = e.get(campo, "")
        contagens[v] = contagens.get(v, 0) + 1
    return contagens


def _exibir_exemplos_fila(fila: list, n: int = 5) -> None:
    """Exibe os primeiros N exemplos reais da fila no terminal."""
    if not fila:
        print("  (fila vazia)")
        return
    print(f"\nExemplos da fila (top {min(n, len(fila))}):")
    for e in fila[:n]:
        nome = e.get("nome", "—")
        cidade = e.get("cidade", "—")
        estado = e.get("estado", "")
        nicho = e.get("categoria", "—")
        cls = e.get("classificacao_presenca_comercial", "—")
        score = e.get("score_presenca_consolidado", "—")
        loc = f"{cidade}/{estado}" if estado else cidade
        print(f"  {nome} | {loc} | {nicho} | {cls} | score:{score}")
