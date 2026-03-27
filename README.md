# Vetor — Empresa operada por agentes de IA

Plataforma de agentes autônomos que opera uma empresa enxuta de serviços digitais para pequenos negócios.
O sistema prospecta clientes, fecha propostas, entrega projetos e acompanha contas — sem operador humano diário.
O usuário atua apenas como decisor final via painel do conselho.

---

## Arquitetura

```
          [Scheduler / main_empresa.py]
                      |
          [Orquestrador — 16 etapas]
         /      |      |      |      \
  Financeiro  Prosp.  Mktg  Comerc. Entrega
        \      |      |      |      /
         [Integrador de Canais]
          Email | WhatsApp | Telefone
                      |
             [Leitor de Respostas]
                      |
         [CS | Secretário | TI]
                      |
          [Painel do Conselho — FastAPI]
```

Todos os módulos se comunicam via JSON (`dados/`). Nenhum módulo acessa banco de dados externo.
LLM em dry-run por padrão — zero custo enquanto em validação.

---

## Agentes operacionais

| Agente | Função | Frequência |
|---|---|---|
| `agente_financeiro` | Fluxo de caixa, recebíveis, conciliação de contratos | Diária |
| `agente_prospeccao` | Busca empresas via OSM, gera oportunidades | Diária |
| `agente_marketing` | Score de presença digital, preparação de abordagem | Diária |
| `agente_comercial` | Processa resultados de contato, propostas, contratos | 2x por ciclo |
| `agente_executor_contato` | Prepara execuções operacionais de handoffs | Diária |
| `agente_operacao_entrega` | Abre/avança entregas, gera onboarding | 2x por ciclo |
| `agente_customer_success` | Saúde de contas, NPS, playbooks, retenção | Diária |
| `agente_secretario` | Consolida ciclo, cria handoffs, deliberações | 2x por ciclo |
| `agente_auditor_seguranca` | Varredura estática de vulnerabilidades no código | Semanal |
| `agente_qualidade` | Executa testes, analisa cobertura, recomendações | Semanal |
| `agente_executor_melhorias` | Aplica melhorias com backup e rollback | Sob demanda |

### Ciclo do orquestrador (16 etapas)

```
 1/16  agente_financeiro          — caixa, recebíveis, conciliação
 2/16  agente_prospeccao          — novas oportunidades
 3/16  agente_marketing           — presença digital, abordagem
 4/16  agente_comercial           — 1ª passagem: importar resultados de contato
 5/16  agente_operacao_entrega    — 1ª passagem: abrir/avançar entregas
 6/16  agente_secretario          — 1ª passagem: consolidar, handoffs, deliberações
 7/16  agente_executor_contato    — preparar execuções de handoffs
 8/16  integrador_email           — preparar emails assistidos
 9/16  integrador_canais          — outros canais (dry-run)
10/16  leitor_respostas_email     — ler, classificar e agir sobre respostas
11/16  agente_comercial           — 2ª passagem: reabsorver efeitos do executor
12/16  gerador_insumos_contato    — gerar insumos de entrega a partir de contatos
13/16  avaliador_fechamento       — avaliar oportunidades prontas para fechar
14/16  agente_operacao_entrega    — 2ª passagem: continuar entregas
15/16  agente_customer_success    — saúde, NPS, playbooks, retenção
16/16  agente_secretario          — 2ª passagem: retrato final do ciclo
```

---

## Catálogo de serviços

| Serviço | Preço | Prazo | Alvo |
|---|---|---|---|
| Agendamento Digital | R$ 800 única | 7 dias | Barbearias, salões |
| Atendimento WhatsApp | R$ 600 única | 5 dias | Mecânicas, açougues, padarias |
| Presença Digital Básica | R$ 400 única | 3 dias | Todos os segmentos SMB |
| Operação Contínua | R$ 497/mês | — | Barbearias, salões, mecânicas |

Definições completas em `dados/catalogo_ofertas.json` e `dados/planos_execucao.json`.

---

## Infraestrutura

| Componente | Descrição |
|---|---|
| `core/llm_router.py` | Cérebro LLM: seleção de modelo, dry-run/real, fallback, custo |
| `core/llm_log.py` | Auditoria de todas as chamadas LLM com estimativa de custo |
| `core/scheduler.py` | Agendamento: ciclo completo às 06h, tarefas avulsas |
| `core/persistencia.py` | Único ponto de leitura/escrita — todos os dados em `dados/` |
| `core/canais.py` | Abstração unificada de canais: Email, WhatsApp, Telefone |
| `core/orquestrador_empresa.py` | Ciclo de 16 etapas com checkpoint, log e resumo por agente |
| `core/governanca_conselho.py` | Pausar/retomar agentes, modo dos agentes, diretivas |
| `core/observabilidade_empresa.py` | Métricas do painel: dashboard, saúde, alertas |
| `core/simulador_ciclo_email.py` | Simulação de ponta a ponta do fluxo de email (sem SMTP real) |

