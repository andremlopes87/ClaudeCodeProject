# Fundação Institucional Mínima — Vetor Operações

**Versão:** v0.41
**Data:** 2026-03-23
**Status:** Fundação definida — pronta para configurar canal email real

---

## 1. Decisão de Nome

### Processo
Foram avaliados 20 candidatos com os critérios:
- Curto (máx. 3 sílabas preferencialmente)
- Fácil de escrever e pronunciar no Brasil
- Sem colidência forte com marcas conhecidas
- Não amarrado a uma área de serviço só
- Soa sério, útil, operacional
- Acomoda crescimento futuro

### Finalistas

| Nome | Por que funciona | Risco |
|------|-----------------|-------|
| **Vetor** ⭐ | Direcional, operacional, 2 sílabas, sem colidência forte | Baixo |
| **Cerne** | Core/essência, raro como marca, sólido | Muito baixo |
| **Escala** | Comunica crescimento diretamente | Médio (genérico) |

### Recomendado: **Vetor**

**Nome oficial:** Vetor Operações Ltda
**Nome de exibição:** Vetor
**Domínio planejado:** vetorops.com.br

**Justificativa:** "Vetor" comunica direção e operação. Não amarra a empresa a marketing, financeiro ou atendimento isoladamente — cobre tudo. O sufixo "ai" no domínio é discreto (sem gritar "somos uma empresa de IA") e diferencia de "vetor" genérico.

**Troca posterior:** se desejar outro nome, basta atualizar `dados/identidade_empresa.json` campos `nome_oficial` e `nome_exibicao` via `/identidade` no painel. O campo `_naming_finalistas` mantém os alternativos para referência.

---

## 2. Identidade Institucional

**Descrição curta:**
> Operamos sua empresa com agentes de IA — do comercial ao financeiro.

**Descrição média:**
> A Vetor é uma plataforma de operações empresariais movida por agentes de IA em camadas. Ajuda pequenos e médios negócios a prospectar, vender, atender e gerir o financeiro sem precisar de grandes equipes. Cada área roda com agentes especializados, supervisionados por um conselho humano.

**Proposta de valor:**
> Operação completa por IA — para negócios que querem crescer sem crescer o time.

**Quem somos:**
> Somos uma empresa de operações empresariais operada por agentes de IA. Atuamos lado a lado com pequenos negócios para estruturar e automatizar as funções que mais consomem tempo: prospecção, comercial, atendimento e financeiro.

**O que fazemos:**
> Prospectamos clientes em potencial, preparamos abordagens, gerimos o pipeline comercial, automatizamos atendimentos e acompanhamos o financeiro — tudo com agentes especializados que trabalham 24h e reportam ao conselho.

**Para quem:**
> Pequenos e médios negócios locais: barbearias, restaurantes, clínicas, oficinas, padarias, salões.

**Como nos diferenciamos:**
> Não somos uma agência de marketing nem um software genérico. Somos uma operação completa por IA — cada função tem um agente dedicado, tudo integrado, auditável e supervisionado pelo dono do negócio.

**Linhas de serviço:**
- `marketing_presenca_digital`
- `automacao_atendimento`
- `gestao_comercial`
- `gestao_financeira`

---

## 3. Tom de Voz

| Campo | Valor |
|-------|-------|
| Tom | Claro, objetivo, consultivo, sem floreio |
| Formalidade | Médio |
| Postura comercial | Diagnóstica — problema antes de oferta |
| Postura consultiva | Escuta ativa, perguntas antes de proposta |
| Postura financeira | Transparente, firme, sem pressão |
| Abertura | Direto ao ponto — nunca elogios vazios |
| Fechamento | Ação clara — próximo passo concreto, sem pressão |

**Palavras que usa:** resultado, simples, prático, direto, operacional, concreto, claro, rápido, estruturado

**Palavras que evita:** incrível, revolucionário, disruptivo, inovador, transformação, soluções, ecossistema, sinergia, plataforma omnichannel

**Regra principal:** A Vetor fala como um sócio operacional pragmático. Nunca como agência criativa. Nunca como software enterprise.

---

## 4. Assinaturas Institucionais

Todas as assinaturas são neutras — sem dependência de nome pessoal do conselho.

```
Comercial:
  Equipe Vetor
  Comercial | Vetor Operações
  comercial@vetorops.com.br

Financeiro:
  Equipe Vetor
  Financeiro | Vetor Operações
  financeiro@vetorops.com.br

Institucional:
  Vetor Operações
  Operamos sua empresa com agentes de IA — do comercial ao financeiro.
  [site quando disponível]
```

---

## 5. Plano de Domínio e Emails

| Campo | Valor | Status |
|-------|-------|--------|
| Domínio | vetorops.com.br | Planejado — não registrado |
| Email principal | contato@vetorops.com.br | Planejado — não configurado |
| Email comercial | comercial@vetorops.com.br | Planejado — não configurado |
| Email financeiro | financeiro@vetorops.com.br | Planejado — não configurado |
| Email operações | operacoes@vetorops.com.br | Planejado — não configurado |
| Site | — | Não definido |
| Instagram | — | Não definido |
| WhatsApp | — | Não definido |

---

## 6. Status de Prontidão

**pronto_para_configurar_email_real = TRUE**

Critérios atendidos:
- [x] Nome definido
- [x] Domínio planejado
- [x] Emails planejados
- [x] Assinatura definida
- [x] Guia de comunicação definido

Pendências para ativar canal email real:
1. Registrar domínio `vetorops.com.br` (registro.br)
2. Configurar hospedagem de email (Zoho Mail, Google Workspace ou Brevo)
3. Atualizar `dados/config_canal_email.json`: `email_remetente_planejado` com email real
4. Alterar `modo=real` em `config_canal_email.json` após SMTP configurado
5. Testar envio real antes de produção

Não obrigatórios para email real:
- Site oficial
- Logo ou identidade visual
- Instagram oficial
- WhatsApp cadastrado

---

## 7. Arquivos de Referência

| Arquivo | Conteúdo |
|---------|----------|
| `dados/identidade_empresa.json` | Nome, descrição, proposta, linhas de serviço |
| `dados/guia_comunicacao_empresa.json` | Tom de voz, posturas, vocabulário |
| `dados/assinaturas_empresa.json` | Assinaturas institucionais por área |
| `dados/canais_empresa.json` | Domínio e emails planejados |
| `dados/prontidao_canais_reais.json` | Status de prontidão para canal real |
| `dados/historico_identidade_empresa.json` | Histórico auditável de alterações |

---

*Gerado por seed_fundacao_institucional.py em 2026-03-23*
