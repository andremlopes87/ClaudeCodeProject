# Modelo: Proposta Comercial Vetor

## Estrutura do documento gerado

O documento é gerado em HTML por `core/documentos_empresa.py` a partir de `dados/propostas_comerciais.json`.

### Seções

1. **Cabeçalho** — nome da empresa, oferta, contraparte, data, referência, versão
2. **Contexto identificado** — problema identificado na análise da empresa-cliente
3. **Nossa proposta** — escopo da entrega
4. **Entregáveis** — lista dos itens entregues
5. **Premissas de execução** — o que a Vetor precisa do cliente
6. **Fora do escopo** — o que não está incluído
7. **Investimento** — valor total e prazo de referência
8. **Próximos passos** — orientação para aceite
9. **Rodapé** — assinatura institucional da Vetor

### Campos utilizados (propostas_comerciais.json)

| Campo | Uso |
|---|---|
| contraparte | Identificação do cliente |
| cidade, categoria | Metadados do cliente |
| oferta_nome, pacote_nome | Título do documento |
| resumo_problema | Seção de contexto |
| escopo | Nossa proposta |
| entregaveis | Lista de entregáveis |
| premissas | Premissas de execução |
| fora_do_escopo | Fora do escopo |
| proposta_valor | Valor de investimento |
| prazo_referencia | Prazo em dias úteis |
| versao | Versão do documento |
| gerada_em | Data de emissão |

### Quando é gerado

- Automaticamente ao chamar `aprovar_proposta()` em `core/propostas_empresa.py`
- Via batch `processar_documentos_pendentes()` para propostas nos status: `aprovada_para_envio`, `enviada`, `aceita`

### Nome de arquivo

`proposta_{proposta_id}_v{versao}.html`
