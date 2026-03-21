# Módulo de Planejamento Comercial

## Objetivo do módulo

Transformar oportunidades de marketing/presença digital em um plano comercial concreto por empresa:
qual oferta fazer, por qual canal começar, como qualificar o interesse, quando avançar para proposta e quando parar.

---

## O que este módulo faz

Para cada empresa com oportunidade identificada (saída do `planejador_marketing`), gera:

| Campo | Descrição |
|---|---|
| `oferta_principal_comercial` | O que oferecer — da perspectiva do cliente, não da tecnologia |
| `motivo_oferta_principal` | Por que esta oferta faz sentido para esta empresa especificamente |
| `canal_primeiro_contato` | Melhor canal disponível para a primeira abordagem |
| `canal_contato_secundario` | Canal alternativo se o principal não funcionar |
| `abordagem_comercial_inicial` | Ângulo de abertura — o problema a mencionar, não um script pronto |
| `sequencia_followup_comercial` | O que fazer se não houver resposta (3 tentativas, depois encerrar) |
| `criterios_qualificacao` | Como identificar se é um lead real antes de investir mais tempo |
| `sinais_interesse_comercial` | O que indica que vale avançar para proposta |
| `sinais_descarte_comercial` | Quando parar e encerrar o contato |
| `momento_certo_proposta` | Quando apresentar proposta formal — varia por tipo de oferta |
| `proxima_acao_comercial` | Próxima ação concreta com canal + número/e-mail real |
| `status_comercial_sugerido` | Estado atual do lead (ver tabela abaixo) |
| `motivo_status_comercial` | Por que este status foi atribuído |
| `nivel_prioridade_comercial` | alta / media / baixa / sem_dados |
| `observacoes_comerciais` | Ressalvas sobre qualidade dos dados |
| `plano_comercial_gerado` | bool — False para empresas sem oportunidade |

---

## O que este módulo NÃO faz

- Não envia mensagens
- Não agenda contatos
- Não rastreia histórico de abordagens entre execuções
- Não valida se os dados de contato (telefone, e-mail) estão atualizados
- Não gera mensagens prontas para envio ao cliente
- Não decide preço ou condições comerciais

---

## Como interpretar o status comercial

| Status | Significado | O que fazer |
|---|---|---|
| `pronto_para_contato` | Tem canal confiável + oportunidade clara + prioridade alta ou média | Executar `proxima_acao_comercial` agora |
| `identificado` | Tem oportunidade mas prioridade baixa ou canal menos confiável | Abordar após finalizar os de alta prioridade |
| `aguardando_dados` | Sem canal de contato direto disponível | Pesquisar canal antes de abordar |
| `descartado` | Sem oportunidade identificada ou dados insuficientes | Não abordar nesta execução |

---

## Como interpretar a prioridade comercial

| Prioridade | Quando se aplica |
|---|---|
| `alta` | oportunidade_alta + canal confirmado (alta/media) + complexidade baixa ou média |
| `media` | oportunidade_media + canal confirmado, ou oportunidade_alta com complexidade alta |
| `baixa` | oportunidade identificada mas canal pouco confiável |
| `sem_dados` | Sem canal de contato disponível |

---

## Diferença entre identificar oportunidade e executar comercialmente

**Identificar a oportunidade** (etapas anteriores do pipeline):
- A empresa não tem WhatsApp no site → gap `sem_whatsapp`
- A empresa não tem site → gap `sem_website`
- A empresa tem site mas sem CTA → gap `sem_cta`

**Executar comercialmente** (o que este módulo planeja):
- Determinar qual oferta faz sentido para o gap identificado
- Escolher o canal certo para a primeira abordagem (baseado em dados disponíveis)
- Ter uma ação concreta imediata: ligar para qual número, mandar mensagem em qual WhatsApp
- Saber quando parar: 3 tentativas sem resposta → descartar

A distinção é importante: uma empresa pode ter oportunidade clara mas status `aguardando_dados` se não houver canal de contato disponível. Nesses casos, a ação comercial não é ligar — é pesquisar o contato primeiro.

---

## Duplo uso do módulo

Este módulo foi desenhado para dois cenários:

**1. Uso próprio — executar comercial da nossa empresa**

Gera a fila de execução comercial com os leads prontos para abordagem, ordenados por prioridade. A `proxima_acao_comercial` inclui o número real ou e-mail — a ação é executar a ligação ou enviar a mensagem.

**2. Base para comercial de clientes (futuro)**

A mesma lógica pode ser adaptada para gerar planos comerciais para os clientes da plataforma: qual canal usar, qual abordagem, como qualificar, quando parar. O cliente passa a ter um roteiro estruturado para seu próprio time de vendas.

---

## Lógica de seleção de canal

Ordem de preferência para `canal_primeiro_contato`:

1. WhatsApp confirmado (confiança media/alta) → `whatsapp`
2. Telefone confirmado (confiança alta/media) → `telefone`
3. E-mail confirmado (confiança alta/media) → `email`
4. Site acessível com formulário → `formulario_site`
5. Nenhum canal identificado → `pesquisa_adicional`

---

## Arquivos gerados

| Arquivo | O que contém |
|---|---|
| `candidatas_com_plano_comercial.json` | Timestamped — todas as empresas, incluindo campos de plano comercial |
| `fila_execucao_comercial_TIMESTAMP.json` | Timestamped — empresas prontas e identificadas, ordenadas por prioridade |
| `fila_execucao_comercial.json` | Fixo (latest) — mesma fila, sobrescrito a cada execução |

### Critérios da fila de execução comercial

Inclusão: `status_comercial_sugerido` = `pronto_para_contato` ou `identificado` + `nivel_prioridade_comercial` = `alta` ou `media`.

Ordenação:
1. `nivel_prioridade_comercial` (alta → media)
2. `status_comercial_sugerido` (pronto_para_contato → identificado)
3. `nivel_complexidade_execucao` (baixa → media — execuções mais fáceis primeiro)
4. `score_presenca_consolidado` decrescente

---

## Limitações

- **Dados do OSM podem estar desatualizado**: telefone registrado no OpenStreetMap não é validado — confirmar na primeira conversa
- **Sem histórico entre execuções**: o módulo não rastreia se a empresa já foi abordada. Esse controle precisa ser feito manualmente ou em versão futura com CRM
- **WhatsApp inferido, não validado**: um número de telefone do OSM não é automaticamente um WhatsApp — verificar antes de usar como canal principal
- **Sem gestão de respostas**: o módulo planeja a abordagem, mas não processa o resultado do contato
