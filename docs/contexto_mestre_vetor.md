# Contexto Mestre — Vetor Operações

> Documento de referência rápida. Estável. Não repete histórico de conversa.
> Prompts futuros devem referenciar este arquivo em vez de reexplicar a empresa.

---

## 1. Identidade

| Campo | Valor |
|---|---|
| Nome oficial | Vetor Operações Ltda |
| Nome de exibição | Vetor |
| Proposta de valor | Operação completa por IA — para negócios que querem crescer sem crescer o time |
| Público-alvo | Pequenos e médios negócios locais (barbearias, clínicas, padarias, oficinas, salões) |
| Linhas de serviço | marketing_presenca_digital · automacao_atendimento · gestao_comercial · gestao_financeira |
| Base | São Paulo, Brasil |

---

## 2. Direção mestra

- Empresa operada por agentes de IA em camadas; humano atua como decisor final, não operador diário
- Conselho = nível deliberativo/estratégico (painel web `conselho_app/`)
- Operação = agentes autônomos com limites claros de autonomia; escalam para o conselho quando necessário
- Princípios: simplicidade, modularidade, legibilidade, agent-ready, baixo atrito, custo zero na fase inicial
- Arquitetura: JSON como contrato entre módulos, logs estruturados, idempotência, best-effort para integrações externas

---

## 3. Agentes existentes

| Agente | Papel | Autonomia | Artefatos principais |
|---|---|---|---|
| agente_prospeccao | Encontra empresas-alvo e gera oportunidades | Alta | pipeline_comercial.json |
| agente_marketing | Analisa presença digital e prepara abordagem | Alta | pipeline_comercial.json |
| agente_comercial | Processa resultados de contato, gera propostas, contratos | Alta | pipeline_comercial.json, propostas_comerciais.json, contratos_clientes.json |
| agente_secretario | Consolida ciclo, cria handoffs e deliberações | Alta | handoffs_agentes.json, deliberacoes_conselho.json |
| agente_executor_contato | Prepara execuções dos handoffs operacionais | Assistida | handoffs_agentes.json |
| agente_financeiro | Analisa caixa, gera recebíveis, reconcilia contratos | Alta | estado_financeiro.json, contas_a_receber.json, previsao_caixa.json |
| agente_operacao_entrega | Abre e avança entregas, gera onboardings | Alta | pipeline_entrega.json, documentos oficiais |
| integrador_canais | Aplica resultados de canal externo (email, etc.) | Assistida | resultados_contato.json |
| gerador_insumos | Gera insumos necessários para execução | Alta | insumos_entrega.json |
| avaliador_fechamento | Avalia se oportunidade está pronta para fechar | Alta | pipeline_comercial.json |
| agente_customer_success | Saúde de contas, NPS, playbooks de retenção, expansão | Alta | relatorio_customer_success.json, acoes_customer_success.json, nps_pendentes.json, oportunidades_expansao.json |
| agente_auditor_seguranca | Varredura estática de vulnerabilidades de segurança | Zero (dry-run) | relatorio_seguranca.json, historico_auditorias_seguranca.json |
| agente_qualidade | Testes, cobertura e qualidade de código | Zero (dry-run) | relatorio_qualidade.json, historico_qualidade.json |
| agente_executor_melhorias | Aplica melhorias com backup/rollback automático | Zero em dry-run | relatorio_melhorias.json, historico_melhorias.json, backups/ |

---

## 4. Módulos do sistema

