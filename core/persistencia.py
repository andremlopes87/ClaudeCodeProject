"""
core/persistencia.py — Único ponto de leitura e escrita de dados do sistema.

Nenhum outro módulo deve ler ou escrever arquivos JSON diretamente.
Se no futuro trocarmos JSON por banco de dados, só este arquivo muda.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _garantir_pasta(pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)


def salvar_resultados(resultados: list, sufixo: str = "", pasta: Path = None) -> Path:
    """
    Salva lista de resultados em arquivo JSON com timestamp.

    Parâmetros:
        resultados: lista de dicionários a salvar
        sufixo: texto adicional no nome do arquivo (ex: "candidatas")
        pasta: pasta de destino (usa config.PASTA_DADOS se None)

    Retorna:
        Path do arquivo criado
    """
    if pasta is None:
        import config
        pasta = config.PASTA_DADOS

    _garantir_pasta(pasta)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    nome = f"resultado_{timestamp}"
    if sufixo:
        nome += f"_{sufixo}"
    nome += ".json"

    caminho = pasta / nome

    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

    logger.info(f"Arquivo salvo: {caminho} ({len(resultados)} registros)")
    return caminho


def salvar_json_fixo(dados, nome_arquivo: str, pasta: Path = None) -> Path:
    """
    Salva dados em arquivo JSON com nome fixo (sem timestamp).

    Usado para arquivos persistentes que são sobrescritos a cada execução:
    prospeccao_historico.json, fila_revisao.json, prospeccao_resumo_execucao.json.

    Parâmetros:
        dados: dict ou list a salvar
        nome_arquivo: nome completo do arquivo (ex: "prospeccao_historico.json")
        pasta: pasta de destino (usa config.PASTA_DADOS se None)

    Retorna:
        Path do arquivo salvo
    """
    if pasta is None:
        import config
        pasta = config.PASTA_DADOS

    _garantir_pasta(pasta)
    caminho = pasta / nome_arquivo

    n = len(dados) if isinstance(dados, (list, dict)) else 1
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    logger.info(f"Arquivo fixo salvo: {caminho} ({n} registros)")
    return caminho


def carregar_json_fixo(nome_arquivo: str, pasta: Path = None, padrao=None):
    """
    Carrega arquivo JSON com nome fixo. Retorna `padrao` se o arquivo não existir.

    Parâmetros:
        nome_arquivo: nome completo do arquivo (ex: "prospeccao_historico.json")
        pasta: pasta de origem (usa config.PASTA_DADOS se None)
        padrao: valor retornado se o arquivo não existir (None por padrão)

    Retorna:
        Conteúdo do arquivo ou `padrao` se não encontrado
    """
    if pasta is None:
        import config
        pasta = config.PASTA_DADOS

    caminho = pasta / nome_arquivo
    if not caminho.exists():
        logger.info(f"Arquivo fixo não encontrado (primeira execução?): {caminho}")
        return padrao

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    n = len(dados) if isinstance(dados, (list, dict)) else 1
    logger.info(f"Arquivo fixo carregado: {caminho} ({n} registros)")
    return dados


def carregar_resultados(caminho) -> list:
    """
    Carrega resultados de um arquivo JSON.

    Parâmetros:
        caminho: string ou Path do arquivo

    Retorna:
        lista de dicionários

    Lança:
        FileNotFoundError se o arquivo não existir
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    logger.info(f"Arquivo carregado: {caminho} ({len(dados)} registros)")
    return dados
