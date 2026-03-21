"""
main_financeiro.py — Ponto de entrada da linha financeira.

Fase 1: eventos não estruturados → classificação → posição de caixa → alertas.
Fase 2: + contas a receber + contas a pagar + resumo financeiro operacional.

Para uso real:
  - Substitua os exemplos abaixo pelos dados reais da empresa.
  - Use registrar_lote_receber() / registrar_lote_pagar() para adicionar contas incrementalmente.
  - Execute este script periodicamente para reclassificar, recalcular e gerar alertas atualizados.
  - Ajuste config.FINANCEIRO_SALDO_INICIAL com o saldo real da conta bancária.
"""

import json
import logging
from datetime import datetime

import config
from modulos.financeiro.registrador_eventos import registrar_lote, carregar_eventos
from modulos.financeiro.classificador_eventos import classificar_eventos
from modulos.financeiro.analisador_caixa import analisar_caixa
from modulos.financeiro.gerador_alertas import gerar_alertas
from modulos.financeiro.resumo_financeiro import gerar_resumo
from modulos.financeiro.contas_a_receber import (
    registrar_lote_receber,
    carregar_com_status_efetivo as receber_efetivo,
)
from modulos.financeiro.contas_a_pagar import (
    registrar_lote_pagar,
    carregar_com_status_efetivo as pagar_efetivo,
)
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


# ─── Eventos de exemplo ─────────────────────────────────────────────────────
# Eventos: transações pontuais sem lifecycle (despesas avulsas, recebimentos diretos).
# Para itens com vencimento e ciclo de vida, use contas_a_receber / contas_a_pagar.

EVENTOS_EXEMPLO = [
    {
        "tipo": "cobranca_recebida",
        "descricao": "Mensalidade Qually Estetica — marco/2026",
        "valor": 1800.00,
        "data_evento": "2026-03-15",
        "status": "confirmado",
        "categoria": "receita",
        "contraparte": "Qually Estetica Automotiva",
        "canal_origem": "manual",
        "referencia": "FT-2026-031",
    },
    {
        "tipo": "despesa_identificada",
        "descricao": "Assinaturas SaaS — marco/2026",
        "valor": 320.00,
        "data_evento": "2026-03-01",
        "status": "confirmado",
        "categoria": "despesa_operacional",
        "contraparte": "Diversos",
        "canal_origem": "manual",
    },
]

# ─── Contas a receber de exemplo ────────────────────────────────────────────
# Itens faturados com vencimento, confirmação e acompanhamento de saldo.

CONTAS_A_RECEBER_EXEMPLO = [
    {
        "contraparte":   "Barbearia Central",
        "descricao":     "Mensalidade marco/2026",
        "valor_total":   900.00,
        "data_emissao":  "2026-03-20",
        "data_vencimento": "2026-03-28",
        "status":        "aberta",
        "categoria":     "receita",
        "referencia":    "FT-2026-032",
    },
    {
        "contraparte":   "Oficina Modelo",
        "descricao":     "Implantacao agente de atendimento",
        "valor_total":   3500.00,
        "data_emissao":  "2026-03-21",
        "data_vencimento": "2026-04-05",
        "status":        "aberta",
        "categoria":     "receita",
        "observacoes":   "proposta assinada em 21/03 — aguardando vencimento",
    },
    {
        "contraparte":   "Padaria do Joao",
        "descricao":     "Mensalidade fevereiro/2026",
        "valor_total":   750.00,
        "data_emissao":  "2026-02-15",
        "data_vencimento": "2026-02-28",
        "status":        "aberta",   # será ajustada para vencida na leitura (prazo expirou)
        "categoria":     "receita",
        "referencia":    "FT-2026-022",
        "observacoes":   "segunda vez que atrasa — acionar cobranca",
    },
]

# ─── Contas a pagar de exemplo ───────────────────────────────────────────────
# Despesas programadas com vencimento e controle de pagamento.

