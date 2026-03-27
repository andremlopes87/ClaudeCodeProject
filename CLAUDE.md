# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projeto

**Vetor** é uma empresa de serviços digitais operada por agentes de IA autônomos.
O sistema prospecta clientes, fecha propostas, entrega projetos e acompanha contas.
O usuário é o decisor final — não o operador diário.

**Repositório GitHub:** https://github.com/andremlopes87/ClaudeCodeProject
**Diretório local:** `C:\Users\Andre\Downloads\ClaudeCodeProject`

## Regras de sincronização com o GitHub

- A cada atualização feita no projeto (novos arquivos, modificações), Claude deve automaticamente fazer commit e push.
- Mensagens de commit descritivas em português.
- Branch principal: `main`.

## Estado atual do sistema

- **11 agentes operacionais** em `agentes/` (ver seção Módulos existentes)
- **Ciclo de 16 etapas** no orquestrador (`core/orquestrador_empresa.py`)
- **32 páginas no painel** via FastAPI + Jinja2 (`conselho_app/`)
- **4 serviços no catálogo** (`dados/catalogo_ofertas.json`)
- **3 canais**: Email, WhatsApp, Telefone — todos com abstração unificada
- **LLM em dry-run** por padrão — zero custo enquanto em validação
- **TI autônoma**: auditor de segurança, qualidade, executor de melhorias

## Módulos existentes

### Agentes (`agentes/`)

| Agente | Arquivo | Função |
|---|---|---|
| comercial | `agentes/comercial/agente_comercial.py` | Propostas, contratos, pipeline comercial |
| customer_success | `agentes/customer_success/agente_customer_success.py` | Saúde de contas, NPS, playbooks |
| executor_contato | `agentes/executor_contato/agente_executor_contato.py` | Execução de handoffs operacionais |
| financeiro | `agentes/financeiro/agente_financeiro.py` | Caixa, recebíveis, projeções |
| marketing | `agentes/marketing/agente_marketing.py` | Presença digital, abordagem |
| operacao_entrega | `agentes/operacao_entrega/agente_operacao_entrega.py` | Entregas, onboarding |
| prospeccao | `agentes/prospeccao/agente_prospeccao.py` | Busca de empresas, oportunidades |
| secretario | `agentes/secretario/agente_secretario.py` | Ciclo, handoffs, deliberações |
| ti/auditor | `agentes/ti/agente_auditor_seguranca.py` | Varredura de vulnerabilidades |
| ti/qualidade | `agentes/ti/agente_qualidade.py` | Testes, cobertura, relatório |
| ti/melhorias | `agentes/ti/agente_executor_melhorias.py` | Aplicar melhorias com rollback |

### Core (`core/`)

