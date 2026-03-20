"""
core/executor.py — Orquestra o fluxo completo de prospecção.

Fluxo v0.5:
  busca → análise → priorização → abordabilidade → diagnóstico → abordagem → histórico → salvamento

Arquivos por execução (com timestamp):
┌──────────────────────────────────┬──────────────────────────────────────────────────────────┐
│ Arquivo                          │ O que contém                                             │
├──────────────────────────────────┼──────────────────────────────────────────────────────────┤
│ todas.json                       │ Todas as empresas encontradas, sem filtro                 │
│ candidatas_brutas.json           │ Todas exceto pouco_util (nome identificado)               │
│ candidatas_priorizadas.json      │ semi_digital + analogica, ordenadas por prioridade        │
│ candidatas_abordaveis.json       │ Não pouco_util + canal direto, ordenadas para uso agora  │
│ candidatas_com_abordagem.json    │ Abordáveis + pacote de mensagens e orientações prontos    │
└──────────────────────────────────┴──────────────────────────────────────────────────────────┘

Arquivos persistentes (nome fixo, sobrescritos a cada execução):
┌──────────────────────────────────┬──────────────────────────────────────────────────────────┐
│ prospeccao_historico.json        │ Memória acumulada de todas as execuções                   │
│ fila_revisao.json                │ Leads prioritários para revisão: novos, mudanças, prontos │
│ prospeccao_resumo_execucao.json  │ Estatísticas e mudanças detectadas nesta execução         │
└──────────────────────────────────┴──────────────────────────────────────────────────────────┘

candidatas_priorizadas exclui: pouco_util e digital_basica
candidatas_abordaveis exclui: pouco_util e empresas sem telefone/e-mail
candidatas_com_abordagem: subset de abordaveis com pacote de abordagem gerado
"""

import logging
from datetime import datetime

import config
from modulos.prospeccao_operacional.buscador import buscar_empresas
from modulos.prospeccao_operacional.analisador import analisar_empresas
from modulos.prospeccao_operacional.priorizador import priorizar_empresas, ordenar_por_prioridade
from modulos.prospeccao_operacional.abordabilidade import calcular_abordabilidade
from modulos.prospeccao_operacional.diagnosticador import diagnosticar_empresas
from modulos.prospeccao_operacional.abordagem import preparar_abordagens
from modulos.prospeccao_operacional.historico import (
    atualizar_historico,
    gerar_fila_revisao,
    gerar_resumo_execucao,
)
from core.persistencia import salvar_resultados, salvar_json_fixo, carregar_json_fixo

logger = logging.getLogger(__name__)

