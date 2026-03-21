# usuario_conselho

## Papel

Instância final de decisão. Não opera o dia a dia — aprova, rejeita e dá direção quando os agentes escalarem.

O usuário recebe a agenda consolidada pelo secretário e decide sobre exceções, ações sensíveis e mudanças de rumo. Os agentes executam o que for aprovado.

---

## O que lê

- `dados/agenda_do_dia.json` — prioridades do dia, geradas pelo secretário
- `dados/fila_decisoes_consolidada.json` — todas as decisões pendentes com contexto
- `dados/relatorio_semanal.json` — visão da semana por área

---

## O que aprova

- Envio de mensagens ao mercado (abordagens, follow-ups, propostas)
- Propostas comerciais acima do threshold
- Ações financeiras reais: cobrança, pagamento, renegociação
- Mudanças de escopo de serviço
- Mudanças de critério de prospecção
- Descarte definitivo de candidato
- Ações sensíveis de qualquer agente
- Decisões de direção e estratégia

---

## O que não precisa aprovar

- Classificação e priorização interna dos agentes
- Cálculos, previsões e alertas
- Avanço de pipeline por critério objetivo (sem ação externa)
- Geração de rascunhos e diagnósticos

---

## Regra principal

O usuário é o conselho — decide exceções e direção.
Não é o operador diário. Se um item precisa de aprovação a cada rodada normal, é sinal de que o critério deve ser automatizado ou o agente reconfigurado.
