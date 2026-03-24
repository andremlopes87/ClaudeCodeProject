# Contratos e Faturamento — Vetor

## Objetivo

Transformar uma proposta aceita em receita formal e rastreável, ligando comercial, entrega e financeiro pela mesma trilha.

---

## Módulo

`core/contratos_empresa.py`

---

## Fluxo

```
proposta aceita
  → contrato (compromisso comercial)
  → plano de faturamento (parcelas/recorrências)
  → contas a receber (rastreadas no financeiro)
  → previsão de caixa reflete vendas reais
```

---

## Objeto Contrato (`contratos_clientes.json`)

| Campo | Descrição |
|---|---|
| `id` | Identificador único (`ct_xxxxxxxx`) |
| `conta_id` | Vínculo com a conta mestra |
| `proposta_id` | Proposta que originou |
| `contraparte` | Nome do cliente |
| `oferta_id/nome` | Oferta contratada |
| `linha_servico` | Linha de serviço |
| `valor_total` | Valor comercial fechado |
| `modelo_cobranca` | `avulso` / `parcela_fixa` / `recorrente_mensal` / `recorrente_trimestral` |
| `numero_parcelas` | Quantidade de parcelas/recorrências |
| `data_inicio` | Data de início do contrato |
| `data_primeiro_vencimento` | Primeiro vencimento (30 dias após início) |
| `status` | `rascunho` / `aguardando_ativacao` / `ativo` / `concluido` / `pausado` / `cancelado` |

### Inferência de modelo de cobrança

| Critério | Modelo inferido |
|---|---|
| `linha_servico` contém gestao/recorrente/suporte | `recorrente_mensal` |
| Implantação + valor >= R$ 3.000 | `parcela_fixa` |
| Demais casos | `avulso` |

---

## Plano de Faturamento (`planos_faturamento.json`)

Gerado automaticamente junto com o contrato.

- 1 plano por contrato
- Parcelas calculadas por periodicidade (`mensal`, `unico`, `trimestral`)
- Cada parcela tem: número, descrição, valor, vencimento, status, conta_receber_id

### Status do plano

`planejado` → `parcialmente_gerado` → `totalmente_gerado` → `em_recebimento` → `concluido`

### Status da parcela

`planejada` → `gerada_no_financeiro` → `recebida`

---

## Contas a Receber de Contratos

Geradas automaticamente pelo `agente_financeiro` (ETAPA 8c).

Campos de rastreabilidade adicionados:
- `contrato_id`
- `proposta_id`
- `conta_id`
- `plano_faturamento_id`
- `parcela_id`
- `origem_recebivel = "contrato_vetor"`
- `descricao_origem`

### Regras de deduplicação

1. Não gera contrato se já existe para a proposta (salvo cancelado)
2. Não gera plano se contrato já tem plano ativo
3. Não gera conta a receber se parcela já tem `conta_receber_id`
4. Se contrato cancelado: não gera recebíveis futuros

---

## Integração por Agente

### `agente_comercial` (ETAPA 8c)
- Após gerar propostas e aplicar respostas, chama `processar_contratos_pendentes()`
- Itera propostas com `status=aceita` ou `aceita_em` preenchido
- Gera contrato + plano de faturamento automaticamente
- Registra em `contratos_gerados` e `planos_gerados` no resumo

### `agente_financeiro` (ETAPA 8c)
- Após associar contas, chama `gerar_recebiveis_pendentes()`
- Para cada plano `planejado` ou `parcialmente_gerado`, gera contas a receber faltantes
- Chama `enriquecer_contas_com_contratos()` para atualizar `faturamento_previsto` e `ultimo_vencimento_previsto` em cada conta

### `core/contas_empresa.py`
- Conta enriquecida com: `contratos_ativos`, `valor_total_fechado`, `faturamento_previsto`, `ultimo_vencimento_previsto`

---

## Arquivos de Dados

| Arquivo | Conteúdo |
|---|---|
| `dados/contratos_clientes.json` | Contratos comerciais formais |
| `dados/planos_faturamento.json` | Planos com parcelas por contrato |
| `dados/historico_contratos.json` | Log de eventos por contrato |

---

## Painel `/contratos`

KPIs:
- Contratos ativos
- Valor total fechado (ativos)
- Faturamento previsto nos próximos 30 dias
- Recebíveis abertos originados de contratos
- Contratos sem plano de faturamento

Ações:
- Filtrar por status (ativo/pausado/cancelado/aguardando)
- Buscar por conta ou oferta
- Drill-down: contrato + plano + parcelas + recebíveis + histórico

Alertas:
- Contratos sem plano
- Planos com inconsistência (planejado há >1 dia sem recebíveis)

---

## Observabilidade

`core/observabilidade_empresa.py` expõe via `_metricas_contratos()`:
- `total_contratos_ativos`
- `valor_fechado_total`
- `faturamento_previsto_30d`
- `recebiveis_contrato_abertos`
- `contratos_sem_plano`
- `planos_com_inconsistencia`

---

## Lógica Final (5 linhas)

Proposta aceita → `agente_comercial` detecta e chama `processar_contratos_pendentes()`, que gera o contrato com modelo de cobrança inferido pela linha de serviço e o plano de faturamento com parcelas calculadas. No ciclo seguinte, `agente_financeiro` converte cada parcela `planejada` em conta a receber no módulo financeiro existente, adicionando campos de rastreabilidade (contrato_id, proposta_id, conta_id). As contas da Vetor são então enriquecidas com `faturamento_previsto` e o painel `/contratos` reflete a posição completa. Tudo é idempotente: nenhum duplo contrato, nenhum duplo recebível.

---

## Decisões de Projeto

- Sem assinatura jurídica, sem NF-e, sem ERP
- Contrato = compromisso comercial estruturado, não documento legal
- Modelo conservador: só gera com proposta aceita E valor > 0
- Janela de recorrente: 3 parcelas antecipadas (configurável via `_JANELA_RECORRENTE`)
- Erros são logados mas não bloqueiam o ciclo operacional
