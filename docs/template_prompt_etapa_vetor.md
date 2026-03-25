# Template de Prompt — Próxima Etapa Vetor

> Copiar e preencher. Não reexplicar o sistema.
> O Claude deve ler `docs/contexto_mestre_vetor.md` como referência base.

---

```
Seguir contexto mestre da Vetor no repo.

Objetivo:
[1 frase direta — o que esta etapa entrega]

Escopo:
- [o que está dentro]
- [o que está dentro]
- [o que NÃO está incluído, se relevante]

Arquivos:
- criar:   [arquivo novo]
- alterar: [arquivo existente]
- reutilizar: [dado/módulo já existente]

Regras:
- [restrição técnica ou de produto]
- [restrição de custo/integração externa se aplicável]

Validação:
- [teste 1: o que deve ser verificável após a execução]
- [teste 2]

Entrega:
- resumo curtíssimo
- arquivos criados/alterados
- lógica em 5 linhas
- antes/depois
- próximo gargalo principal
```

---

## Exemplo preenchido

```
Seguir contexto mestre da Vetor no repo.

Objetivo:
Criar camada de envio assistido de proposta por email a partir do documento HTML gerado.

Escopo:
- Gerar rascunho de email com link/conteúdo da proposta
- Registrar envio em historico_documentos_oficiais.json
- Sem envio real automático — modo assistido (conselho aprova antes)

Arquivos:
- criar:   core/envio_documentos.py
- alterar: conselho_app/app.py (rota /documentos/enviar)
- reutilizar: dados/documentos_oficiais.json, core/integrador_email.py

Regras:
- Sem SMTP real nesta etapa
- Idempotente: não gerar rascunho duplicado para o mesmo documento_id
- Best-effort: falha de canal não bloqueia o sistema

Validação:
- 1 proposta gera rascunho de email com assunto e corpo corretos
- Rascunho registrado em historico_documentos_oficiais.json com evento=email_preparado

Entrega:
- resumo curtíssimo
- arquivos criados/alterados
- lógica em 5 linhas
- antes/depois
- próximo gargalo principal
```
