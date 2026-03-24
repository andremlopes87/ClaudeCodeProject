# Reconciliação do Ciclo de Contratos (v0.49)

## Objetivo

Fechar o ciclo de vida dos contratos correlacionando:
- Status de entrega (agente_operacao_entrega)
- Status de recebimento (contas_a_receber)
- Previsão de caixa (conservador vs expandido)
- Enriquecimento de contas

## Arquivo principal

`modulos/financeiro/reconciliador_contratos_faturamento.py`

## Fluxo de reconciliação

Executado em ordem por `executar_reconciliacao()`:

### A — Reconciliar parcelas com recebíveis

Para cada parcela de cada plano de faturamento, verifica o status da conta a receber vinculada:

| Status conta_a_receber | Status parcela resultante |
|---|---|
| recebida | recebida |
| aberta / parcial (no prazo) | gerada_no_financeiro |
| aberta / parcial (vencida) | vencida |
| vencida | vencida |
| cancelada | cancelada |
| (sem conta_receber_id) | planejada ou vencida se prazo passou |

Status nunca regride: parcela `recebida` ou `cancelada` não é alterada.

### B — Atualizar status do plano

Com base nas parcelas reconciliadas:

| Condição | Status plano |
|---|---|
| Todas recebidas | concluido |
| Alguma recebida ou gerada | em_recebimento |
| Todas geradas (nenhuma recebida) | totalmente_gerado |
| Alguma planejada (sem todas geradas) | parcialmente_gerado |
| Nenhuma parcela | planejado |

### C — Atualizar status do contrato

Cruza status operacional (entrega) com status financeiro (plano):

**Status operacional** (via pipeline_entrega):
- `concluida` → concluido
- `aguardando_insumo` → bloqueado
- `onboarding / em_execucao` → ativo
- (sem entrega) → sem_entrega

**Status financeiro** (via plano):
- plano concluido → concluido
- plano em_recebimento → em_cobranca
- plano totalmente_gerado → em_cobranca
- plano parcialmente_gerado → em_faturamento
- plano planejado → em_faturamento
- (sem plano) → sem_plano

**Status final do contrato**:
- Ambos concluido → concluido
- Recorrente: fin=concluido + op=ativo → ativo (renovação esperada)
- op=bloqueado → pausado
- Qualquer outro → ativo

### D — Enriquecer contas

Atualiza `contas_clientes.json` com:
- `faturamento_previsto` (soma de parcelas não recebidas)
- `faturamento_recebido` (soma do valor recebido confirmado)
- `contratos_ativos` (lista de IDs)
- `contratos_concluidos` (lista de IDs)
- `ultimo_vencimento_previsto`
- `ultimo_recebimento_confirmado`

### E — Enriquecer previsão de caixa

Adiciona ao `previsao_caixa.json`:

```json
{
  "total_previsto_conservador": 4400.0,
  "total_previsto_expandido": 5860.0,
  "entradas_planejadas_contratos_por_janela": {
    "7_dias": 0.0,
    "30_dias": 1460.0,
    "60_dias": 1460.0,
    "90_dias": 1460.0
  }
}
```

- **Conservador**: apenas recebiveis já gerados no financeiro (em contas_a_receber)
- **Expandido**: conservador + parcelas ainda em status "planejada" (futuras, mais incertas)

## Link entrega → contrato

Disparado por `atualizar_contrato_por_entrega()` no agente_operacao_entrega (ETAPA 3d).

Busca o contrato por três níveis de fallback:
1. `oportunidade_id` (preciso)
2. `conta_id` (por conta)
3. `contraparte` nome (texto, fallback)

## Arquivos de dados

| Arquivo | Uso |
|---|---|
| `dados/contratos_clientes.json` | Status operacional e financeiro dos contratos |
| `dados/planos_faturamento.json` | Status dos planos e resumo de valores |
| `dados/historico_reconciliacao_contratos.json` | Log de todos os eventos de reconciliação |
| `dados/previsao_caixa.json` | Enriquecido com conservador/expandido |

## Integração nos agentes

- `agente_financeiro.py` — ETAPA 8d: executa `executar_reconciliacao()` a cada ciclo
- `agente_operacao_entrega.py` — ETAPA 3d: atualiza contrato a cada mudança de entrega

## Painel /contratos

Exibe:
- Resumo: contratos ativos/concluídos, planos em recebimento, parcelas vencidas, inconsistências
- Tabela com status_operacional, status_financeiro, percentual_recebido

## Painel /financeiro

Exibe:
- Card "Previsão: Contratos" com leituras conservadora e expandida
- Tabela de recebíveis de contratos em aberto
- Alerta se há parcelas vencidas ou inconsistências
