# Acompanhamento Pós-Entrega e Expansão de Conta — Vetor

## Objetivo

Após a conclusão ou avanço de uma entrega para cliente, o sistema cria formalmente um registro de acompanhamento, calcula a saúde da conta e sugere oportunidades de expansão — tudo de forma automática, sem intervenção humana na rotina.

O conselho humano atua apenas para:
- Aprovar/rejeitar a promoção de uma expansão para handoff comercial
- Avaliar contas em estado crítico

---

## Módulo

`core/acompanhamento_contas.py`

---

## Tipos de acompanhamento

| Tipo | Trigger |
|---|---|
| `pos_entrega_inicial` | Entrega recém-aberta (dias_na_fase == 0) |
| `pos_entrega_andamento` | Entrega em execução (dias_na_fase >= 14) |
| `pos_entrega_conclusao` | Entrega com status `concluida` |
| `reativacao` | Conta inativa sem follow-up há > 60 dias |

---

## Score de Saúde

Determinístico e auditável. Base de 60 pontos.

| Condição | Ajuste |
|---|---|
| Entrega concluída | +15 (máx +25) |
| Entrega em execução | +5 |
| Entrega bloqueada | -10 por item (máx -20) |
| Proposta aceita (conta tem `proposta_aceita`) | +10 |
| Flag `risco_relacionamento=True` | -25 |
| Satisfação `alta` (último acomp.) | +15 |
| Satisfação `baixa` | -20 |
| NPS ≥ 8 | +10 |
| NPS ≤ 5 | -15 |
| Sem follow-up há > 90 dias | -10 |
| Follow-up recente (< 14 dias) | +5 |
| Score final | clamp(0, 100) |

### Classificação

| Score | Status |
|---|---|
| ≥ 80 | `excelente` |
| ≥ 60 | `boa` |
| ≥ 40 | `atencao` |
| < 40 | `critica` |

---

## Sinais de Expansão

Conservadores — apenas casos com alta probabilidade de conversão.

| Tipo | Critério |
|---|---|
| `cross_sell_marketing` | Cliente ativo com automação, sem marketing; score ≥ 60 |
| `cross_sell_automacao` | Cliente ativo com marketing, sem automação; score ≥ 60 |
| `renovacao` | Entrega concluída há > 60 dias, sem outra entrega aberta |
| `reativacao` | Status inativo/perdido, score ≥ 55 |
| `upsell` | Score ≥ 75, apenas 1 serviço, entrega concluída |

---

## Ciclo de Vida de uma Expansão

```
sugerida → pronta_para_handoff → convertida_em_oportunidade
```

- `sugerida`: criada automaticamente por `agente_operacao_entrega`
- `pronta_para_handoff`: promovida via painel `/acompanhamento` (ação do conselho)
- `convertida_em_oportunidade`: processada por `agente_comercial` → nova opp em `pipeline_comercial.json`

---

## Integração com Agentes

### `agente_operacao_entrega` (ETAPA 3c)
- Chama `processar_acompanhamentos_entrega(pipeline_entrega, origem)`
- Para cada entrega elegível:
  1. Cria acompanhamento em `acompanhamentos_contas.json`
  2. Recalcula saúde → salva em `saude_contas.json`
  3. Enriquece registro em `contas_clientes.json` com `score_saude`, `status_saude`, `potencial_expansao`, `cliente_em_risco`
  4. Sugere expansão se sinais presentes → salva em `oportunidades_expansao.json`

### `agente_comercial` (ETAPA 3d)
- Chama `processar_expansoes_para_handoff(pipeline, origem)`
- Para cada expansão com `status=pronta_para_handoff`:
  1. Cria nova oportunidade no pipeline comercial
  2. Marca expansão como `convertida_em_oportunidade`

---

## Arquivos de Dados

| Arquivo | Conteúdo |
|---|---|
| `dados/acompanhamentos_contas.json` | Registros de follow-up por conta |
| `dados/saude_contas.json` | Score e status de saúde por conta |
| `dados/oportunidades_expansao.json` | Expansões sugeridas/promovidas/convertidas |
| `dados/historico_acompanhamento_contas.json` | Log de eventos de acompanhamento |

---

## Painel `/acompanhamento`

KPIs visíveis:
- Acompanhamentos abertos
- Contas em risco (atenção/crítica)
- Contas com potencial de expansão
- Expansões sugeridas / prontas para handoff / convertidas

Ações disponíveis:
- Registrar satisfação (alta/média/baixa) em acompanhamentos sem avaliação
- Promover expansão para `pronta_para_handoff` (botão por item)
- Filtrar por saúde da conta ou busca por nome

---

## Observabilidade

`core/observabilidade_empresa.py` expõe via `_metricas_acompanhamento()`:
- `acompanhamentos_abertos`
- `contas_em_risco_acomp`
- `contas_com_potencial_expansao`
- `oportunidades_expansao_sugeridas`
- `oportunidades_expansao_convertidas`

`core/orquestrador_empresa.py` inclui no resumo do ciclo:
- `acompanhamentos_abertos`
- `expansoes_sugeridas_no_ciclo`
- `expansoes_convertidas_no_ciclo`

---

## Decisão de Projeto

Toda a lógica de saúde e expansão é **best-effort**: erros não bloqueiam o ciclo operacional.
A regra de custo inicial é mantida: nenhuma API externa paga é usada nesta camada.