**Modos de operação:**
- `dry-run` (padrão): zero custo, zero envio, apenas lógica e dados locais
- `assistido`: Claude prepara, humano revisa e envia
- `real`: produção — requer SMTP/IMAP/API configurados

---

## Painel do conselho

Acesso: `python main_conselho.py` → `http://localhost:8000`

| Seção | URL | Função |
|---|---|---|
| Visão Geral | `/` | Dashboard executivo com métricas do ciclo |
| Feed de Eventos | `/feed` | Log de todos os eventos do sistema |
| Agentes | `/agentes` | Status e métricas por agente |
| Áreas | `/areas` | Visão por departamento |
| Comercial | `/comercial` | Pipeline, propostas, oportunidades |
| Entrega | `/entrega` | Pipeline de entrega, onboarding |
| Financeiro | `/financeiro` | Caixa, recebíveis, projeções |
| Contas | `/contas` | Clientes ativos, histórico |
| Acompanhamento | `/acompanhamento` | Follow-ups pós-venda |
| Contratos | `/contratos` | Contratos e planos de cobrança |
| Customer Success | `/customer-success` | Saúde, NPS, playbooks |
| NPS & Feedback | `/nps` | Pesquisas e respostas |
| Documentos | `/documentos` | Propostas, contratos, onboarding (geração + envio) |
| Deliberações | `/deliberacoes` | Fila de aprovação humana |
| Propostas | `/propostas` | Gestão de propostas comerciais |
| Governança | `/governanca` | Políticas, diretivas, controles |
| Saúde | `/saude` | Score de saúde da empresa |
| Identidade | `/identidade` | Identidade e marca da empresa |
| Ofertas | `/ofertas` | Catálogo de serviços |
| Email | `/email` | Canal email: fila, métricas, funil |
| Email Simulação | `/email/simulacao` | Ensaio de ponta a ponta sem SMTP real |
| Ativação Email | `/ativacao-email` | Checklist de ativação SMTP/IMAP |
| Canais | `/canais` | Visão geral de todos os canais |
| Multi-Cidade | `/multi-cidade` | Expansão para outras cidades |
| Expansão | `/expansao` | Oportunidades de upsell/cross-sell |
| TI | `/ti` | Segurança, qualidade, melhorias |
| LLM | `/llm` | Custos e uso de LLM |
| Scheduler | `/scheduler` | Agenda de tarefas |

---

## Segurança e qualidade

**Agentes de TI** executam automaticamente via scheduler:

| Agente | O que faz |
|---|---|
| `agente_auditor_seguranca` | Varre o código em busca de hardcoded secrets, SQL injection, XSS, permissões inseguras |
| `agente_qualidade` | Executa testes unitários, mede cobertura, gera relatório de qualidade |
| `agente_executor_melhorias` | Aplica correções aprovadas com backup automático e rollback em caso de falha |

Políticas definidas em `dados/politicas_ti.json`. Scores visíveis em `/ti`.

---

## Como rodar

```bash
# Ciclo operacional completo (16 etapas)
python main_empresa.py

# Scheduler contínuo (ciclo completo às 06h + tarefas avulsas)
python main_scheduler.py

# Ver agenda do scheduler sem executar
python main_scheduler.py --dry-run

# Painel web do conselho
python main_conselho.py

# Expansão multi-cidade (status)
python main_multi_cidade.py --status

# Simulação de ciclo email de ponta a ponta
python main_simular_ciclo_email.py --n 5

# Agentes individuais (para debug ou execução avulsa)
python main_agente_prospeccao.py
python main_agente_comercial.py
python main_agente_financeiro.py
python main_agente_customer_success.py
python main_agente_secretario.py
# ... (ver main_agente_*.py para todos)
```

---

## Instalação

```bash
pip install -r requirements.txt
```

Sem banco de dados externo. Todos os dados em `dados/` (JSON).
LLM em dry-run por padrão — sem chave de API obrigatória para testar.

---

## Estrutura do projeto