| Módulo | Arquivo core | Dados principais |
|---|---|---|
| Identidade | `core/identidade_empresa.py` | `dados/identidade_empresa.json` |
| Ofertas/catálogo | `core/ofertas_empresa.py` | `dados/catalogo_ofertas.json` |
| Prospecção | `agentes/prospeccao/` | `dados/pipeline_comercial.json` |
| Marketing | `agentes/marketing/` · `core/executor_marketing.py` | `dados/pipeline_comercial.json` |
| Comercial / Propostas | `core/propostas_empresa.py` · `core/expediente_propostas.py` | `dados/propostas_comerciais.json` |
| Contratos / Faturamento | `core/contratos_empresa.py` | `dados/contratos_clientes.json` · `dados/planos_faturamento.json` |
| Entrega | `agentes/operacao_entrega/` | `dados/pipeline_entrega.json` · `dados/checklists_entrega.json` |
| Financeiro | `agentes/financeiro/` · `modulos/financeiro/` | `dados/contas_a_receber.json` · `dados/previsao_caixa.json` |
| Reconciliação contratos | `modulos/financeiro/reconciliador_contratos_faturamento.py` | `dados/historico_reconciliacao_contratos.json` |
| Contas/clientes | `core/contas_empresa.py` | `dados/contas_clientes.json` |
| Acompanhamento pós-entrega | `core/acompanhamento_contas.py` | `dados/acompanhamentos_contas.json` |
| Customer Success | `agentes/customer_success/agente_customer_success.py` | `dados/relatorio_customer_success.json` · `dados/acoes_customer_success.json` · `dados/saude_contas_clientes.json` |
| NPS & Feedback | `core/nps_feedback.py` | `dados/nps_pendentes.json` · `dados/nps_respostas.json` · `dados/historico_nps.json` |
| Playbooks CS | `core/playbooks_cs.py` | `dados/playbooks_customer_success.json` · `dados/historico_playbooks_cs.json` |
| Motor de Expansão | `core/motor_expansao.py` | `dados/oportunidades_expansao.json` · `dados/propostas_expansao.json` |
| Documentos oficiais | `core/documentos_empresa.py` | `dados/documentos_oficiais.json` · `artefatos/documentos/` |
| Governança | `core/governanca_conselho.py` | `dados/governanca_conselho.json` |
| Observabilidade | `core/observabilidade_empresa.py` | `dados/painel_conselho.json` · `dados/metricas_empresa.json` |
| Canais externos | `core/integrador_canais.py` · `core/integrador_email.py` | `dados/config_canal_email.json` |
| Email — templates | `core/templates_email.py` | templates por tipo: abordagem, proposta, followup, nps |
| Email — leitor | `core/leitor_respostas_email.py` | classificar respostas e disparar ações; `dados/respostas_email.json` |
| Email — simulação | `core/simulador_ciclo_email.py` | ensaio de ponta a ponta sem SMTP; `dados/metricas_email.json` |
| LLM Router | `core/llm_router.py` | seleção de modelo, dry-run/real, fallback, custo estimado |
| LLM Auditoria | `core/llm_log.py` | log de todas as chamadas LLM com custo; `dados/log_llm.json` |
| Orquestrador | `core/orquestrador_empresa.py` | ciclo de 16 etapas com checkpoint; `dados/ciclo_operacional.json` |
| Painel web | `conselho_app/app.py` · `conselho_app/templates/` | 50+ rotas, 32 templates, porta 8000 |

---

## 5. Entidades principais

| Entidade | Papel |
|---|---|
| Oportunidade | Empresa-alvo identificada; percorre pipeline_comercial por status (prospectada→ganho) |
| Proposta | Oferta formal gerada para uma oportunidade; tem entregáveis, valor, prazo, escopo |
| Contrato | Formalização do aceite da proposta; gera plano de faturamento e recebíveis |
| Plano de faturamento | Cronograma de parcelas vinculado ao contrato |
| Entrega | Execução operacional do contrato; tem checklist, etapas, insumos |
| Conta/Cliente | Empresa-cliente cadastrada; agrega histórico comercial, financeiro e de entrega |
| Recebível | Conta a receber vinculada a parcela de contrato ou evento avulso |
| Deliberação | Decisão que precisa de aprovação humana no conselho |
| Handoff | Tarefa operacional passada de um agente a outro ou a canal externo |
| Documento oficial | Artefato HTML gerado a partir de proposta/contrato/entrega; versionado por checksum |
| Insumo | Recurso necessário para execução de entrega (fornecido pelo cliente) |
| Acompanhamento | Contato pós-entrega para verificar saúde da conta e identificar expansões |
| Saúde de conta | Score 0-100 calculado por CS; status: excelente/boa/atencao/critica |
| NPS | Pesquisa de satisfação disparada por gatilho (pós-entrega, primeiro mês, trimestral); score 0-10 |
| Playbook CS | Receita de retenção ativada por padrão de risco; gera ações para executor_contato |
| Oportunidade de expansão | Upsell/cross-sell/indicação detectada pelo motor_expansao; funil detectada→convertida |

