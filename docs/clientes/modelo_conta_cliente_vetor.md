# Modelo de Conta/Cliente — Vetor Operações

## Conceito

Cada empresa atendida tem um registro mestre único (`conta_id`).
Leads, oportunidades, propostas, entregas e financeiro apontam para esse registro.

---

## Ciclo de vida do status_relacionamento

| Status | Condição |
|---|---|
| `lead` | Empresa identificada, sem oportunidade ativa |
| `oportunidade` | Oportunidade no pipeline comercial |
| `cliente_ativo` | Proposta aceita ou entrega aberta |
| `cliente_em_implantacao` | Entrega em execução (onboarding / em_execucao) |
| `cliente_recorrente` | Mais de um contrato/entrega concluído |
| `cliente_inativo` | Entrega concluída, sem atividade futura |
| `perdido` | Proposta recusada ou oportunidade encerrada sem sucesso |

## Fases (fase_atual)

`descoberta` → `comercial` → `proposta` → `fechamento` → `onboarding` → `entrega` → `acompanhamento` → `encerrado`

---

## Matching de duplicatas (conservador)

Prioridade para encontrar conta existente:

1. `email_principal` — exato, case-insensitive
2. `instagram` — exato, sem `@`
3. `site` — exato, sem `http://`, sem trailing `/`
4. `telefone_principal` / `whatsapp` — somente dígitos, mínimo 8 caracteres
5. `nome_normalizado` — após remoção de sufixos (ltda, me, eireli, s.a., epp, mei)

Se houver ambiguidade (dois critérios apontando para contas diferentes), **não funde automaticamente**.

---

## Estrutura do objeto conta

```json
{
  "id": "conta_xxxxxxxx",
  "nome_empresa": "Padaria do João",
  "nome_normalizado": "padaria joao",
  "site": "padarijoao.com.br",
  "instagram": "padaria_joao",
  "email_principal": "joao@padaria.com.br",
  "telefone_principal": "11987654321",
  "whatsapp": "11987654321",
  "cidade": "São Paulo",
  "categoria": "alimentacao",
  "origem_inicial": "prospecção_marketing",
  "status_relacionamento": "cliente_ativo",
  "fase_atual": "entrega",
  "oportunidade_ativa": true,
  "cliente_ativo": true,
  "risco_relacionamento": false,
  "valor_total_propostas": 4800.0,
  "valor_total_fechado": 4800.0,
  "entregas_ativas": 1,
  "oportunidade_ids": ["opp_abc123"],
  "proposta_ids": ["prop_def456"],
  "entrega_ids": ["ent_ghi789"],
  "tags": [],
  "observacoes": "",
  "criado_em": "2026-01-10T14:30:00",
  "atualizado_em": "2026-03-24T09:00:00"
}
```

---

## Eventos de jornada (jornada_contas.json)

| tipo_evento | Quando ocorre |
|---|---|
| `conta_criada` | Primeira vez que a empresa aparece no sistema |
| `oportunidade_associada` | Opp vinculada à conta |
| `proposta_gerada` | Proposta formal criada |
| `proposta_aceita` | Cliente aceitou proposta |
| `entrega_aberta` | Entrega iniciada |
| `entrega_bloqueada` | Entrega travada por insumo ou deliberação |
| `entrega_concluida` | Entrega finalizada |
| `evento_financeiro_associado` | Recebimento ou evento financeiro vinculado |
| `conta_marcada_como_cliente` | Status promovido para cliente_ativo |
| `conta_marcada_como_perdida` | Oportunidade encerrada sem sucesso |

---

## Integração por módulo

| Módulo | Ação |
|---|---|
| `agente_comercial` | Cria/encontra conta ao importar nova oportunidade |
| `agente_operacao_entrega` | Vincula entrega à conta ao abrir delivery |
| `agente_financeiro` | Associa contas_a_receber por contraparte (best-effort) |
| `processador_entrada_manual` | Cria/encontra conta com status inicial `cliente_ativo` |
| `expediente_propostas` | Proposta aceita promove conta via `marcar_proposta_aceita_na_conta` |

---

## Regras de não-overengineering

- Sem multi-contato por empresa (versão atual)
- Sem hierarquia matriz/filial
- Sem contratos complexos
- Sem CRM completo
- Dados locais em JSON — sem banco de dados
