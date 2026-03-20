"""
core/executor.py — Orquestra o fluxo completo de prospecção.

Fluxo v0.2:
  busca → análise → priorização → diagnóstico → salvamento (3 arquivos) → resumo

Arquivos gerados:
  todas.json              → todas as empresas encontradas
  candidatas_brutas.json  → empresas com nome identificado (excluindo pouco_util)
  candidatas_priorizadas.json → semi_digital + analogica, ordenadas por prioridade
"""

import logging
from datetime import datetime

import config
from agents.prospeccao.buscador import buscar_empresas
from agents.prospeccao.analisador import analisar_empresas
from agents.prospeccao.priorizador import priorizar_empresas, ordenar_por_prioridade
from agents.prospeccao.diagnosticador import diagnosticar_empresas
from core.persistencia import salvar_resultados

logger = logging.getLogger(__name__)


def configurar_logs() -> str:
    """Configura logging para terminal e arquivo. Retorna caminho do log."""
    config.PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    arquivo_log = config.PASTA_LOGS / f"execucao_{timestamp}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(arquivo_log), encoding="utf-8"),
        ],
    )
    return str(arquivo_log)


def executar() -> None:
    """Executa o fluxo completo. Cada etapa é logada individualmente."""
    arquivo_log = configurar_logs()
    inicio = datetime.now()

    logger.info("=" * 60)
    logger.info("INICIANDO FLUXO DE PROSPECÇÃO v0.2")
    logger.info(f"Cidade: {config.CIDADE}")
    logger.info(f"Categorias: {', '.join(config.NOMES_CATEGORIAS.values())}")
    logger.info(f"Limite score presença para digital_basica: 65")
    logger.info(f"Limite score prontidão para semi_digital: 40")
    logger.info("=" * 60)

    # ETAPA 1: Busca
    logger.info("ETAPA 1/5 — Buscando empresas...")
    empresas = buscar_empresas()

    if not empresas:
        logger.warning("Nenhuma empresa encontrada. Encerrando.")
        print("\nNenhuma empresa encontrada. Verifique os logs para detalhes.")
        return

    logger.info(f"ETAPA 1 concluída: {len(empresas)} empresas encontradas.")

    # ETAPA 2: Análise (score_presenca_digital + detecção de Instagram)
    logger.info("ETAPA 2/5 — Analisando presença digital...")
    empresas = analisar_empresas(empresas)
    logger.info("ETAPA 2 concluída.")

    # ETAPA 3: Priorização (score_prontidao_ia + classificacao_comercial)
    logger.info("ETAPA 3/5 — Calculando prioridade comercial...")
    empresas = priorizar_empresas(empresas)
    logger.info("ETAPA 3 concluída.")

    # ETAPA 4: Diagnóstico (texto — usa classificacao do priorizador)
    logger.info("ETAPA 4/5 — Gerando diagnósticos...")
    empresas = diagnosticar_empresas(empresas)
    logger.info("ETAPA 4 concluída.")

    # ETAPA 5: Salvamento (3 arquivos)
    logger.info("ETAPA 5/5 — Salvando resultados...")

    # Separar por classificação
    candidatas_brutas = [
        e for e in empresas
        if e.get("classificacao_comercial") != "pouco_util"
    ]
    candidatas_priorizadas = ordenar_por_prioridade([
        e for e in empresas
        if e.get("classificacao_comercial") in ("semi_digital_prioritaria", "analogica")
    ])

    caminho_todas = salvar_resultados(empresas, sufixo="todas")
    caminho_brutas = salvar_resultados(candidatas_brutas, sufixo="candidatas_brutas")
    caminho_priorizadas = salvar_resultados(candidatas_priorizadas, sufixo="candidatas_priorizadas")

    # Contagem por classificação para o resumo
    contagens = _contar_por_classificacao(empresas)

    # Resumo nos logs
    duracao = int((datetime.now() - inicio).total_seconds())
    logger.info("=" * 60)
    logger.info("CONCLUÍDO")
    logger.info(f"  Total encontradas          : {len(empresas)}")
    logger.info(f"  semi_digital_prioritaria   : {contagens.get('semi_digital_prioritaria', 0)}")
    logger.info(f"  analogica                  : {contagens.get('analogica', 0)}")
    logger.info(f"  digital_basica             : {contagens.get('digital_basica', 0)}")
    logger.info(f"  pouco_util                 : {contagens.get('pouco_util', 0)}")
    logger.info(f"  Arquivo todas              : {caminho_todas}")
    logger.info(f"  Arquivo candidatas_brutas  : {caminho_brutas}")
    logger.info(f"  Arquivo candidatas_prior.  : {caminho_priorizadas}")
    logger.info(f"  Log da execução            : {arquivo_log}")
    logger.info(f"  Duração total              : {duracao}s")
    logger.info("=" * 60)

    # Resumo limpo no terminal
    print("\n" + "=" * 55)
    print("PROSPECÇÃO CONCLUÍDA")
    print("=" * 55)
    print(f"Total encontradas          : {len(empresas)}")
    print(f"semi_digital_prioritaria   : {contagens.get('semi_digital_prioritaria', 0)}")
    print(f"analogica                  : {contagens.get('analogica', 0)}")
    print(f"digital_basica             : {contagens.get('digital_basica', 0)}")
    print(f"pouco_util                 : {contagens.get('pouco_util', 0)}")
    print(f"Resultados salvos em       : dados/")
    print(f"Duração                    : {duracao}s")
    print("=" * 55)


def _contar_por_classificacao(empresas: list) -> dict:
    """Conta quantas empresas caíram em cada classificação."""
    contagens: dict = {}
    for e in empresas:
        cls = e.get("classificacao_comercial", "pouco_util")
        contagens[cls] = contagens.get(cls, 0) + 1
    return contagens