---

## 6. Convenções do projeto

- Não criar fluxo paralelo — enricher sempre no módulo já existente
- Reaproveitar arquitetura atual; enriquecer em vez de duplicar
- Sem refatoração ampla sem necessidade clara
- Sem automação externa sensível (email real, push, webhooks) sem etapa explícita de aprovação
- Custo zero na fase de validação; APIs pagas só com aprovação explícita
- Idempotência em toda geração de objeto (contrato, recebível, documento, etc.)
- Best-effort para integrações externas — jamais bloquear o ciclo principal por falha de canal
- Respostas do Claude sempre curtas; sem recapitular histórico já implícito no repo

---

## 7. Formato padrão dos próximos prompts

```
Seguir contexto mestre da Vetor no repo.

Objetivo:
[1 frase]

Escopo:
- [item]

Arquivos:
- criar:
- alterar:
- reutilizar:

Regras:
- [regra]

Validação:
- [teste 1]

Entrega:
- resumo curtíssimo
- arquivos criados/alterados
- lógica em 5 linhas
- antes/depois
- próximo gargalo principal
```

---

## 8. Pós-venda — visão técnica

### agente_customer_success (`agentes/customer_success/`)
- Roda em ciclos; lê contas ativas, calcula `score_saude` (0-100) por conta
- Score: base 60 + pesos por entregas concluídas, recebíveis em dia, NPS, acompanhamentos
- Gera ações de acompanhamento por conta → `dados/acoes_customer_success.json`
- Dispara playbooks de risco via `core/playbooks_cs.py`
- Detecta oportunidades de expansão via `agente_customer_success.sugerir_expansao_para_conta`
- Programa NPS automático (gatilhos: pós-entrega, primeiro mês, trimestral)
- Gera relatório consolidado → `dados/relatorio_customer_success.json`
- Chama LLM para diagnóstico por conta (dry-run por padrão)

### core/playbooks_cs.py
- Playbooks definidos em `dados/playbooks_customer_success.json` (editável)
- Gatilhos: `inatividade`, `nps_detrator`, `pagamento_atrasado`, `entrega_bloqueada`
- Severidades: `atencao`, `risco`, `critico`
- Gera ações com prazo e template para executor_contato
- Histórico de execuções: `dados/historico_playbooks_cs.json`

### core/nps_feedback.py
- Programação automática por gatilho nos momentos certos do ciclo de vida
- Janela mínima de 30 dias entre pesquisas para a mesma conta
- Análise de sentimento via LLM: positivo / neutro / negativo / negativo_grave
- Ações derivadas automáticas: `escalacao_urgente`, `planejamento_retencao`, `expansao_indicacao_sugerida`
- Tipos de respondente derivados do score: promotor (≥9), neutro (7-8), detrator (≤6)

### core/motor_expansao.py
- Detecta oportunidades por conta: renovacao, upsell, cross-sell, indicacao
- Score de expansão 0-100 com 5 fatores objetivos
- Classificação: quente (≥70), morna (50-70), fria (<50)
- Gera pitch personalizado via LLM para oportunidades quentes
- Cria handoff para agente_comercial com `tipo="expansao"`
- Funil: detectada → qualificada → preparada → handoff_criado → convertida → descartada

