# Mapa de Interação entre Agentes

## Fluxo principal

```
[entrada manual / fontes públicas]
           |
           v
  agente_prospeccao
  - qualifica candidatos
  - gera diagnóstico de presença digital
           |
           | fila_candidatos.json + diagnosticos/
           |
           +------------------+
           |                  |
           v                  v
  agente_comercial     agente_marketing
  - escolhe canal      - analisa presença digital
  - aborda mercado     - consolida oportunidade
  - conduz pipeline    - monta plano de marketing
  - prepara proposta   - prepara proposta de marketing
           |                  |
           | pipeline,        | propostas_marketing,
           | propostas,       | fila_decisoes_marketing
           | fila_decisoes    |
           |                  |
           +------------------+
           |
           | (eventos e contas gerados pelo comercial/operacao)
           v
  agente_financeiro
  - registra e classifica
  - calcula posição de caixa
  - projeta fluxo 7/30/60/90 dias
  - gera alertas e riscos
           |
           | posicao_caixa, previsao, alertas,
           | riscos, resumo, decisoes
           |
           v
  agente_secretario
  - consolida todas as filas
  - prioriza o dia
  - agrupa pendências
  - escala exceções
           |
           | agenda_do_dia, fila_decisoes_consolidada
           v
  usuario_conselho
  - aprova ou rejeita
  - dá direção
  - decide exceções
           |
           v
  [agentes executam a decisão aprovada]
```

---

## Regra de comunicação entre agentes

Os agentes **não se chamam diretamente**. Eles escrevem em filas JSON. O secretário lê as filas e coordena. O usuário lê a agenda e decide.

Nenhum agente pode executar ação sensível sem aprovação registrada no item da fila.

---

## O que cada agente já pode usar das saídas atuais do sistema

| Agente | Arquivos disponíveis hoje |
|---|---|
| agente_financeiro | `dados/eventos_financeiros.json`, `dados/contas_a_receber.json`, `dados/contas_a_pagar.json`, `dados/posicao_caixa.json`, `dados/previsao_caixa.json`, `dados/fila_alertas_financeiros.json`, `dados/fila_decisoes_financeiras.json`, `dados/fila_riscos_financeiros.json`, `dados/resumo_financeiro_operacional.json` |
| agente_prospeccao | `dados/diagnosticos/` (parcialmente — linha de prospecção existe, formato a formalizar) |
| agente_comercial | `dados/contas_a_receber.json` (clientes ativos) |
| agente_secretario | `dados/fila_alertas_financeiros.json`, `dados/fila_decisoes_financeiras.json`, `dados/resumo_financeiro_operacional.json` |
| agente_marketing | nenhuma saída direta ainda — depende do diagnóstico da prospeccao |

---

## Ordem de implementação

| Ordem | Agente | Motivo |
|---|---|---|
| 1 | agente_financeiro | backend completo, só precisa do wrapper de agente |
| 2 | agente_prospeccao | linha de prospecção existe, formato de fila a formalizar |
| 3 | agente_comercial | depende de candidatos qualificados + pipeline a criar |
| 4 | agente_marketing | depende de diagnóstico + candidatos qualificados |
| 5 | agente_secretario | depende de todos os outros produzindo filas |
| 6 | painel agenda | interface para o usuário ver e aprovar decisões |