```
ClaudeCodeProject/
├── agentes/
│   ├── comercial/              agente_comercial.py
│   ├── customer_success/       agente_customer_success.py
│   ├── executor_contato/       agente_executor_contato.py
│   ├── financeiro/             agente_financeiro.py
│   ├── marketing/              agente_marketing.py
│   ├── operacao_entrega/       agente_operacao_entrega.py
│   ├── prospeccao/             agente_prospeccao.py
│   ├── secretario/             agente_secretario.py
│   └── ti/                     agente_auditor_seguranca.py
│                               agente_qualidade.py
│                               agente_executor_melhorias.py
├── artefatos/                  Documentos gerados (HTML): propostas, contratos, onboarding
├── conectores/
│   ├── email.py                Conector SMTP/IMAP
│   ├── whatsapp.py             Conector WhatsApp Business
│   ├── telefone.py             Conector de chamadas
│   └── overpass.py             Conector OpenStreetMap (dados de prospecção)
├── conselho_app/
│   ├── app.py                  FastAPI — 50+ rotas
│   ├── templates/              32 templates Jinja2
│   └── static/                 CSS e assets
├── core/
│   ├── orquestrador_empresa.py Ciclo de 16 etapas
│   ├── persistencia.py         Único ponto de I/O de dados
│   ├── llm_router.py           Roteador LLM (dry-run/real)
│   ├── llm_log.py              Auditoria LLM com custo
│   ├── scheduler.py            Agendamento de tarefas
│   ├── canais.py               Abstração unificada de canais
│   ├── simulador_ciclo_email.py Ensaio de email ponta a ponta
│   ├── templates_email.py      Biblioteca de templates de email
│   ├── leitor_respostas_email.py Classificador de respostas
│   ├── integrador_email.py     Integração canal email
│   ├── integrador_canais.py    Integração multi-canal
│   ├── governanca_conselho.py  Governança e diretivas
│   ├── deliberacoes.py         Fila de aprovação humana
│   ├── documentos_empresa.py   Geração de documentos oficiais
│   ├── propostas_empresa.py    Gestão de propostas
│   ├── contratos_empresa.py    Gestão de contratos
│   ├── contas_empresa.py       Gestão de contas de clientes
│   ├── acompanhamento_contas.py Follow-up e saúde de contas
│   ├── playbooks_cs.py         Playbooks de customer success
│   ├── nps_feedback.py         NPS e análise de sentimento
│   ├── motor_expansao.py       Detecção de upsell/cross-sell
│   ├── orquestrador_multi_cidade.py Expansão para outras cidades
│   ├── observabilidade_empresa.py Métricas e alertas do painel
│   ├── identidade_empresa.py   Identidade e marca
│   ├── ofertas_empresa.py      Catálogo de serviços
│   └── ...                     +15 módulos adicionais
├── dados/                      Todos os dados em JSON (estado, filas, históricos)
│   ├── catalogo_ofertas.json   4 serviços com preço e entregáveis
│   ├── pipeline_comercial.json Oportunidades em aberto
│   ├── pipeline_entrega.json   Entregas em andamento
│   ├── metricas_email.json     Métricas acumuladas do canal email
│   ├── fila_envio_email.json   Fila de envio de emails
│   └── ...                     380+ arquivos de estado e histórico
├── docs/
│   └── contexto_mestre_vetor.md Contexto completo da empresa e operação
├── modulos/
│   ├── prospeccao_operacional/ Busca, análise, priorização via OpenStreetMap
│   └── presenca_digital/       Análise de sites, enriquecimento de canais
├── tests/                      Testes unitários por módulo
├── main_empresa.py             Ciclo operacional completo
├── main_conselho.py            Painel web
├── main_scheduler.py           Scheduler contínuo
├── main_multi_cidade.py        Expansão multi-cidade
├── main_simular_ciclo_email.py Simulação de email
└── main_agente_*.py            Execução avulsa de cada agente
```

---

## Status do projeto

| Fase | Componente | Status |
|---|---|---|
| Concluída | Prospecção operacional (OSM) | Produção |
| Concluída | Análise de presença digital | Produção |
| Concluída | Orquestrador 16 etapas | Produção |
| Concluída | Agentes: comercial, marketing, financeiro | Produção |
| Concluída | Agentes: entrega, secretário, executor_contato | Produção |
| Concluída | Agente customer success + playbooks | Produção |
| Concluída | Agentes de TI (segurança, qualidade, melhorias) | Produção |
| Concluída | Catálogo de serviços + planos de entrega | Produção |
| Concluída | Canal email com simulação de ponta a ponta | Simulado |
| Concluída | Painel do conselho (32 páginas, 50+ rotas) | Produção |
| Concluída | Multi-cidade | Produção |
| Concluída | LLM Router + auditoria de custo | Produção |
| Concluída | Scheduler contínuo | Produção |
| Pendente | SMTP/IMAP real | Aguarda configuração |
| Pendente | WhatsApp Business API real | Aguarda configuração |
| Pendente | Primeiro cliente real | Aguarda operação real |

---

## Para ativar operação real

- [ ] Definir CNPJ e dados da empresa em `dados/identidade_empresa.json`
- [ ] Configurar domínio com e-mail profissional (ex: contato@vetor.com.br)
- [ ] Configurar SMTP/IMAP em `dados/config_canal_email.json`
- [ ] Obter chave da API Anthropic e configurar em variável de ambiente `ANTHROPIC_API_KEY`
- [ ] Trocar LLM Router de dry-run para real em `core/llm_router.py`
- [ ] Testar SMTP/IMAP via `/ativacao-email` no painel
- [ ] Rodar `python main_empresa.py` e revisar deliberações no painel