| Módulo | Função |
|---|---|
| `orquestrador_empresa.py` | Ciclo de 16 etapas, checkpoint, log por agente |
| `persistencia.py` | ÚNICO ponto de leitura/escrita — sempre usar este |
| `llm_router.py` | Cérebro LLM: seleção de modelo, dry-run/real, custo |
| `llm_log.py` | Auditoria de chamadas LLM com estimativa de custo |
| `scheduler.py` | Agendamento de tarefas (ciclo às 06h + avulsas) |
| `canais.py` | Abstração unificada de canais (Email/WhatsApp/Telefone) |
| `integrador_email.py` | Integração canal email: preparar, enviar, status |
| `integrador_canais.py` | Processar resultados de outros canais |
| `leitor_respostas_email.py` | Ler, classificar e agir sobre respostas de email |
| `simulador_ciclo_email.py` | Ensaio de email de ponta a ponta (sem SMTP real) |
| `templates_email.py` | Biblioteca de templates de email por tipo |
| `motor_cenarios_contato.py` | Cenários de contato por contexto |
| `governanca_conselho.py` | Pausar/retomar agentes, diretivas, modos |
| `deliberacoes.py` | Fila de aprovação humana |
| `documentos_empresa.py` | Geração de documentos oficiais (propostas, contratos) |
| `expediente_documentos_email.py` | Assistência email para documentos oficiais |
| `expediente_propostas.py` | Workflow de propostas |
| `propostas_empresa.py` | Gestão de propostas comerciais |
| `contratos_empresa.py` | Gestão de contratos |
| `contas_empresa.py` | Gestão de contas de clientes |
| `contatos_contas.py` | Contatos por conta |
| `acompanhamento_contas.py` | Follow-up e saúde de contas |
| `playbooks_cs.py` | Playbooks de customer success |
| `nps_feedback.py` | NPS e análise de sentimento |
| `motor_expansao.py` | Detecção de upsell/cross-sell |
| `orquestrador_multi_cidade.py` | Expansão para outras cidades |
| `observabilidade_empresa.py` | Métricas e alertas para o painel |
| `identidade_empresa.py` | Identidade e marca da empresa |
| `ofertas_empresa.py` | Catálogo de serviços |
| `planos_entrega.py` | Templates de planos de entrega |
| `politicas_empresa.py` | Políticas operacionais |
| `politicas_ti.py` | Políticas de TI e governança de agentes |
| `guardas_codigo.py` | Backup, integridade, rollback de código |
| `confiabilidade_empresa.py` | Locks, checkpoints, incidentes |
| `controle_agente.py` | Estado e controle de execução de agentes |
| `executor.py` | Orquestrador antigo do fluxo de prospecção |
| `executor_marketing.py` | Execução de marketing e scoring digital |
| `respostas_documentos.py` | Respostas a documentos oficiais recebidos |
| `provisionamento_canais.py` | Configuração de domínio, SMTP, canais |
| `llm_memoria.py` | Memória persistente de contexto LLM |

## Dados persistentes

Todos os dados em `dados/` (JSON). Nunca criar tabelas ou bancos de dados externos.

| Arquivo | O que guarda |
|---|---|
| `estado_empresa.json` | Estado atual da empresa no ciclo |
| `pipeline_comercial.json` | Oportunidades em aberto |
| `pipeline_entrega.json` | Entregas em andamento |
| `propostas_comerciais.json` | Propostas geradas e status |
| `contratos_clientes.json` | Contratos ativos |
| `contas_clientes.json` | Clientes ativos e histórico |
| `catalogo_ofertas.json` | 4 serviços com preço, prazo e entregáveis |
| `planos_execucao.json` | Planos detalhados por serviço |
| `identidade_empresa.json` | Nome, CNPJ, missão, tom de voz |
| `saude_empresa.json` | Score de saúde e alertas |
| `metricas_empresa.json` | Métricas acumuladas por ciclo |
| `metricas_email.json` | Métricas do canal email (taxas, templates) |
| `fila_envio_email.json` | Fila de emails a enviar |
| `fila_envio_whatsapp.json` | Fila de mensagens WhatsApp |
| `fila_chamadas_telefone.json` | Fila de chamadas telefônicas |
| `handoffs_agentes.json` | Handoffs entre agentes |
| `respostas_email.json` | Respostas recebidas (email) |
| `config_canal_email.json` | Configuração SMTP/IMAP e modo |
| `config_leitor_respostas.json` | Modo do leitor (simulado/real) |
| `politicas_ti.json` | Políticas de TI e governança |
| `log_llm.json` | Auditoria de todas as chamadas LLM |
| `feed_eventos_empresa.json` | Log de eventos do sistema |
| `incidentes_operacionais.json` | Incidentes registrados |
| `scheduler_estado.json` | Estado do scheduler |
| `guia_tom_comunicacao.json` | Tom de voz e regras de comunicação |

**Nota:** `dados/` está no `.gitignore`. Nunca commitar arquivos de dados.

## Padrões atuais

### Padrão de agente
Todo agente segue o contrato:
```python
def executar() -> dict:
    """Retorna dict com: status, resumo, métricas específicas."""
    # 1. Ler dados via core/persistencia.py
    # 2. Processar lógica (com fallback LLM via llm_router)
    # 3. Escrever resultado via core/persistencia.py
    # 4. Retornar resumo estruturado
```

