# Lacunas e Próximas Camadas

## Lacunas estruturais (precisam ser criadas)

| Arquivo | Descrição | Quem precisa |
|---|---|---|
| `dados/pipeline_comercial.json` | Negociações em aberto por estágio | agente_comercial |
| `dados/fila_candidatos.json` | Formato formalizado de candidatos qualificados | agente_prospeccao, agente_comercial |
| `dados/historico_abordagens.json` | Registro de contatos realizados por candidato | agente_comercial |
| `dados/fila_decisoes_consolidada.json` | Todas as decisões de todos os agentes em um lugar | agente_secretario |
| `dados/agenda_do_dia.json` | Agenda priorizada para o usuário | agente_secretario |
| `dados/templates_plano_marketing/` | Templates de plano por setor | agente_marketing |
| `dados/propostas_marketing/` | Propostas de marketing por cliente | agente_marketing |

---

## Lacunas operacionais (faltam para os agentes serem úteis de verdade)

### Aprovação formal do usuário
Hoje não existe mecanismo para registrar "aprovei" ou "rejeitei" um item da fila.
Solução mínima: arquivo `dados/aprovacoes.json` com `{item_id, decisao, data, observacao}`.

### Estado persistente entre execuções
Agentes hoje não sabem o que processaram na última rodada. Sem isso, reprocessam tudo a cada execução.
Solução mínima: arquivo `dados/estado_{agente}.json` com IDs já processados.

### Histórico de execução por agente
Não há registro do que cada agente fez, quando e com qual resultado.
Necessário para auditoria, depuração e rastreabilidade.

### Trigger de execução
Não há scheduler. Cada módulo é rodado manualmente.
Solução mínima: script de orquestração sequencial com logs por etapa.

### Auditoria de decisões
Quando o usuário aprova algo, não fica registrado onde nem quando.
Solução mínima: campo `aprovado_em` e `aprovado_por` em cada item da fila de decisões.

---

## Próximas camadas futuras

### agente_operacao_entrega *(não implementar agora)*

**Objetivo:** executar o que foi vendido — implantar os agentes nos clientes, acompanhar a entrega, registrar o progresso.

**Papel futuro:**
- Receber proposta assinada do agente_comercial
- Montar plano de implantação por cliente
- Acompanhar marcos de entrega
- Registrar o que foi entregue e quando
- Sinalizar bloqueios e desvios de prazo
- Gerar relatório de progresso por cliente

**Por que não agora:** ainda não há clientes em produção. O padrão de entrega ainda está sendo definido. Implementar depois que os primeiros clientes forem ativos.

**Escala para o usuário quando:**
- Entrega atrasada sem solução técnica clara
- Cliente insatisfeito ou solicitando mudança de escopo
- Bloqueio técnico que exige decisão de produto

---

## Resumo das lacunas por prioridade

| Prioridade | Lacuna |
|---|---|
| Alta | Aprovação formal do usuário (sem isso, nenhum agente pode agir com segurança) |
| Alta | Estado persistente entre execuções (sem isso, agentes reprocessam tudo) |
| Media | Trigger de execução (hoje tudo é manual) |
| Media | Pipeline comercial estruturado |
| Baixa | Auditoria completa de decisões |
| Futura | agente_operacao_entrega |
