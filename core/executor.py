"""
core/executor.py — Orquestra o fluxo completo de prospecção.

Responsabilidades:
- Configurar logs (console + arquivo)
- Chamar cada etapa do fluxo na ordem correta
- Registrar o resultado de cada etapa
- Salvar os resultados via persistencia.py
- Exibir resumo final no terminal

Fluxo: busca → análise → diagnóstico → filtro → salvamento → resumo
"""

import logging
from datetime import datetime

import config
from agents.prospeccao.buscador import buscar_empresas
from agents.prospeccao.analisador import analisar_empresas
from agents.prospeccao.diagnosticador import diagnosticar_empresas
from core.persistencia import salvar_resultados

logger = logging.getLogger(__name__)


def configurar_logs() -> str:
    """
    Configura logging para saída no terminal e em arquivo.
    Retorna o caminho do arquivo de log criado.
    """
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
    """
    Executa o fluxo completo de prospecção.
    Cada etapa registra seu progresso nos logs.
    Em caso de falha em uma etapa, o processo para com mensagem clara.
    """
    arquivo_log = configurar_logs()
    inicio = datetime.now()

    logger.info("=" * 60)
    logger.info("INICIANDO FLUXO DE PROSPECÇÃO")
    logger.info(f"Cidade: {config.CIDADE}")
    logger.info(f"Categorias: {', '.join(config.NOMES_CATEGORIAS.values())}")
    logger.info(f"Limite de score para candidata: {config.LIMITE_SCORE_CANDIDATA}")
    logger.info("=" * 60)

    # ETAPA 1: Busca
    logger.info("ETAPA 1/4 — Buscando empresas...")
    empresas = buscar_empresas()

    if not empresas:
        logger.warning(
            "Nenhuma empresa encontrada. Possíveis causas: "
            "sem conexão com internet, cidade não encontrada no OSM, "
            "ou categorias sem dados na região. Encerrando."
        )
        print("\nNenhuma empresa encontrada. Verifique os logs para detalhes.")
        return

    logger.info(f"ETAPA 1 concluída: {len(empresas)} empresas encontradas.")

    # ETAPA 2: Análise
    logger.info("ETAPA 2/4 — Analisando presença digital...")
    empresas = analisar_empresas(empresas)
    logger.info("ETAPA 2 concluída.")

    # ETAPA 3: Diagnóstico
    logger.info("ETAPA 3/4 — Gerando diagnósticos...")
    empresas = diagnosticar_empresas(empresas)
    logger.info("ETAPA 3 concluída.")

    # ETAPA 4: Filtro e salvamento
    logger.info("ETAPA 4/4 — Salvando resultados...")
    candidatas = [e for e in empresas if e.get("e_candidata")]

    caminho_todas = salvar_resultados(empresas, sufixo="todas")
    caminho_candidatas = salvar_resultados(candidatas, sufixo="candidatas")

    # Resumo final
    duracao = int((datetime.now() - inicio).total_seconds())
    logger.info("=" * 60)
    logger.info("CONCLUÍDO")
    logger.info(f"  Empresas encontradas : {len(empresas)}")
    logger.info(f"  Candidatas           : {len(candidatas)} (score < {config.LIMITE_SCORE_CANDIDATA})")
    logger.info(f"  Arquivo completo     : {caminho_todas}")
    logger.info(f"  Arquivo candidatas   : {caminho_candidatas}")
    logger.info(f"  Log da execução      : {arquivo_log}")
    logger.info(f"  Duração total        : {duracao}s")
    logger.info("=" * 60)

    # Resumo limpo no terminal
    print("\n" + "=" * 50)
    print("PROSPECÇÃO CONCLUÍDA")
    print("=" * 50)
    print(f"Empresas encontradas : {len(empresas)}")
    print(f"Candidatas           : {len(candidatas)}")
    print(f"Resultados salvos em : dados/")
    print(f"Duração              : {duracao}s")
    print("=" * 50)