### Padrão de comunicação
- Seguir `dados/guia_tom_comunicacao.json`: direto, concreto, sem buzzwords
- Nunca usar "transformação digital", "IA revolucionária" ou equivalentes
- Foco no problema concreto do negócio do cliente

### Padrão de canal
- Todos os canais usam `core/canais.py` como abstração
- Modos: `dry-run` (default), `assistido`, `real`
- Nunca acoplar agentes diretamente ao canal — sempre via abstração

### Padrão de LLM
- Todas as chamadas LLM passam por `core/llm_router.py`
- dry-run retorna `[DRY-RUN] texto simulado` — zero custo
- Todo uso de LLM é auditado em `core/llm_log.py`
- Nunca chamar API Anthropic diretamente de agentes

### Padrão de dados
- Leitura e escrita SEMPRE via `core/persistencia.py`
- JSON como formato padrão entre módulos
- Nunca ler `dados/` diretamente de agentes sem passar pelo módulo de persistência

## Regra principal

Nunca improvise a estratégia do negócio.
Sempre siga esta ordem:
1. entender o objetivo real
2. mapear o processo atual
3. identificar gargalos
4. propor a menor solução útil
5. esperar aprovação quando houver impacto estrutural
6. implementar com testes
7. registrar o que foi decidido

## Como trabalhar neste projeto

Sempre que receber uma tarefa:
1. leia o contexto relevante (arquivos existentes, não presuma)
2. identifique se é tarefa de negócio, produto, arquitetura ou código
3. proponha um plano curto
4. destaque dúvidas, riscos e dependências
5. só implemente depois de ter um caminho claro
6. após implementar, rode testes e registre o que mudou

## O que otimizar

- automação real
- simplicidade
- baixo atrito
- reutilização de módulos existentes
- clareza de logs
- facilidade de manutenção
- segurança
- aprovação humana em exceções

## O que evitar

- arquitetura inchada
- telas desnecessárias
- abstrações prematuras
- múltiplas formas de fazer a mesma coisa
- dependência de intervenção manual em tarefas repetitivas
- código sem teste
- acoplamento direto entre agentes e canais externos
- commitar arquivos em `dados/`

## Regras de arquitetura

- Backend modular — cada módulo tem responsabilidade única
- Filas para tarefas assíncronas (`fila_*.json`)
- Logs estruturados — todo agente retorna `resumo` dict
- Contratos de entrada/saída explícitos — sempre dict com `status`
- JSON como formato padrão entre módulos
- Configuração centralizada — nunca hardcode de configs
- Features protegidas por flags quando necessário

## Modelo operacional

Duas camadas **nunca misturadas**:
1. Agentes internos da própria empresa (prospecção, financeiro, TI...)
2. Agentes implantados para clientes (futura camada de produto)

## Aprovação humana

Escalar para o usuário quando houver:
- mudança estrutural de arquitetura
- escolha entre caminhos de produto
- risco de segurança
- dúvida sobre regra de negócio
- deploy sensível
- ação destrutiva
- uso de custo relevante (APIs pagas)

## Padrão de entrega

Toda entrega deve incluir:
- objetivo
- abordagem escolhida
- arquivos alterados
- testes executados
- riscos remanescentes
- próximos passos recomendados

## Documentação

Sempre atualize a documentação relevante quando:
- uma regra mudar
- um agente novo for criado
- um conector novo for adicionado
- um fluxo importante mudar

Atualizar `README.md`, `CLAUDE.md` e `docs/contexto_mestre_vetor.md` conforme necessário.

## Estilo

Código limpo, simples e explícito.
Soluções pequenas que funcionam — não estruturas grandiosas sem uso real.
Sem comentários óbvios. Comentar apenas lógica não-evidente.

## Regra de custo

LLM em dry-run por padrão — zero custo em validação.
Não adotar APIs pagas sem aprovação explícita.
Arquitetura preparada para trocar conectores no futuro.
