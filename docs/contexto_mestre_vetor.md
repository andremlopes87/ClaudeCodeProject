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
| Documentos oficiais | `core/documentos_empresa.py` | `dados/documentos_oficiais.json` · `artefatos/documentos/` |
| Governança | `core/governanca_conselho.py` | `dados/governanca_conselho.json` |
| Observabilidade | `core/observabilidade_empresa.py` | `dados/painel_conselho.json` · `dados/metricas_empresa.json` |
| Canais externos | `core/integrador_canais.py` · `core/integrador_email.py` | `dados/canal_email_config.json` |
| Orquestrador | `core/orquestrador_empresa.py` | `dados/ciclo_operacional.json` · `dados/estado_empresa.json` |
| Painel web | `conselho_app/app.py` · `conselho_app/templates/` | serve HTTP na porta 8000 |

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

## 8. Formato padrão das respostas

- Resumo curtíssimo (1–3 linhas)
- Arquivos criados/alterados (lista)
- Lógica em 5 linhas
- Antes/depois quando relevante
- Próximo gargalo principal
