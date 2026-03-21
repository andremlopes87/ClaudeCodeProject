"""
main_financeiro.py — Ponto de entrada da linha financeira.

Fase 1: registro manual de eventos → classificação → posição de caixa → alertas → decisões.

Para uso real:
  - Substitua ou complemente EVENTOS_EXEMPLO com os eventos reais da empresa.
  - Chame registrar_lote() ou registrar_evento() para adicionar eventos incrementalmente.
  - Execute este script para reclassificar, recalcular posição e gerar alertas atualizados.
"""

import logging
from datetime import datetime

import config
from modulos.financeiro.registrador_eventos import registrar_lote, carregar_eventos
from modulos.financeiro.classificador_eventos import classificar_eventos
from modulos.financeiro.analisador_caixa import analisar_caixa
from modulos.financeiro.gerador_alertas import gerar_alertas
from core.persistencia import salvar_json_fixo


def configurar_logs() -> str:
    config.PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    arquivo_log = config.PASTA_LOGS / f"financeiro_{timestamp}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(arquivo_log), encoding="utf-8"),
        ],
    )
    return str(arquivo_log)


# ─── Eventos de exemplo ────────────────────────────────────────────────────
# Substitua por eventos reais em produção.
# Em uso incremental: registrar_evento() ou registrar_lote() separadamente.

EVENTOS_EXEMPLO = [
    {
        "tipo": "cobranca_recebida",
        "descricao": "Mensalidade cliente Qually Estética — março/2026",
        "valor": 1800.00,
        "data_evento": "2026-03-15",
        "status": "confirmado",
        "categoria": "receita",
        "contraparte": "Qually Estética Automotiva",
        "canal_origem": "manual",
        "referencia": "FT-2026-031",
    },
    {
        "tipo": "cobranca_emitida",
        "descricao": "Mensalidade cliente Barbearia Central — março/2026",
        "valor": 900.00,
        "data_evento": "2026-03-20",
        "data_vencimento": "2026-03-28",
        "status": "pendente",
        "categoria": "receita",
        "contraparte": "Barbearia Central",
        "canal_origem": "manual",
        "referencia": "FT-2026-032",
    },
    {
        "tipo": "entrada_prevista",
        "descricao": "Proposta aprovada verbalmente — implantação Oficina Modelo",
        "valor": 3500.00,
        "data_evento": "2026-03-21",
        "data_vencimento": "2026-04-05",
        "status": "pendente",
        "categoria": "receita",
        "contraparte": "Oficina Modelo",
        "canal_origem": "manual",
        "observacoes": "cliente confirmou verbalmente — proposta formal pendente",
    },
    {
        "tipo": "despesa_identificada",
        "descricao": "Assinaturas SaaS — março/2026",
        "valor": 320.00,
        "data_evento": "2026-03-01",
        "status": "confirmado",
        "categoria": "despesa_operacional",
        "contraparte": "Diversos",
        "canal_origem": "manual",
    },
    {
        "tipo": "conta_a_vencer",
        "descricao": "Aluguel escritório — abril/2026",
        "valor": 1200.00,
        "data_evento": "2026-03-21",
        "data_vencimento": "2026-03-24",
        "status": "pendente",
        "categoria": "despesa_fixa",
        "contraparte": "Imobiliária ABC",
        "canal_origem": "manual",
        "referencia": "ALUG-2026-04",
    },
    {
        "tipo": "cliente_atrasou",
        "descricao": "Mensalidade cliente Padaria do João — fevereiro/2026",
        "valor": 750.00,
        "data_evento": "2026-03-10",
        "data_vencimento": "2026-02-28",
        "status": "vencido",
        "categoria": "receita",
        "contraparte": "Padaria do João",
        "canal_origem": "manual",
        "referencia": "FT-2026-022",
        "observacoes": "segunda vez que atrasa — monitorar",
    },
    {
        "tipo": "saida_prevista",
        "descricao": "Freelancer — desenvolvimento módulo de março",
        "valor": 2000.00,
        "data_evento": "2026-03-21",
        "data_vencimento": "2026-03-31",
        "status": "pendente",
        "categoria": "despesa_operacional",
        "contraparte": "Freelancer TBD",
        "canal_origem": "manual",
    },
]


