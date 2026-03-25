# Modelo: Resumo de Entrega / Onboarding Vetor

## Estrutura do documento gerado

Gerado por `core/documentos_empresa.py` a partir de `dados/pipeline_entrega.json`,
enriquecido com proposta e contrato vinculados via oportunidade_id.

### Seções

1. **Cabeçalho** — nome da empresa, oferta, cliente, data de abertura, ref., etapa, prioridade
2. **Objetivo da entrega** — escopo da proposta/contrato vinculado
3. **Entregáveis** — lista da proposta vinculada
4. **Premissas e insumos esperados** — o que a Vetor precisa do cliente
5. **Checklist de execução** — atividades a executar
6. **Bloqueios ativos** — se houver, lista os bloqueios registrados
7. **Status atual** — progresso (%) e etapa corrente
8. **Próxima etapa** — orientação padrão para avanço
9. **Rodapé** — assinatura institucional da Vetor

### Campos utilizados

**pipeline_entrega.json:**
- contraparte, cidade, linha_servico, tipo_entrega, etapa_atual, prioridade
- status_entrega, percentual_conclusao, bloqueios, checklist
- registrado_em (data de abertura)

**propostas_comerciais.json** (via oportunidade_id → proposta aceita):
- escopo, entregaveis, premissas, checklist_execucao, oferta_nome

**contratos_clientes.json** (via oportunidade_id):
- escopo_resumido (fallback se proposta não encontrada)

### Quando é gerado

- Automaticamente na ETAPA 3e do `agente_operacao_entrega.py`
- Via batch `processar_documentos_pendentes()` para entregas: `onboarding`, `em_execucao`, `em_andamento`, `aguardando_insumo`, `concluida`

### Nome de arquivo

`onboarding_{entrega_id}_v{versao}.html`
