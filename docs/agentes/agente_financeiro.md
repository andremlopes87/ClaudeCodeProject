# agente_financeiro

## Objetivo

Manter a posição de caixa atualizada, classificar eventos e contas, gerar previsão de fluxo e alertar sobre riscos financeiros.

Não movimenta dinheiro. Não cobra clientes. Não paga fornecedores. Não renegocia. Apenas lê, calcula, alerta e recomenda.

---

## Entradas

- `dados/eventos_financeiros.json` — transações avulsas registradas
- `dados/contas_a_receber.json` — contas estruturadas com lifecycle
- `dados/contas_a_pagar.json` — obrigações estruturadas com lifecycle
- `config.py` — parâmetros financeiros (saldo inicial, thresholds, dias de alerta)

## Saídas

- `dados/posicao_caixa.json` — posição consolidada atual
- `dados/previsao_caixa.json` — projeção por janela de 7/30/60/90 dias
- `dados/fila_alertas_financeiros.json` — alertas operacionais priorizados
- `dados/fila_decisoes_financeiras.json` — itens que exigem decisão humana
- `dados/fila_riscos_financeiros.json` — riscos acionáveis com tipo, urgência e ação sugerida
- `dados/resumo_financeiro_operacional.json` — visão consolidada para o secretário e o usuário
- `logs/financeiro_{timestamp}.log`

---

## Decisões que pode tomar sozinho

- Classificar eventos por tipo, impacto e urgência
- Aplicar status efetivo (conta aberta + vencimento passado → vencida) sem alterar o arquivo base
- Calcular posição de caixa e saldo previsto
- Gerar previsão de fluxo e detectar buracos de caixa dentro de cada janela
- Gerar e priorizar alertas operacionais
- Calcular sinais heurísticos de crescimento (claramente rotulados como heurísticas, não métricas formais)
- Gerar fila de riscos com ação sugerida e prazo
- Recomendar ação: "acionar cobrança", "antecipar recebível", "revisar pagamentos"

## Decisões que escalam para o usuário

- Buraco de caixa projetado em menos de 7 dias
- Risco classificado como `alta` na fila de riscos
- Conta vencida acima do threshold sem resolução
- Qualquer cobrança real a cliente
- Qualquer pagamento real a fornecedor
- Renegociação de prazo ou valor
- Movimentação financeira de qualquer natureza

---

## Rotinas

**Diária:** recalcular posição de caixa, atualizar alertas, verificar vencimentos do dia e próximos 7 dias
**Semanal:** previsão de 30/60/90 dias, relatório de saúde financeira, atualizar riscos

**Gatilhos automáticos:**
- Nova conta registrada → recalcular posição imediatamente
- Conta chega na data de vencimento → atualizar status efetivo e gerar alerta
- Saldo previsto abaixo do threshold → gerar decisão para o usuário

---

## Limites de autonomia

| Pode | Não pode |
|---|---|
| Classificar eventos e contas | Cobrar cliente diretamente |
| Calcular posição e previsão | Pagar fornecedor |
| Gerar alertas e riscos | Renegociar prazo ou valor |
| Recomendar ação | Movimentar dinheiro |
| Aplicar status efetivo em memória | Alterar status persistido sem instrução |
