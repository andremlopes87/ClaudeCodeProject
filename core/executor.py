"""
core/executor.py — Orquestra o fluxo completo de prospecção.

Fluxo v0.8:
  busca → análise OSM → priorização → abordabilidade → diagnóstico →
  abordagem → histórico → presença digital + canais + consolidação → salvamento

Arquivos por execução (com timestamp):
┌──────────────────────────────────────┬────────────────────────────────────────────────────────┐
│ Arquivo                              │ O que contém                                           │
├──────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ todas.json                           │ Todas as empresas encontradas, sem filtro               │
│ candidatas_brutas.json               │ Todas exceto pouco_util (nome identificado)             │
│ candidatas_priorizadas.json          │ semi_digital + analogica, ordenadas por prioridade      │
│ candidatas_abordaveis.json           │ Não pouco_util + canal direto, ordenadas para uso agora │
│ candidatas_com_abordagem.json        │ Abordáveis + pacote de mensagens e orientações prontos  │
│ candidatas_com_diagnostico_web.json  │ Empresas com website + análise de presença digital      │
└──────────────────────────────────────┴────────────────────────────────────────────────────────┘

Arquivos persistentes (nome fixo, sobrescritos a cada execução):
┌──────────────────────────────────────┬──────────────────────────────────────────────────────────┐
│ prospeccao_historico.json            │ Memória acumulada de todas as execuções                   │
│ fila_revisao.json                    │ Leads prioritários para revisão: novos, mudanças, prontos │
│ prospeccao_resumo_execucao.json      │ Estatísticas e mudanças detectadas nesta execução         │
│ fila_oportunidades_presenca.json     │ Empresas com maior oportunidade de melhoria digital       │
│ candidatas_com_canais_digitais.json  │ Empresas com ao menos um canal digital identificado       │
│ fila_oportunidades_marketing.json    │ Oportunidades alta/media de presença, ordenadas           │
└──────────────────────────────────────┴──────────────────────────────────────────────────────────┘

candidatas_priorizadas exclui: pouco_util e digital_basica
candidatas_abordaveis exclui: pouco_util e empresas sem telefone/e-mail
candidatas_com_abordagem: subset de abordaveis com pacote de abordagem gerado
candidatas_com_diagnostico_web: empresas com website, com análise de presença web
candidatas_com_canais_digitais: empresas com ao menos um canal digital confirmado (qualquer confiança)
candidatas_com_presenca_consolidada: todas as empresas com presença digital consolidada (timestamped)
fila_oportunidades_marketing: oportunidades alta/media de presença para ação comercial
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
from modulos.presenca_digital.analisador_web import analisar_presenca_web
from modulos.presenca_digital.diagnosticador_presenca import diagnosticar_presenca
from modulos.presenca_digital.enriquecedor_canais import enriquecer_canais, tem_canal_identificado
from modulos.presenca_digital.consolidador_presenca import consolidar_presenca, gerar_fila_marketing
from core.persistencia import salvar_resultados, salvar_json_fixo, carregar_json_fixo

logger = logging.getLogger(__name__)

_NOME_HISTORICO = "prospeccao_historico.json"
_NOME_FILA = "fila_revisao.json"
_NOME_RESUMO = "prospeccao_resumo_execucao.json"
_NOME_FILA_PRESENCA = "fila_oportunidades_presenca.json"
_NOME_CANAIS_DIGITAIS = "candidatas_com_canais_digitais.json"
_NOME_FILA_MARKETING = "fila_oportunidades_marketing.json"


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
    logger.info("INICIANDO FLUXO DE PROSPECCAO v0.8")
    logger.info(f"Cidade: {config.CIDADE}")
    logger.info(f"Categorias: {', '.join(config.NOMES_CATEGORIAS.values())}")
    logger.info("=" * 60)

    # ETAPA 1: Busca
    logger.info("ETAPA 1/9 - Buscando empresas...")
    empresas = buscar_empresas()

    if not empresas:
        logger.warning("Nenhuma empresa encontrada. Encerrando.")
        print("\nNenhuma empresa encontrada. Verifique os logs para detalhes.")
        return

    logger.info(f"ETAPA 1 concluida: {len(empresas)} empresas encontradas.")

    # ETAPA 2: Analise OSM (score_presenca_digital + deteccao de Instagram)
    logger.info("ETAPA 2/9 - Analisando presenca digital (dados OSM)...")
    empresas = analisar_empresas(empresas)
    logger.info("ETAPA 2 concluida.")

    # ETAPA 3: Priorizacao (score_prontidao_ia + classificacao_comercial)
    logger.info("ETAPA 3/9 - Calculando prioridade comercial...")
    empresas = priorizar_empresas(empresas)
    logger.info("ETAPA 3 concluida.")

    # ETAPA 4: Abordabilidade (canais de contato, abordavel_agora)
    logger.info("ETAPA 4/9 - Calculando abordabilidade...")
    empresas = calcular_abordabilidade(empresas)
    logger.info("ETAPA 4 concluida.")

    # ETAPA 5: Diagnostico (texto - usa classificacao e abordabilidade)
    logger.info("ETAPA 5/9 - Gerando diagnosticos...")
    empresas = diagnosticar_empresas(empresas)
    logger.info("ETAPA 5 concluida.")

    # ETAPA 6: Abordagem — pacote de mensagens para empresas abordáveis
    logger.info("ETAPA 6/9 - Gerando pacotes de abordagem...")
    candidatas_abordaveis_pre = ordenar_por_prioridade([
        e for e in empresas
        if e.get("classificacao_comercial") != "pouco_util"
        and e.get("abordavel_agora") is True
    ])
    candidatas_com_abordagem = preparar_abordagens(candidatas_abordaveis_pre)
    logger.info(f"ETAPA 6 concluida: {len(candidatas_com_abordagem)} pacotes de abordagem gerados.")

    # ETAPA 7: Histórico — atualiza memória persistente e detecta mudanças
    logger.info("ETAPA 7/9 - Atualizando historico de prospeccao...")

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

    # ETAPA 8: Presença digital — análise web + canais + consolidação comercial
    logger.info("ETAPA 8/9 - Analisando presenca digital, enriquecendo canais e consolidando...")
    empresas = analisar_presenca_web(empresas)
    empresas = diagnosticar_presenca(empresas)
    empresas = enriquecer_canais(empresas)
    empresas = consolidar_presenca(empresas)

    candidatas_com_diagnostico_web = [
        e for e in empresas
        if e.get("tem_site") is True
    ]
    fila_oportunidades_presenca = _gerar_fila_presenca(candidatas_com_diagnostico_web)
    candidatas_com_canais_digitais = [e for e in empresas if tem_canal_identificado(e)]
    fila_oportunidades_marketing = gerar_fila_marketing(empresas)

    n_acessiveis = sum(1 for e in candidatas_com_diagnostico_web if e.get("site_acessivel"))
    contagem_cls_presenca = _contar_por_classificacao_presenca(empresas)
    logger.info(
        f"ETAPA 8 concluida: {len(candidatas_com_diagnostico_web)} com site, "
        f"{n_acessiveis} acessiveis, "
        f"{len(candidatas_com_canais_digitais)} com canais, "
        f"{len(fila_oportunidades_marketing)} na fila de marketing."
    )

    # ETAPA 9: Salvamento — arquivos com timestamp + arquivos fixos
    logger.info("ETAPA 9/9 - Salvando resultados...")

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
    caminho_diagnostico_web = salvar_resultados(candidatas_com_diagnostico_web, sufixo="candidatas_com_diagnostico_web")
    caminho_presenca_consolidada = salvar_resultados(empresas, sufixo="candidatas_com_presenca_consolidada")

    # Arquivos fixos (persistentes — sobrescritos a cada execução)
    historico_lista = list(historico_atual.values())
    caminho_historico = salvar_json_fixo(historico_lista, _NOME_HISTORICO)
    caminho_fila = salvar_json_fixo(fila_revisao, _NOME_FILA)
    caminho_resumo = salvar_json_fixo(resumo_execucao, _NOME_RESUMO)
    caminho_fila_presenca = salvar_json_fixo(fila_oportunidades_presenca, _NOME_FILA_PRESENCA)
    caminho_canais_digitais = salvar_json_fixo(candidatas_com_canais_digitais, _NOME_CANAIS_DIGITAIS)
    caminho_fila_marketing = salvar_json_fixo(fila_oportunidades_marketing, _NOME_FILA_MARKETING)

    # Contagens por classificação, status e presença web
    contagens = _contar_por_classificacao(empresas)
    contagem_status = resumo_execucao.get("contagem_por_status_interno", {})
    contagem_presenca_web = _contar_por_presenca_web(candidatas_com_diagnostico_web)
    n_sites_acessiveis = sum(1 for e in candidatas_com_diagnostico_web if e.get("site_acessivel"))

    # Log detalhado
    duracao = int((datetime.now() - inicio).total_seconds())
    logger.info("=" * 60)
    logger.info("CONCLUIDO v0.8")
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
    logger.info(f"  PRESENCA DIGITAL WEB:")
    logger.info(f"    com website              : {len(candidatas_com_diagnostico_web)}")
    logger.info(f"    sites acessiveis         : {n_sites_acessiveis}")
    for cls, n in sorted(contagem_presenca_web.items()):
        logger.info(f"    {cls:<28}: {n}")
    logger.info(f"    fila_oportunidades       : {len(fila_oportunidades_presenca)}")
    logger.info(f"  PRESENCA CONSOLIDADA (comercial):")
    for cls, n in sorted(contagem_cls_presenca.items(), key=lambda x: ["oportunidade_alta_presenca","oportunidade_media_presenca","oportunidade_baixa_presenca","pouca_utilidade_presenca"].index(x[0]) if x[0] in ["oportunidade_alta_presenca","oportunidade_media_presenca","oportunidade_baixa_presenca","pouca_utilidade_presenca"] else 9):
        logger.info(f"    {cls:<36}: {n}")
    logger.info(f"    fila_oportunidades_marketing     : {len(fila_oportunidades_marketing)}")
    logger.info(f"  CANAIS DIGITAIS:")
    logger.info(f"    com canal identificado   : {len(candidatas_com_canais_digitais)}")
    contagem_canais = _contar_por_confianca_canais(candidatas_com_canais_digitais)
    for canal, counts in sorted(contagem_canais.items()):
        partes = ", ".join(f"{k}:{v}" for k, v in sorted(counts.items()) if k != "nao_identificado" and v > 0)
        if partes:
            logger.info(f"    {canal:<16}: {partes}")
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
    logger.info(f"  candidatas_diagnostico_web : {caminho_diagnostico_web}")
    logger.info(f"  presenca_consolidada       : {caminho_presenca_consolidada}")
    logger.info(f"  canais_digitais            : {caminho_canais_digitais}")
    logger.info(f"  prospeccao_historico       : {caminho_historico}")
    logger.info(f"  fila_revisao               : {caminho_fila}")
    logger.info(f"  resumo_execucao            : {caminho_resumo}")
    logger.info(f"  fila_oportunidades_presenca: {caminho_fila_presenca}")
    logger.info(f"  candidatas_com_canais      : {caminho_canais_digitais}")
    logger.info(f"  fila_oportunidades_mktg    : {caminho_fila_marketing}")
    logger.info(f"  log                        : {arquivo_log}")
    logger.info(f"  Duracao total              : {duracao}s")
    logger.info("=" * 60)

    # Resumo limpo no terminal
    print("\n" + "=" * 58)
    print("PROSPECCAO CONCLUIDA v0.8")
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
    print(f"PRESENCA DIGITAL WEB:")
    print(f"  com website              : {len(candidatas_com_diagnostico_web)}")
    print(f"  sites acessiveis         : {n_sites_acessiveis}")
    for cls in ("presenca_boa", "presenca_razoavel", "presenca_basica", "presenca_fraca", "dados_insuficientes"):
        n = contagem_presenca_web.get(cls, 0)
        if n:
            print(f"  {cls:<28}: {n}")
    print(f"  fila_oportunidades       : {len(fila_oportunidades_presenca)}")
    print(f"PRESENCA CONSOLIDADA:")
    for cls in ("oportunidade_alta_presenca", "oportunidade_media_presenca", "oportunidade_baixa_presenca", "pouca_utilidade_presenca"):
        n = contagem_cls_presenca.get(cls, 0)
        if n:
            print(f"  {cls:<36}: {n}")
    print(f"  fila_oportunidades_marketing     : {len(fila_oportunidades_marketing)}")
    print(f"CANAIS DIGITAIS:")
    print(f"  com canal identificado   : {len(candidatas_com_canais_digitais)}")
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


def _contar_por_classificacao_presenca(empresas: list) -> dict:
    contagens: dict = {}
    for e in empresas:
        cls = e.get("classificacao_presenca_comercial", "pouca_utilidade_presenca")
        contagens[cls] = contagens.get(cls, 0) + 1
    return contagens


def _contar_por_confianca_canais(empresas: list) -> dict:
    """Conta por canal e nível de confiança."""
    canais = ["website", "instagram", "facebook", "whatsapp", "email", "telefone"]
    resultado: dict = {}
    for canal in canais:
        counts: dict = {}
        for e in empresas:
            conf = e.get(f"confianca_{canal}", "nao_identificado")
            counts[conf] = counts.get(conf, 0) + 1
        resultado[canal] = counts
    return resultado


def _contar_por_presenca_web(empresas: list) -> dict:
    contagens: dict = {}
    for e in empresas:
        cls = e.get("classificacao_presenca_web", "dados_insuficientes")
        contagens[cls] = contagens.get(cls, 0) + 1
    return contagens


def _gerar_fila_presenca(empresas: list) -> list:
    """
    Gera fila de oportunidades de presença digital.

    Inclui empresas com website que:
    - Têm site acessível
    - Têm presença fraca ou básica (maior oportunidade de melhoria)
    - São comercialmente úteis (não são pouco_util)

    Ordenação: presenca_fraca primeiro, depois presenca_basica,
               depois por score_prontidao_ia decrescente.
    """
    _ORDEM_PRESENCA = {
        "presenca_fraca": 0,
        "presenca_basica": 1,
        "presenca_razoavel": 2,
        "presenca_boa": 3,
        "dados_insuficientes": 4,
    }
    candidatas = [
        e for e in empresas
        if e.get("site_acessivel")
        and e.get("classificacao_presenca_web") in ("presenca_fraca", "presenca_basica", "presenca_razoavel")
        and e.get("classificacao_comercial") != "pouco_util"
    ]
    return sorted(
        candidatas,
        key=lambda e: (
            _ORDEM_PRESENCA.get(e.get("classificacao_presenca_web", "dados_insuficientes"), 4),
            -e.get("score_presenca_web", 0),
            -e.get("score_prontidao_ia", 0),
        ),
    )
