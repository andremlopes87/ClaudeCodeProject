"""
core/executor.py — Orquestra o fluxo completo de prospecção.

Fluxo v0.3:
  busca → análise → priorização → abordabilidade → diagnóstico → salvamento

Arquivos gerados (lógica explícita):
┌─────────────────────────────┬───────────────────────────────────────────────────────┐
│ Arquivo                     │ O que contém                                          │
├─────────────────────────────┼───────────────────────────────────────────────────────┤
│ todas.json                  │ Todas as empresas encontradas, sem filtro              │
│ candidatas_brutas.json      │ Todas exceto pouco_util (nome identificado)            │
│ candidatas_priorizadas.json │ semi_digital + analogica, ordenadas por prioridade     │
│ candidatas_abordaveis.json  │ Não pouco_util + canal direto, ordenadas para uso agora│
└─────────────────────────────┴───────────────────────────────────────────────────────┘

candidatas_priorizadas exclui: pouco_util e digital_basica
candidatas_abordaveis exclui: pouco_util e empresas sem telefone/e-mail
"""

import logging
from datetime import datetime

import config
from agents.prospeccao.buscador import buscar_empresas
from agents.prospeccao.analisador import analisar_empresas
from agents.prospeccao.priorizador import priorizar_empresas, ordenar_por_prioridade
from agents.prospeccao.abordabilidade import calcular_abordabilidade
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
    logger.info("INICIANDO FLUXO DE PROSPECCAO v0.3")
    logger.info(f"Cidade: {config.CIDADE}")
    logger.info(f"Categorias: {', '.join(config.NOMES_CATEGORIAS.values())}")
    logger.info("=" * 60)

    # ETAPA 1: Busca
    logger.info("ETAPA 1/6 - Buscando empresas...")
    empresas = buscar_empresas()

    if not empresas:
        logger.warning("Nenhuma empresa encontrada. Encerrando.")
        print("\nNenhuma empresa encontrada. Verifique os logs para detalhes.")
        return

    logger.info(f"ETAPA 1 concluida: {len(empresas)} empresas encontradas.")

    # ETAPA 2: Analise (score_presenca_digital + deteccao de Instagram)
    logger.info("ETAPA 2/6 - Analisando presenca digital...")
    empresas = analisar_empresas(empresas)
    logger.info("ETAPA 2 concluida.")

    # ETAPA 3: Priorizacao (score_prontidao_ia + classificacao_comercial)
    logger.info("ETAPA 3/6 - Calculando prioridade comercial...")
    empresas = priorizar_empresas(empresas)
    logger.info("ETAPA 3 concluida.")

    # ETAPA 4: Abordabilidade (canais de contato, abordavel_agora)
    logger.info("ETAPA 4/6 - Calculando abordabilidade...")
    empresas = calcular_abordabilidade(empresas)
    logger.info("ETAPA 4 concluida.")

    # ETAPA 5: Diagnostico (texto - usa classificacao e abordabilidade)
    logger.info("ETAPA 5/6 - Gerando diagnosticos...")
    empresas = diagnosticar_empresas(empresas)
    logger.info("ETAPA 5 concluida.")

    # ETAPA 6: Salvamento — 4 arquivos com logica explicita
    logger.info("ETAPA 6/6 - Salvando resultados...")

    # todas.json: sem filtro
    todas = empresas

    # candidatas_brutas.json: exclui pouco_util (tem nome identificado)
    candidatas_brutas = [
        e for e in empresas
        if e.get("classificacao_comercial") != "pouco_util"
    ]

    # candidatas_priorizadas.json: semi_digital + analogica, ordenadas
    # exclui: pouco_util (sem identificacao util) e digital_basica (pouca oportunidade)
    candidatas_priorizadas = ordenar_por_prioridade([
        e for e in empresas
        if e.get("classificacao_comercial") in ("semi_digital_prioritaria", "analogica")
    ])

    # candidatas_abordaveis.json: nao pouco_util + canal direto de contato
    # exclui: pouco_util, digital_basica, e empresas sem telefone/email identificado
    candidatas_abordaveis = ordenar_por_prioridade([
        e for e in empresas
        if e.get("classificacao_comercial") != "pouco_util"
        and e.get("abordavel_agora") is True
    ])

    caminho_todas = salvar_resultados(todas, sufixo="todas")
    caminho_brutas = salvar_resultados(candidatas_brutas, sufixo="candidatas_brutas")
    caminho_priorizadas = salvar_resultados(candidatas_priorizadas, sufixo="candidatas_priorizadas")
    caminho_abordaveis = salvar_resultados(candidatas_abordaveis, sufixo="candidatas_abordaveis")

    # Contagens por classificacao
    contagens = _contar_por_classificacao(empresas)
    n_abordaveis = sum(1 for e in empresas if e.get("abordavel_agora"))

    # Log detalhado
    duracao = int((datetime.now() - inicio).total_seconds())
    logger.info("=" * 60)
    logger.info("CONCLUIDO")
    logger.info(f"  Total encontradas          : {len(empresas)}")
    logger.info(f"  pouco_util                 : {contagens.get('pouco_util', 0)}")
    logger.info(f"  analogica                  : {contagens.get('analogica', 0)}")
    logger.info(f"  semi_digital_prioritaria   : {contagens.get('semi_digital_prioritaria', 0)}")
    logger.info(f"  digital_basica             : {contagens.get('digital_basica', 0)}")
    logger.info(f"  ---")
    logger.info(f"  candidatas_brutas          : {len(candidatas_brutas)} (sem pouco_util)")
    logger.info(f"  candidatas_priorizadas     : {len(candidatas_priorizadas)} (semi_digital + analogica)")
    logger.info(f"  candidatas_abordaveis      : {len(candidatas_abordaveis)} (com canal direto de contato)")
    logger.info(f"  total abordaveis           : {n_abordaveis}")
    logger.info(f"  ---")
    logger.info(f"  todas.json                 : {caminho_todas}")
    logger.info(f"  candidatas_brutas          : {caminho_brutas}")
    logger.info(f"  candidatas_priorizadas     : {caminho_priorizadas}")
    logger.info(f"  candidatas_abordaveis      : {caminho_abordaveis}")
    logger.info(f"  log                        : {arquivo_log}")
    logger.info(f"  Duracao total              : {duracao}s")
    logger.info("=" * 60)

    # Resumo limpo no terminal
    print("\n" + "=" * 58)
    print("PROSPECCAO CONCLUIDA")
    print("=" * 58)
    print(f"Total encontradas          : {len(empresas)}")
    print(f"  pouco_util               : {contagens.get('pouco_util', 0)}")
    print(f"  analogica                : {contagens.get('analogica', 0)}")
    print(f"  semi_digital_prioritaria : {contagens.get('semi_digital_prioritaria', 0)}")
    print(f"  digital_basica           : {contagens.get('digital_basica', 0)}")
    print(f"---")
    print(f"candidatas_brutas          : {len(candidatas_brutas)}")
    print(f"candidatas_priorizadas     : {len(candidatas_priorizadas)}")
    print(f"candidatas_abordaveis      : {len(candidatas_abordaveis)}")
    print(f"---")
    print(f"Resultados salvos em       : dados/")
    print(f"Duracao                    : {duracao}s")
    print("=" * 58)


def _contar_por_classificacao(empresas: list) -> dict:
    contagens: dict = {}
    for e in empresas:
        cls = e.get("classificacao_comercial", "pouco_util")
        contagens[cls] = contagens.get(cls, 0) + 1
    return contagens
