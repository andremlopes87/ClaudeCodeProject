# Linha Financeira — Visão Geral

## Objetivo

Organizar o financeiro da empresa em torno de **eventos**, não de relatórios.

A pergunta central não é "qual é o DRE do mês?" — é:
- O que entrou?
- O que saiu?
- O que está vencendo?
- O que está atrasado?
- O que está apertando o caixa?
- O que precisa de decisão agora?

---

## Organização interna

```
modulos/financeiro/
  registrador_eventos.py    — valida e registra eventos financeiros
  classificador_eventos.py  — classifica impacto, urgência e flag de decisão
  analisador_caixa.py       — calcula posição de caixa a partir dos eventos
  gerador_alertas.py        — gera fila de alertas e fila de decisões humanas

main_financeiro.py          — ponto de entrada
```

---

## Regra de modelagem

| Campo | O que é | Muda depois? |
|---|---|---|
| `tipo` | O que aconteceu | Não — imutável após registro |
| `status` | Estado atual do evento | Sim — pode evoluir |
| `impacto_caixa` | Efeito no caixa | Recalculado a cada execução |
| `urgencia` | Prioridade de atenção | Recalculado a cada execução |
| `requer_decisao` | Precisa de humano | Recalculado a cada execução |

---

## Tipos de evento

| Tipo | Descrição | Impacto no caixa |
|---|---|---|
| `cobranca_emitida` | Cobrança enviada ao cliente | previsto_positivo → positivo quando confirmado |
| `cobranca_recebida` | Pagamento de cliente confirmado | positivo |
| `cliente_atrasou` | Cliente não pagou no vencimento | risco_positivo |
| `despesa_identificada` | Despesa registrada | negativo |
| `conta_a_vencer` | Conta com vencimento próximo | previsto_negativo |
| `conta_vencida` | Conta que passou do vencimento | negativo + urgente |
| `pagamento_confirmado` | Pagamento de despesa confirmado | negativo |
| `entrada_prevista` | Receita esperada ainda não faturada | previsto_positivo |
| `saida_prevista` | Despesa planejada ainda não executada | previsto_negativo |
| `risco_de_caixa` | Alerta manual de caixa crítico | alerta |

---

## Status de um evento

| Status | Significado |
|---|---|
| `pendente` | Registrado, aguardando confirmação ou vencimento |
| `confirmado` | Entrada ou saída realizada — entra no saldo atual |
| `vencido` | Passou do vencimento sem resolução — entra no total_vencido |
| `cancelado` | Ignorado em todas as análises |
| `em_analise` | Ambíguo — gera flag de decisão humana automaticamente |

---

## Posição de caixa

| Campo | O que representa |
|---|---|
| `saldo_atual_estimado` | Entradas confirmadas menos saídas confirmadas |
| `total_a_receber_confirmado` | Faturado e confirmado pelo cliente, ainda não recebido |
| `total_a_receber_previsto` | Esperado mas não confirmado ainda |
| `total_a_pagar_confirmado` | Compromisso de pagamento futuro (conta a vencer) |
| `total_a_pagar_previsto` | Planejado mas sem data firme |
| `total_vencido` | Valores overdue — a pagar ou a receber em atraso |
| `saldo_previsto` | Projeção: saldo + receber − pagar |
| `risco_caixa` | True se saldo previsto negativo ou há valores vencidos |
| `resumo_curto` | Texto legível com os principais números |

---

## Filas geradas

| Arquivo | O que contém |
|---|---|
| `eventos_financeiros.json` | Todos os eventos registrados e classificados |
| `posicao_caixa.json` | Posição atual de caixa calculada |
| `fila_alertas_financeiros.json` | Eventos com urgência `imediata` ou `curto_prazo` |
| `fila_decisoes_financeiras.json` | Eventos que precisam de decisão humana real |

---

## Critérios da fila de decisões

Só entra na fila de decisões se:
- Tipo `risco_de_caixa` → sempre
- `conta_vencida` ou `status=vencido` com valor ≥ `FINANCEIRO_VALOR_RELEVANTE`
- `cliente_atrasou` com valor ≥ `FINANCEIRO_VALOR_RELEVANTE`
- `despesa_identificada` com valor ≥ `FINANCEIRO_VALOR_RELEVANTE × 3`
- `status=em_analise` (evento ambíguo)
- Saldo previsto negativo (gerado pelo analisador_caixa)

---

## Configuração (config.py)

| Parâmetro | Padrão | O que controla |
|---|---|---|
| `FINANCEIRO_VALOR_RELEVANTE` | 500.00 | Limiar para considerar um valor relevante nas decisões |
| `FINANCEIRO_THRESHOLD_RISCO` | 0.0 | Saldo previsto abaixo disso → risco_caixa = True |
| `FINANCEIRO_DIAS_ALERTA_IMEDIATO` | 2 | Vence em ≤ N dias → urgência imediata |
| `FINANCEIRO_DIAS_ALERTA_CURTO_PRAZO` | 7 | Vence em ≤ N dias → urgência curto_prazo |

---

## Limitações da fase 1

- **Entrada manual**: sem integração bancária, OCR ou leitura de e-mail
- **Sem histórico entre execuções além do JSON**: não há banco de dados
- **Sem previsão de caixa por período**: apenas a projeção baseada nos eventos registrados
- **Sem categorização automática**: categoria definida por quem registra
- **Sem multi-empresa**: um único contexto financeiro

---

## Evolução prevista

```
Fase 1 (atual)  → eventos manuais + alertas + posição de caixa
Fase 2          → contas a pagar e a receber estruturadas
Fase 3          → previsão de caixa por período (30/60/90 dias)
Fase 4          → leitura de extrato OFX / arquivo bancário
Fase 5          → alertas automáticos por threshold configurável
Fase 6          → versão cliente: mesma lógica, contexto parametrizável por empresa
```
