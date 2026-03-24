# Runbook — Ativação do Canal Email Real

**Versão:** v0.42
**Data:** 2026-03-23
**Empresa:** Vetor Operações Ltda
**Domínio planejado:** vetorai.com.br

---

## Pré-requisitos antes de começar

- [ ] Ter acesso ao painel do conselho rodando localmente
- [ ] Ter acesso ao registrador de domínio (registro.br recomendado)
- [ ] Ter acesso ao provedor de email escolhido (Zoho Mail, Google Workspace, etc.)
- [ ] Nunca colocar credenciais SMTP no repositório

---

## O que preencher no sistema (arquivos locais)

### 1. `dados/provisionamento_email_real.json`

Após cada etapa externa, atualizar os campos correspondentes:

```json
{
  "provedor_email_planejado": "Zoho Mail",
  "smtp_host_planejado":      "smtp.zoho.com",
  "smtp_porta_planejada":     587,
  "smtp_usuario_planejado":   "comercial@vetorai.com.br",
  "dominio_registrado":       true,    // após registrar no registro.br
  "dns_configurado":          true,    // após nameservers apontarem
  "mx_configurado":           true,    // após MX records configurados
  "spf_configurado":          true,    // após TXT SPF adicionado
  "dkim_configurado":         true,    // após DKIM gerado e adicionado
  "dmarc_configurado":        false,   // opcional — pode deixar false no início
  "smtp_validado":            true,    // após testar conexão SMTP
  "remetente_validado":       true,    // após testar envio básico
  "whitelist_teste_definida": true     // após definir lista de teste
}
```

### 2. `dados/checklist_ativacao_email.json`

Para cada item, atualizar `status` para `"concluido"` e adicionar `"observacoes"`:

```json
{
  "id": "dominio_registrado",
  "status": "concluido",
  "observacoes": "Registrado em registro.br em 2026-xx-xx",
  "atualizado_em": "2026-xx-xx"
}
```

### 3. `dados/config_canal_email.json`

Após configurar o email real:

```json
{
  "email_remetente_planejado": "comercial@vetorai.com.br",
  "nome_remetente":            "Equipe Vetor",
  "responder_para_planejado":  "comercial@vetorai.com.br",
  "whitelist_emails_teste":    ["seu@email.pessoal.com"],
  "modo":                      "assistido"   // MANTER assistido até validar
}
```

---

## O que configurar fora do sistema

### Registro de domínio (registro.br)

1. Criar conta em registro.br
2. Registrar `vetorai.com.br`
3. Apontar nameservers para o provedor de email ou zona DNS separada
4. Aguardar propagação (2-48h)

### Zoho Mail (opção gratuita até 5 usuários)

1. Acessar mail.zoho.com → criar conta com domínio próprio
2. Verificar domínio adicionando registro TXT no DNS
3. Configurar MX records conforme instruções do Zoho
4. Adicionar SPF: `v=spf1 include:zoho.com ~all`
5. Gerar DKIM pelo painel Zoho → adicionar ao DNS
6. Criar caixas: contato@, comercial@, financeiro@, operacoes@
7. Anotar configurações SMTP:
   - Host: `smtp.zoho.com`
   - Porta: 587 (TLS) ou 465 (SSL)
   - Usuário: endereço de email completo
   - Senha: senha de aplicativo (não a senha principal)

### Variáveis de ambiente (NUNCA no repo)

Definir no ambiente de execução:

```bash
export SMTP_HOST=smtp.zoho.com
export SMTP_PORTA=587
export SMTP_USUARIO=comercial@vetorai.com.br
export SMTP_SENHA=senha_de_aplicativo_aqui
export SMTP_REMETENTE="Equipe Vetor <comercial@vetorai.com.br>"
```

---

## Validações antes de ativar modo=real

O sistema valida automaticamente via `core/provisionamento_canais.py`.
Execute antes de alterar `modo=real`:

```python
from core.provisionamento_canais import avaliar_prontidao_modo_real
resultado = avaliar_prontidao_modo_real()
print(resultado['apto'])      # deve ser True
print(resultado['bloqueios']) # deve ser []
```

Ou acesse `/ativacao-email` no painel e confira:
- Todos os itens obrigatórios do checklist = `concluido`
- Todos os campos DNS/SMTP = `true`
- `pronto_para_modo_real = TRUE`

---

## Ativar modo=real com segurança

Só alterar após todos os checks verdes:

```json
// dados/config_canal_email.json
{
  "modo": "real",
  "habilitado": true,
  "whitelist_emails_teste": ["seu@email.pessoal.com"],
  "modo_restrito_whitelist": true   // força envio apenas para whitelist no primeiro ciclo
}
```

**O integrador verificará automaticamente.** Se `pronto_para_modo_real=false`, reverterá para `assistido` e registrará o evento.

---

## Rollback simples se der problema

Alterar de volta em `config_canal_email.json`:

```json
{ "modo": "assistido" }
```

Isso é suficiente — sem migrations, sem serviços para reiniciar.
O histórico do integrador registra a reversão automaticamente.

---

## Primeira rodada segura de envio

1. Definir `whitelist_emails_teste` com seu email pessoal
2. Deixar `modo_restrito_whitelist=true`
3. Criar 1 execução de teste com `canal=email` e destino = seu email
4. Rodar ciclo: `python main_empresa.py`
5. Verificar:
   - Email chegou na caixa de entrada (não spam)
   - Cabeçalhos mostram SPF/DKIM aprovados
   - Conteúdo correto (assunto, corpo, assinatura)
6. Se tudo OK: remover `modo_restrito_whitelist` ou definir `false`
7. Iniciar operação normal

---

## Referências

| Arquivo | Descrição |
|---------|-----------|
| `dados/provisionamento_email_real.json` | Status DNS/SMTP — atualizar externamente |
| `dados/checklist_ativacao_email.json` | Checklist auditável de pré-requisitos |
| `dados/historico_provisionamento_email.json` | Log de eventos de ativação |
| `dados/config_canal_email.json` | Configuração do canal (modo, remetente, etc.) |
| `core/provisionamento_canais.py` | Lógica de validação de prontidão |
| `core/integrador_email.py` | Guard automático contra modo=real sem pré-requisitos |

*Runbook gerado em 2026-03-23 — atualizar ao completar cada etapa*
