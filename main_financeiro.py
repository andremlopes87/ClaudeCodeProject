"""
main_financeiro.py — Ponto de entrada da linha financeira.

Fase 1: eventos nao estruturados → classificacao → posicao de caixa → alertas.
Fase 2: + contas a receber + contas a pagar + resumo financeiro operacional.
Fase 3: + previsao de caixa (7/30/60/90 dias) + fila de riscos acionaveis.

Para uso real:
  - Substitua os exemplos abaixo pelos dados reais da empresa.
  - Ajuste config.FINANCEIRO_SALDO_INICIAL com o saldo real da conta bancaria.
  - Execute periodicamente para reclassificar, recalcular e gerar alertas atualizados.
"""

import logging
from datetime import datetime

import config
from modulos.financeiro.registrador_eventos import registrar_lote
from modulos.financeiro.contas_a_receber import (
    registrar_lote_receber,
    carregar_contas_a_receber,
)
from modulos.financeiro.contas_a_pagar import (
    registrar_lote_pagar,
    carregar_contas_a_pagar,
)
from modulos.financeiro.pipeline import executar_analise_financeira
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
# Eventos: transacoes pontuais sem lifecycle (recebimentos avulsos, despesas nao programadas).

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

CONTAS_A_RECEBER_EXEMPLO = [
    {
        "contraparte":     "Barbearia Central",
        "descricao":       "Mensalidade marco/2026",
        "valor_total":     900.00,
        "data_emissao":    "2026-03-20",
        "data_vencimento": "2026-03-28",
        "status":          "aberta",
        "categoria":       "receita",
        "referencia":      "FT-2026-032",
    },
    {
        "contraparte":     "Oficina Modelo",
        "descricao":       "Implantacao agente de atendimento",
        "valor_total":     3500.00,
        "data_emissao":    "2026-03-21",
        "data_vencimento": "2026-04-05",
        "status":          "aberta",
        "categoria":       "receita",
        "observacoes":     "proposta assinada em 21/03",
    },
    {
        "contraparte":     "Padaria do Joao",
        "descricao":       "Mensalidade fevereiro/2026",
        "valor_total":     750.00,
        "data_emissao":    "2026-02-15",
        "data_vencimento": "2026-02-28",
        "status":          "aberta",  # detectada como vencida na leitura
        "categoria":       "receita",
        "referencia":      "FT-2026-022",
        "observacoes":     "segunda vez que atrasa",
    },
]

# ─── Contas a pagar de exemplo ───────────────────────────────────────────────

CONTAS_A_PAGAR_EXEMPLO = [
    {
        "contraparte":     "Imobiliaria ABC",
        "descricao":       "Aluguel escritorio — abril/2026",
        "valor_total":     1200.00,
        "data_lancamento": "2026-03-21",
        "data_vencimento": "2026-03-24",
        "status":          "aberta",
        "categoria":       "despesa_fixa",
        "referencia":      "ALUG-2026-04",
    },
    {
        "contraparte":     "Freelancer TBD",
        "descricao":       "Desenvolvimento modulo financeiro — marco/2026",
        "valor_total":     2000.00,
        "data_lancamento": "2026-03-21",
        "data_vencimento": "2026-03-31",
        "status":          "aberta",
        "categoria":       "despesa_operacional",
    },
]