### Painel — rotas de pós-venda
| Rota | Conteúdo |
|---|---|
| `/customer-success` | Saúde do portfólio, distribuição, playbooks, ações pendentes/executadas |
| `/nps` | Score NPS empresa, detratores, promotores, pendentes de envio |
| `/expansao` | Pipeline de expansão, top 5, convertidas, valor estimado |

---

## 9. Canais de comunicação — visão técnica

### Arquitetura
- Abstração unificada em `core/canais.py` — `CanalBase`, `CanalEmail`, `CanalWhatsApp`, `CanalTelefone`
- Cada canal tem: `preparar_envio`, `enviar`, `verificar_resposta`, `status`
- Implementações reais em `conectores/` com lazy-import para evitar circular import
- Modos: `dry-run` (padrão, sem envio real), `assistido` (humano vê e executa), `real` (automático)
- Estado global em `dados/estado_canais.json`

### Canal Email (`conectores/` + `core/integrador_email.py`)
- Modo simulado: status avança para `enviado_simulado` automaticamente; respostas geradas por probabilidade
- Modo assistido: fila em `dados/fila_envio_email.json`; operador envia manualmente
- Modo real: SMTP/IMAP via `dados/config_canal_email.json`
- Templates por tipo em `core/templates_email.py`: abordagem_inicial, envio_proposta, followup_sem_resposta, nps
- Leitor de respostas: `core/leitor_respostas_email.py` — classifica (11 tipos) e dispara ações
- Simulação de ponta a ponta: `core/simulador_ciclo_email.py` — sem SMTP real; `dados/metricas_email.json`
- Checklist de ativação real em `/ativacao-email`; teste de SMTP/IMAP via `/api/verificar-smtp`

### Canal WhatsApp (`conectores/whatsapp.py`)
- 4 templates: `abordagem_inicial`, `followup`, `proposta`, `nps`
- Fila em `dados/fila_envio_whatsapp.json`
- Número normalizado para `+55XXXXXXXXXXX`
- API real: WhatsApp Business Cloud (não contratado — dry-run por padrão)
- Config: `dados/config_canal_whatsapp.json`

### Canal Telefone (`conectores/telefone.py`)
- 3 roteiros: `abordagem_fria`, `followup`, `cobranca_gentil`
- Modo assistido: operador vê roteiro completo e registra resultado
- 6 outcomes: `atendeu_interessado`, `atendeu_recusou`, `nao_atendeu`, `caixa_postal`, `numero_invalido`, `ocupado`
- `atendeu_interessado` → cria follow-up por email automaticamente
- Fila em `dados/fila_chamadas_telefone.json`; histórico em `dados/resultados_chamadas.json`
- Integração VoIP futura: `conectores/telefone.py → _enviar_real_placeholder()`
- Config: `dados/config_canal_telefone.json`

### Painel — rotas de canais
| Rota | Conteúdo |
|---|---|
| `/canais` | Visão geral: modo, fila, taxa resposta, histórico 7 dias por canal |
| `/email` | Fila, métricas, funil, últimas respostas, por template, badge de modo |
| `/email/simulacao` | Ensaio de ponta a ponta: botão rodar, resultado inline, métricas acumuladas |
| `/telefone` | Fila de chamadas com roteiro, formulário de resultado, histórico |
| `/ativacao-email` | Checklist de ativação + botões de teste SMTP/IMAP |

---

## 10. Multi-Cidade — visão técnica

### Modelo de dados
- Cidades derivadas do campo `cidade` em `dados/pipeline_comercial.json`
- Não há tabela separada de cidades — extração on-the-fly via pipeline
- Nichos: campo `categoria` ou `segmento` ou `tipo_negocio` da oportunidade

### Painel `/multi-cidade`
- Ranking de cidades por oportunidades ativas
- Ranking de nichos cross-cidade (nicho presente em mais de uma cidade)
- Detecção de redes/franquias: mesmo nome de empresa em múltiplas cidades
- Progressão: leads → oportunidades por cidade (barra proporcional)