def executar_financeiro() -> None:
    arquivo_log = configurar_logs()
    logger = logging.getLogger(__name__)
    inicio = datetime.now()

    logger.info("=" * 60)
    logger.info("INICIANDO LINHA FINANCEIRA — FASE 1")
    logger.info("=" * 60)

    # ETAPA 1: Registrar eventos (reinicia o arquivo para demo)
    logger.info("ETAPA 1 — Registrando eventos...")
    salvar_json_fixo([], "eventos_financeiros.json")   # limpa para esta execução de demo
    registrados = registrar_lote(EVENTOS_EXEMPLO)
    logger.info(f"  {len(registrados)} eventos registrados.")

    # ETAPA 2: Carregar e classificar
    logger.info("ETAPA 2 — Classificando eventos...")
    eventos = carregar_eventos()
    eventos = classificar_eventos(eventos)
    salvar_json_fixo(eventos, "eventos_financeiros.json")
    logger.info(f"  {len(eventos)} eventos classificados.")

    # ETAPA 3: Posição de caixa
    logger.info("ETAPA 3 — Calculando posição de caixa...")
    posicao = analisar_caixa(eventos)
    salvar_json_fixo(posicao, "posicao_caixa.json")
    logger.info(f"  {posicao['resumo_curto']}")

    # ETAPA 4: Alertas e decisões
    logger.info("ETAPA 4 — Gerando alertas e fila de decisões...")
    alertas, decisoes = gerar_alertas(eventos, posicao)
    salvar_json_fixo(alertas, "fila_alertas_financeiros.json")
    salvar_json_fixo(decisoes, "fila_decisoes_financeiras.json")
    logger.info(f"  {len(alertas)} alertas | {len(decisoes)} decisões")

    duracao = int((datetime.now() - inicio).total_seconds())
    pasta = config.PASTA_DADOS

    # ─── Resumo no terminal ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("LINHA FINANCEIRA — FASE 1")
    print("=" * 60)
    print(f"Eventos registrados        : {len(registrados)}")
    print(f"Eventos classificados      : {len(eventos)}")
    print("---")
    print("POSIÇÃO DE CAIXA:")
    print(f"  Saldo atual estimado     : R$ {posicao['saldo_atual_estimado']:>10,.2f}")
    print(f"  A receber confirmado     : R$ {posicao['total_a_receber_confirmado']:>10,.2f}")
    print(f"  A receber previsto       : R$ {posicao['total_a_receber_previsto']:>10,.2f}")
    print(f"  A pagar confirmado       : R$ {posicao['total_a_pagar_confirmado']:>10,.2f}")
    print(f"  A pagar previsto         : R$ {posicao['total_a_pagar_previsto']:>10,.2f}")
    print(f"  Total vencido            : R$ {posicao['total_vencido']:>10,.2f}")
    print(f"  Saldo previsto           : R$ {posicao['saldo_previsto']:>10,.2f}")
    print(f"  Risco de caixa           : {'SIM' if posicao['risco_caixa'] else 'nao'}")
    print(f"  Resumo                   : {posicao['resumo_curto']}")
    print("---")
    print(f"Alertas gerados            : {len(alertas)}")
    for a in alertas:
        print(f"  [{a.get('urgencia', '?'):13}] {a['descricao']} — {a.get('motivo_alerta', '')}")
    print("---")
    print(f"Decisoes humanas           : {len(decisoes)}")
    for d in decisoes:
        print(f"  [{d.get('urgencia', '?'):13}] {d['descricao']} — {d.get('motivo_decisao', '')}")
    print("---")
    print(f"eventos_financeiros.json   : {pasta / 'eventos_financeiros.json'}")
    print(f"posicao_caixa.json         : {pasta / 'posicao_caixa.json'}")
    print(f"fila_alertas_financeiros   : {pasta / 'fila_alertas_financeiros.json'}")
    print(f"fila_decisoes_financeiras  : {pasta / 'fila_decisoes_financeiras.json'}")
    print(f"Duracao                    : {duracao}s")
    print("=" * 60)


if __name__ == "__main__":
    executar_financeiro()
