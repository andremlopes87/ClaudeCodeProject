# Modelo: Compromisso Comercial Vetor

## Estrutura do documento gerado

Gerado por `core/documentos_empresa.py` a partir de `dados/contratos_clientes.json`,
enriquecido com dados da proposta, conta e plano de faturamento.

### Seções

1. **Cabeçalho** — nome da empresa, oferta/pacote, cliente, data, referência do contrato
2. **Identificação das partes** — prestador (Vetor) e cliente (conta)
3. **Objeto** — escopo resumido do contrato/proposta
4. **Entregáveis** — lista da proposta vinculada
5. **Premissas operacionais** — condições para execução
6. **Fora do escopo** — limitações acordadas
7. **Modelo financeiro** — valor total, modelo de cobrança, tabela de parcelas
8. **Vigência** — data de início e observações
9. **Rodapé** — assinatura institucional da Vetor

### Campos utilizados

**contratos_clientes.json:**
- contraparte, oferta_nome, pacote_nome, valor_total
- modelo_cobranca, numero_parcelas, periodicidade
- data_inicio, data_primeiro_vencimento, escopo_resumido, observacoes

**propostas_comerciais.json** (via proposta_id):
- escopo, entregaveis, premissas, fora_do_escopo

**contas_clientes.json** (via conta_id):
- nome_empresa, cidade, email_comercial

**planos_faturamento.json** (via contrato_id):
- parcelas (numero, valor, vencimento, status)

### Quando é gerado

- Automaticamente ao criar contrato via `gerar_contrato_de_proposta()`
- Via batch `processar_documentos_pendentes()` para contratos: `aguardando_ativacao`, `ativo`, `concluido`

### Nome de arquivo

`contrato_{contrato_id}_v{versao}.html`