_NOME_HISTORICO = "prospeccao_historico.json"
_NOME_FILA = "fila_revisao.json"
_NOME_RESUMO = "prospeccao_resumo_execucao.json"


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
    timestamp_execucao = inicio.isoformat()

    logger.info("=" * 60)
    logger.info("INICIANDO FLUXO DE PROSPECCAO v0.5")
    logger.info(f"Cidade: {config.CIDADE}")
    logger.info(f"Categorias: {', '.join(config.NOMES_CATEGORIAS.values())}")
    logger.info("=" * 60)

    # ETAPA 1: Busca
    logger.info("ETAPA 1/8 - Buscando empresas...")
    empresas = buscar_empresas()

    if not empresas:
        logger.warning("Nenhuma empresa encontrada. Encerrando.")
        print("\nNenhuma empresa encontrada. Verifique os logs para detalhes.")
        return

    logger.info(f"ETAPA 1 concluida: {len(empresas)} empresas encontradas.")

    # ETAPA 2: Analise (score_presenca_digital + deteccao de Instagram)
    logger.info("ETAPA 2/8 - Analisando presenca digital...")
    empresas = analisar_empresas(empresas)
    logger.info("ETAPA 2 concluida.")

    # ETAPA 3: Priorizacao (score_prontidao_ia + classificacao_comercial)
    logger.info("ETAPA 3/8 - Calculando prioridade comercial...")
    empresas = priorizar_empresas(empresas)
    logger.info("ETAPA 3 concluida.")

    # ETAPA 4: Abordabilidade (canais de contato, abordavel_agora)
    logger.info("ETAPA 4/8 - Calculando abordabilidade...")
    empresas = calcular_abordabilidade(empresas)
    logger.info("ETAPA 4 concluida.")

    # ETAPA 5: Diagnostico (texto - usa classificacao e abordabilidade)
    logger.info("ETAPA 5/8 - Gerando diagnosticos...")
    empresas = diagnosticar_empresas(empresas)
    logger.info("ETAPA 5 concluida.")

    # ETAPA 6: Abordagem — pacote de mensagens para empresas abordáveis
    logger.info("ETAPA 6/8 - Gerando pacotes de abordagem...")
    candidatas_abordaveis_pre = ordenar_por_prioridade([
        e for e in empresas
        if e.get("classificacao_comercial") != "pouco_util"
        and e.get("abordavel_agora") is True
    ])
    candidatas_com_abordagem = preparar_abordagens(candidatas_abordaveis_pre)
    logger.info(f"ETAPA 6 concluida: {len(candidatas_com_abordagem)} pacotes de abordagem gerados.")

    # ETAPA 7: Histórico — atualiza memória persistente e detecta mudanças
    logger.info("ETAPA 7/8 - Atualizando historico de prospeccao...")

    historico_anterior_lista = carregar_json_fixo(_NOME_HISTORICO, padrao=[])
    historico_anterior = {e["empresa_id"]: e for e in historico_anterior_lista if "empresa_id" in e}

    historico_atual, mudancas, stats = atualizar_historico(
        historico_anterior,
        empresas,
        timestamp_execucao,
        cidade=config.CIDADE,
    )

    fila_revisao = gerar_fila_revisao(historico_atual)
    resumo_execucao = gerar_resumo_execucao(
        historico_anterior, historico_atual, mudancas, stats, timestamp_execucao
    )

    logger.info(
        f"ETAPA 7 concluida: {len(historico_atual)} no historico, "
        f"{len(mudancas)} mudancas detectadas, "
        f"{len(fila_revisao)} na fila de revisao."
    )

    # ETAPA 8: Salvamento — arquivos com timestamp + arquivos fixos
    logger.info("ETAPA 8/8 - Salvando resultados...")

    # Arquivos com timestamp (por execução)
    todas = empresas
    candidatas_brutas = [
        e for e in empresas
        if e.get("classificacao_comercial") != "pouco_util"
    ]
    candidatas_priorizadas = ordenar_por_prioridade([
        e for e in empresas
        if e.get("classificacao_comercial") in ("semi_digital_prioritaria", "analogica")
    ])
    candidatas_abordaveis = candidatas_abordaveis_pre

    caminho_todas = salvar_resultados(todas, sufixo="todas")
    caminho_brutas = salvar_resultados(candidatas_brutas, sufixo="candidatas_brutas")
    caminho_priorizadas = salvar_resultados(candidatas_priorizadas, sufixo="candidatas_priorizadas")
    caminho_abordaveis = salvar_resultados(candidatas_abordaveis, sufixo="candidatas_abordaveis")
    caminho_com_abordagem = salvar_resultados(candidatas_com_abordagem, sufixo="candidatas_com_abordagem")

    # Arquivos fixos (persistentes — sobrescritos a cada execução)
    historico_lista = list(historico_atual.values())
    caminho_historico = salvar_json_fixo(historico_lista, _NOME_HISTORICO)
    caminho_fila = salvar_json_fixo(fila_revisao, _NOME_FILA)
    caminho_resumo = salvar_json_fixo(resumo_execucao, _NOME_RESUMO)

    # Contagens por classificação e status
    contagens = _contar_por_classificacao(empresas)
    n_abordaveis = sum(1 for e in empresas if e.get("abordavel_agora"))
    contagem_status = resumo_execucao.get("contagem_por_status_interno", {})

    # Log detalhado
    duracao = int((datetime.now() - inicio).total_seconds())
    logger.info("=" * 60)
    logger.info("CONCLUIDO v0.5")
    logger.info(f"  Total encontradas          : {len(empresas)}")
    logger.info(f"  pouco_util                 : {contagens.get('pouco_util', 0)}")
    logger.info(f"  analogica                  : {contagens.get('analogica', 0)}")
    logger.info(f"  semi_digital_prioritaria   : {contagens.get('semi_digital_prioritaria', 0)}")
    logger.info(f"  digital_basica             : {contagens.get('digital_basica', 0)}")
    logger.info(f"  ---")
    logger.info(f"  candidatas_brutas          : {len(candidatas_brutas)}")
    logger.info(f"  candidatas_priorizadas     : {len(candidatas_priorizadas)}")
    logger.info(f"  candidatas_abordaveis      : {len(candidatas_abordaveis)}")
    logger.info(f"  candidatas_com_abordagem   : {len(candidatas_com_abordagem)}")
    logger.info(f"  ---")
    logger.info(f"  HISTORICO ({len(historico_atual)} total):")
    for s, n in sorted(contagem_status.items()):
        logger.info(f"    {s:<28}: {n}")
    logger.info(f"  mudancas detectadas        : {len(mudancas)}")
    logger.info(f"  fila_revisao               : {len(fila_revisao)}")
    logger.info(f"  ---")
    logger.info(f"  todas.json                 : {caminho_todas}")
    logger.info(f"  candidatas_brutas          : {caminho_brutas}")
    logger.info(f"  candidatas_priorizadas     : {caminho_priorizadas}")
    logger.info(f"  candidatas_abordaveis      : {caminho_abordaveis}")
    logger.info(f"  candidatas_com_abordagem   : {caminho_com_abordagem}")
    logger.info(f"  prospeccao_historico       : {caminho_historico}")
    logger.info(f"  fila_revisao               : {caminho_fila}")
    logger.info(f"  resumo_execucao            : {caminho_resumo}")
    logger.info(f"  log                        : {arquivo_log}")
    logger.info(f"  Duracao total              : {duracao}s")
    logger.info("=" * 60)

    # Resumo limpo no terminal
    print("\n" + "=" * 58)
    print("PROSPECCAO CONCLUIDA v0.5")
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
    print(f"candidatas_com_abordagem   : {len(candidatas_com_abordagem)}")
    print(f"---")
    print(f"HISTORICO ({len(historico_atual)} empresas no total):")
    for s in ("novo", "pronto_para_abordagem", "revisar", "baixa_prioridade", "descartar"):
        n = contagem_status.get(s, 0)
        if n:
            print(f"  {s:<28}: {n}")
    print(f"Mudancas detectadas        : {len(mudancas)}")
    print(f"Fila de revisao            : {len(fila_revisao)} leads")
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