### Expansão geográfica
- Objetivo atual: validar operação em 1 cidade antes de replicar
- Quando iniciar multi-cidade: ao fechar 2+ contratos na cidade-base
- Próxima cidade: definir por densidade de leads qualificados no pipeline

---

## 11. Agentes de TI — visão técnica

Os agentes de TI operam de forma autônoma 2–3x por semana, na madrugada, sem interferir na operação diária.

### agente_auditor_seguranca (`agentes/ti/`)
- Varredura estática de todos os `.py` do projeto buscando 9 categorias de vulnerabilidades
- Nunca modifica código, nunca executa código encontrado, nunca loga dados sensíveis
- Escalona críticas/altas para deliberação do conselho
- Saída: `dados/relatorio_seguranca.json`, `dados/historico_auditorias_seguranca.json`
- Schedule: segunda e quinta às 02:00

### agente_qualidade (`agentes/ti/`)
- Roda todos os `test_*.py` via subprocess com timeout configurável
- Analisa cobertura de módulos (quais têm teste), arquivos grandes, funções sem docstring, TODOs
- Gera recomendações priorizadas e handoffs para o executor
- Saída: `dados/relatorio_qualidade.json`, `dados/historico_qualidade.json`
- Schedule: terça e sexta às 03:00

### agente_executor_melhorias (`agentes/ti/`)
- **Único agente que modifica código** no projeto
- Guardas obrigatórias: backup pré-mudança → aplicar → testes → rollback automático se falhar
- Máximo 3 mudanças por execução; nunca aplica risco alto sem aprovação do conselho
- Em `LLM_MODO=dry-run` (padrão): planeja mas não aplica — registra como "simulada"
- Saída: `dados/relatorio_melhorias.json`, `dados/historico_melhorias.json`, `dados/backups/`
- Schedule: quarta e sábado às 04:00

### core/guardas_codigo.py
- `criar_backup_pre_mudanca()` — copia todos os `.py` para `dados/backups/backup_TIMESTAMP/`
- `verificar_integridade_pos_mudanca()` — py_compile + suite de testes completa
- `reverter_mudanca()` — restaura todos os arquivos do backup, registra incidente
- `validar_mudanca_proposta()` — whitelist/blacklist de arquivos, limite de linhas

### core/politicas_ti.py + dados/politicas_ti.json
- Governança centralizada dos 3 agentes de TI
- `executor_pode_aplicar(tipo, arquivo, risco)` — valida whitelist, blacklist, tipo permitido, risco máximo
- `executor_em_cooldown()` — 24h de cooldown após qualquer rollback
- `auditor_ativo()` / `qualidade_ativo()` — respeitam agentes_pausados e modo_empresa
- Modo conservador → executor limitado a risco_maximo=baixo
- Modo manutenção → apenas auditor roda; executor e qualidade bloqueados
- Conselho pode alterar via `atualizar_politica_ti(secao, campo, valor)` ou painel `/governanca`

### Painel — rota /ti
- Score de segurança + score de qualidade + modo executor em cards principais
- Seção Segurança: vulnerabilidades por severidade, top 10 achados, histórico de auditorias
- Seção Qualidade: barras de testes e cobertura, recomendações por prioridade, módulos sem teste, evolução do score
- Seção Melhorias: mudanças aplicadas/revertidas/simuladas, histórico, backups disponíveis
- Cards TI no dashboard `/`: Segurança (score + vulns), Qualidade (score + testes%), Melhorias (aplicadas + pendentes)
- Seção TI no `/governanca`: pausar/retomar cada agente, alterar risco_maximo do executor
- Badge `!` no menu de navegação quando há vulnerabilidade crítica ou rollback recente

---

## 12. Formato padrão das respostas

- Resumo curtíssimo (1–3 linhas)
- Arquivos criados/alterados (lista)
- Lógica em 5 linhas
- Antes/depois quando relevante
- Próximo gargalo principal