def executar_financeiro() -> None:
    arquivo_log = configurar_logs()
    logger = logging.getLogger(__name__)
    inicio = datetime.now()

    logger.info("=" * 60)
    logger.info("INICIANDO LINHA FINANCEIRA — FASE 3")
    logger.info("=" * 60)

    config.PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")

    # ETAPA 1: Registrar eventos
    logger.info("ETAPA 1 — Registrando eventos...")
    salvar_json_fixo([], "eventos_financeiros.json")
    registrados = registrar_lote(EVENTOS_EXEMPLO)
    logger.info(f"  {len(registrados)} eventos registrados.")

    # ETAPA 2: Registrar contas a receber
    logger.info("ETAPA 2 — Registrando contas a receber...")
    salvar_json_fixo([], "contas_a_receber.json")
    receber_reg = registrar_lote_receber(CONTAS_A_RECEBER_EXEMPLO)
    logger.info(f"  {len(receber_reg)} contas registradas.")

    # ETAPA 3: Registrar contas a pagar
    logger.info("ETAPA 3 — Registrando contas a pagar...")
    salvar_json_fixo([], "contas_a_pagar.json")
    pagar_reg = registrar_lote_pagar(CONTAS_A_PAGAR_EXEMPLO)
    logger.info(f"  {len(pagar_reg)} contas registradas.")

    # ETAPA 4–9: Pipeline de análise financeira (reutilizável por agentes)
    logger.info("ETAPA 4 — Executando pipeline de analise financeira...")
    resultado   = executar_analise_financeira(salvar=True, ts=ts)
    posicao     = resultado["posicao"]
    alertas     = resultado["alertas"]
    decisoes    = resultado["decisoes"]
    resumo      = resultado["resumo"]
    previsao    = resultado["previsao"]
    fila_riscos = resultado["fila_riscos"]
    receber     = resultado["contas_a_receber"]
    pagar       = resultado["contas_a_pagar"]
    logger.info(f"  {len(fila_riscos)} riscos identificados.")

    duracao = int((datetime.now() - inicio).total_seconds())
    pasta = config.PASTA_DADOS
    sinais = previsao["sinais_crescimento"]

    # ─── Resumo no terminal ───────────────────────────────────────────────
    print("\n" + "=" * 64)
    print("LINHA FINANCEIRA — FASE 3")
    print("=" * 64)
    print(f"Eventos registrados            : {len(registrados)}")
    print(f"Contas a receber               : {len(receber_reg)}")
    print(f"Contas a pagar                 : {len(pagar_reg)}")
    print("---")
    print("POSICAO DE CAIXA:")
    print(f"  Saldo inicial                : R$ {posicao['saldo_inicial']:>10,.2f}")
    print(f"  Saldo atual estimado         : R$ {posicao['saldo_atual_estimado']:>10,.2f}")
    print(f"  Total recebido confirmado    : R$ {posicao['total_recebido_confirmado']:>10,.2f}")
    print(f"  Total pago confirmado        : R$ {posicao['total_pago_confirmado']:>10,.2f}")
    print(f"  A receber aberto (faturado)  : R$ {posicao['total_a_receber_aberto']:>10,.2f}")
    print(f"  A receber previsto           : R$ {posicao['total_a_receber_previsto']:>10,.2f}")
    print(f"  A pagar aberto (compromet.)  : R$ {posicao['total_a_pagar_aberto']:>10,.2f}")
    print(f"  A pagar previsto             : R$ {posicao['total_a_pagar_previsto']:>10,.2f}")
    print(f"  Total aberto a receber       : R$ {posicao['total_aberto_a_receber']:>10,.2f}")
    print(f"  Total aberto a pagar         : R$ {posicao['total_aberto_a_pagar']:>10,.2f}")
    print(f"  Vencido a receber            : R$ {posicao['total_vencido_a_receber']:>10,.2f}")
    print(f"  Vencido a pagar              : R$ {posicao['total_vencido_a_pagar']:>10,.2f}")
    print(f"  Saldo previsto               : R$ {posicao['saldo_previsto']:>10,.2f}")
    print(f"  Risco de caixa               : {'SIM' if posicao['risco_caixa'] else 'nao'}")
    print("---")
    print("PREVISAO DE CAIXA:")
    for nome, j in previsao["janelas"].items():
        buraco = " [BURACO]" if j["houve_buraco_de_caixa"] else ""
        print(
            f"  {nome:8} | saldo projetado: R$ {j['saldo_projetado']:>9,.2f} "
            f"| entradas: R$ {j['entradas_previstas']:>8,.2f} "
            f"| saidas: R$ {j['saidas_previstas']:>8,.2f}"
            f"{buraco}"
        )
        if j["houve_buraco_de_caixa"]:
            print(f"           menor saldo: R$ {j['menor_saldo_projetado_na_janela']:>9,.2f} em {j['data_do_menor_saldo']}")
    print("---")
    print(f"SINAIS (heuristicos):")
    print(f"  Classificacao                : {sinais['classificacao']}")
    print(f"  Risco operacional imediato   : {'SIM' if sinais['risco_operacional_imediato'] else 'nao'}")
    print(f"  Risco de crescimento         : {'SIM' if sinais['risco_de_crescimento'] else 'nao'}")
    print(f"  Buraco de caixa em 30 dias   : {'SIM' if sinais['buraco_de_caixa_em_30_dias'] else 'nao'}")
    print(f"  Dependencia concentrada      : {'SIM' if sinais['dependencia_concentrada'] else 'nao'}")
    if sinais["dependencia_concentrada"]:
        print(f"    {sinais['maior_contraparte']} = {sinais['percentual_maior_contraparte']:.0f}% do aberto")
    print(f"  Folga para investir          : R$ {sinais['folga_para_investir']:>10,.2f}")
    for obs in sinais["observacoes_recomendadas"]:
        print(f"  > {obs}")
    print("---")
    print(f"Riscos identificados           : {len(fila_riscos)}")
    for r in fila_riscos:
        prazo = f" | prazo: {r['prazo_sugerido']}" if r.get("prazo_sugerido") else ""
        print(f"  [{r['urgencia']:5}] {r['tipo']} — {r['descricao']}")
        print(f"           Acao: {r['acao_sugerida']}{prazo}")
    print("---")
    print(f"Alertas                        : {len(alertas)}")
    print(f"Decisoes humanas               : {len(decisoes)}")
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
        "previsao_caixa.json",
        "fila_riscos_financeiros.json",
    ]:
        print(f"  {pasta / nome}")
    print(f"Duracao                        : {duracao}s")
    print("=" * 64)


if __name__ == "__main__":
    executar_financeiro()