CONTAS_A_PAGAR_EXEMPLO = [
    {
        "contraparte":    "Imobiliaria ABC",
        "descricao":      "Aluguel escritorio — abril/2026",
        "valor_total":    1200.00,
        "data_lancamento": "2026-03-21",
        "data_vencimento": "2026-03-24",
        "status":         "aberta",
        "categoria":      "despesa_fixa",
        "referencia":     "ALUG-2026-04",
    },
    {
        "contraparte":    "Freelancer TBD",
        "descricao":      "Desenvolvimento modulo financeiro — marco/2026",
        "valor_total":    2000.00,
        "data_lancamento": "2026-03-21",
        "data_vencimento": "2026-03-31",
        "status":         "aberta",
        "categoria":      "despesa_operacional",
    },
]


def executar_financeiro() -> None:
    arquivo_log = configurar_logs()
    logger = logging.getLogger(__name__)
    inicio = datetime.now()

    logger.info("=" * 60)
    logger.info("INICIANDO LINHA FINANCEIRA — FASE 2")
    logger.info("=" * 60)

    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")

    # ETAPA 1: Registrar eventos (reinicia arquivo para demo)
    logger.info("ETAPA 1 — Registrando eventos...")
    salvar_json_fixo([], "eventos_financeiros.json")
    registrados = registrar_lote(EVENTOS_EXEMPLO)
    logger.info(f"  {len(registrados)} eventos registrados.")

    # ETAPA 2: Classificar eventos
    logger.info("ETAPA 2 — Classificando eventos...")
    eventos = carregar_eventos()
    eventos = classificar_eventos(eventos)
    salvar_json_fixo(eventos, "eventos_financeiros.json")
    _salvar_ts(eventos, f"eventos_financeiros_{timestamp}.json")
    logger.info(f"  {len(eventos)} eventos classificados.")

    # ETAPA 3: Registrar contas a receber (reinicia arquivo para demo)
    logger.info("ETAPA 3 — Registrando contas a receber...")
    salvar_json_fixo([], "contas_a_receber.json")
    receber_reg = registrar_lote_receber(CONTAS_A_RECEBER_EXEMPLO)
    logger.info(f"  {len(receber_reg)} contas a receber registradas.")

    # ETAPA 4: Registrar contas a pagar (reinicia arquivo para demo)
    logger.info("ETAPA 4 — Registrando contas a pagar...")
    salvar_json_fixo([], "contas_a_pagar.json")
    pagar_reg = registrar_lote_pagar(CONTAS_A_PAGAR_EXEMPLO)
    logger.info(f"  {len(pagar_reg)} contas a pagar registradas.")

    # Salva snapshots timestamped das contas
    from modulos.financeiro.contas_a_receber import carregar_contas_a_receber
    from modulos.financeiro.contas_a_pagar import carregar_contas_a_pagar
    _salvar_ts(carregar_contas_a_receber(), f"contas_a_receber_{timestamp}.json")
    _salvar_ts(carregar_contas_a_pagar(),   f"contas_a_pagar_{timestamp}.json")

    # ETAPA 5: Carregar com status efetivo (vencimento ajustado)
    receber = receber_efetivo()
    pagar   = pagar_efetivo()

    # ETAPA 6: Posição de caixa
    logger.info("ETAPA 6 — Calculando posicao de caixa...")
    posicao = analisar_caixa(eventos, contas_a_receber=receber, contas_a_pagar=pagar)
    salvar_json_fixo(posicao, "posicao_caixa.json")
    _salvar_ts(posicao, f"posicao_caixa_{timestamp}.json")
    logger.info(f"  {posicao['resumo_curto']}")

    # ETAPA 7: Alertas e decisões
    logger.info("ETAPA 7 — Gerando alertas e decisoes...")
    alertas, decisoes = gerar_alertas(
        eventos, posicao,
        contas_a_receber=receber,
        contas_a_pagar=pagar,
    )
    salvar_json_fixo(alertas,  "fila_alertas_financeiros.json")
    salvar_json_fixo(decisoes, "fila_decisoes_financeiras.json")
    _salvar_ts(alertas,  f"fila_alertas_financeiros_{timestamp}.json")
    _salvar_ts(decisoes, f"fila_decisoes_financeiras_{timestamp}.json")
    logger.info(f"  {len(alertas)} alertas | {len(decisoes)} decisoes")

    # ETAPA 8: Resumo financeiro operacional
    logger.info("ETAPA 8 — Gerando resumo financeiro operacional...")
    resumo = gerar_resumo(posicao, receber, pagar, alertas, decisoes)
    salvar_json_fixo(resumo, "resumo_financeiro_operacional.json")
    _salvar_ts(resumo, f"resumo_financeiro_operacional_{timestamp}.json")
    logger.info(f"  {resumo['resumo_curto']}")

    duracao = int((datetime.now() - inicio).total_seconds())
    pasta = config.PASTA_DADOS

    # ─── Resumo no terminal ───────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("LINHA FINANCEIRA — FASE 2")
    print("=" * 62)
    print(f"Eventos registrados          : {len(registrados)}")
    print(f"Contas a receber             : {len(receber_reg)}")
    print(f"Contas a pagar               : {len(pagar_reg)}")
    print("---")
    print("POSICAO DE CAIXA:")
    print(f"  Saldo inicial              : R$ {posicao['saldo_inicial']:>10,.2f}")
    print(f"  Saldo atual estimado       : R$ {posicao['saldo_atual_estimado']:>10,.2f}")
    print(f"  A receber confirmado       : R$ {posicao['total_a_receber_confirmado']:>10,.2f}")
    print(f"  A receber previsto         : R$ {posicao['total_a_receber_previsto']:>10,.2f}")
    print(f"  A pagar confirmado         : R$ {posicao['total_a_pagar_confirmado']:>10,.2f}")
    print(f"  A pagar previsto           : R$ {posicao['total_a_pagar_previsto']:>10,.2f}")
    print(f"  Total aberto a receber     : R$ {posicao['total_aberto_a_receber']:>10,.2f}")
    print(f"  Total aberto a pagar       : R$ {posicao['total_aberto_a_pagar']:>10,.2f}")
    print(f"  Vencido a receber          : R$ {posicao['total_vencido_a_receber']:>10,.2f}")
    print(f"  Vencido a pagar            : R$ {posicao['total_vencido_a_pagar']:>10,.2f}")
    print(f"  Saldo previsto             : R$ {posicao['saldo_previsto']:>10,.2f}")
    print(f"  Risco de caixa             : {'SIM' if posicao['risco_caixa'] else 'nao'}")
    print("---")
    print("RESUMO OPERACIONAL:")
    print(f"  Contas receber abertas     : {resumo['total_contas_a_receber_abertas']}")
    print(f"  Contas receber vencidas    : {resumo['total_contas_a_receber_vencidas']}")
    print(f"  Contas pagar abertas       : {resumo['total_contas_a_pagar_abertas']}")
    print(f"  Contas pagar vencidas      : {resumo['total_contas_a_pagar_vencidas']}")
    print(f"  Total em aberto a receber  : R$ {resumo['total_em_aberto_a_receber']:>10,.2f}")
    print(f"  Total em aberto a pagar    : R$ {resumo['total_em_aberto_a_pagar']:>10,.2f}")
    print(f"  Total vencido a receber    : R$ {resumo['total_vencido_a_receber']:>10,.2f}")
    print(f"  Total vencido a pagar      : R$ {resumo['total_vencido_a_pagar']:>10,.2f}")
    print("---")
    print(f"Alertas gerados              : {len(alertas)}")
    for a in alertas:
        print(f"  [{a.get('urgencia', '?'):13}] {a['descricao']} — {a.get('motivo_alerta', '')}")
    print("---")
    print(f"Decisoes humanas             : {len(decisoes)}")
    for d in decisoes:
        print(f"  [{d.get('urgencia', '?'):13}] {d['descricao']} — {d.get('motivo_decisao', '')}")
    print("---")
    print("ARQUIVOS GERADOS (latest):")
    for nome in [
        "eventos_financeiros.json",
        "contas_a_receber.json",
        "contas_a_pagar.json",
        "posicao_caixa.json",
        "fila_alertas_financeiros.json",
        "fila_decisoes_financeiras.json",
        "resumo_financeiro_operacional.json",
    ]:
        print(f"  {pasta / nome}")
    print(f"Duracao                      : {duracao}s")
    print("=" * 62)


def _salvar_ts(dados, nome_arquivo: str) -> None:
    """Salva snapshot timestamped em dados/."""
    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = config.PASTA_DADOS / nome_arquivo
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
    logger_ts = logging.getLogger(__name__)
    n = len(dados) if isinstance(dados, list) else 1
    logger_ts.info(f"Arquivo salvo: {caminho} ({n} registros)")


if __name__ == "__main__":
    executar_financeiro()
