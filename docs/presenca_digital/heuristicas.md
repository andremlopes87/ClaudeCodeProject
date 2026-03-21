# Heurísticas — Módulo de Presença Digital

## Objetivo do módulo

Analisar a presença digital básica de empresas prospectadas que possuem website registrado nos dados públicos (OpenStreetMap), identificando sinais concretos de organização — ou ausência deles — na página pública do site.

---

## O que este módulo mede

### Sinais verificados

| Sinal | Fonte | Método |
|---|---|---|
| Website registrado nos dados públicos | Campo `sinais["tem_website"]` (OSM) | Campo já calculado pelo analisador OSM |
| Site responde (HTTP 2xx) | HTTP | HEAD → GET (ver estratégia de requisição) |
| Usa HTTPS | URL do campo `website` | Prefixo `https://` |
| Telefone no site | HTML estático | Regex em texto puro + `href="tel:"` |
| E-mail no site | HTML estático | Regex em texto puro + `href="mailto:"` |
| Link para WhatsApp | HTML estático | `href` com `wa.me`, `api.whatsapp.com`, `whatsapp.com/send` |
| Link para Instagram | HTML estático | `href` com `instagram.com` |
| Link para Facebook | HTML estático | `href` com `facebook.com` |
| Chamada clara para ação (CTA) | HTML estático | Texto de links/botões e `href` com palavras-chave |

### Palavras-chave de CTA detectadas

Texto de elementos `<a>` e `<button>`: agendar, agendamento, agende, orçamento, reservar, marcar, solicitar, fale conosco, entre em contato, ligar, chamar, contratar, comprar.

`href` de links: agenda, orcamento, contato, wa.me, whatsapp, reserva, solicitar.

---

## Score de presença web (`score_presenca_web`, 0-100)

| Sinal | Pontos |
|---|---|
| Site acessível (HTTP 2xx) | +20 |
| Usa HTTPS | +10 |
| Telefone no site | +20 |
| E-mail no site | +15 |
| WhatsApp no site | +15 |
| Instagram no site | +10 |
| Facebook no site | +5 |
| CTA clara | +5 |
| **Total** | **100** |

---

## Classificação de presença web

| Classificação | Score | Significado |
|---|---|---|
| `dados_insuficientes` | 0 | Site não acessível ou empresa sem website |
| `presenca_fraca` | 20–35 | Site acessível, sem elementos de contato ou conversão |
| `presenca_basica` | 36–55 | Tem 1–2 elementos de contato |
| `presenca_razoavel` | 56–75 | Bem estruturado, faltam poucos elementos |
| `presenca_boa` | 76–100 | Site completo e organizado |

---

## Estratégia de requisição

```
1. HEAD (timeout 6s)
   ├─ 2xx/3xx → prosseguir para GET
   └─ 4xx/5xx → marcar inacessível, registrar status HTTP, encerrar

2. GET (timeout 10s)
   ├─ 2xx → extrair sinais do HTML
   └─ Erro ou timeout → marcar inacessível, registrar motivo no log

Fallback: se HEAD falhar (timeout ou erro de conexão), tentar GET diretamente.
```

**Headers enviados:** User-Agent identificando o sistema, Accept `text/html`, Accept-Language `pt-BR`.

---

## Extração do HTML

Parser: `html.parser` (biblioteca padrão do Python).

- Links (`<a>`): verificados por `href` (tel:, mailto:, wa.me, instagram.com, facebook.com, palavras-chave de CTA)
- Botões (`<button>`): texto verificado por palavras-chave de CTA
- Texto puro: regex aplicado ao texto acumulado da página para telefone e e-mail não linkados

---

## O que este módulo NÃO mede

- Conteúdo carregado via JavaScript (React, Vue, Angular etc.)
- Anúncios pagos (Google Ads, Meta Ads)
- Qualidade do design ou UX do site
- Posicionamento em buscadores (SEO)
- Métricas de tráfego ou conversão
- Redes sociais além dos links encontrados no site

---

## Limitações

- **Somente websites registrados no OSM**: empresas sem website no OpenStreetMap não são analisadas — a ausência de resultado não significa que a empresa não tem site.
- **JavaScript não processado**: sites modernos que carregam conteúdo dinamicamente mostrarão sinais ausentes mesmo que os elementos existam.
- **Telefone em imagem**: números exibidos como imagem não são detectados pelo parser.
- **Disponibilidade momentânea**: um site pode estar fora do ar no momento da análise e retornar resultado diferente numa nova execução.
- **Subpáginas não visitadas**: apenas a página raiz (homepage) é analisada.

---

## Campos gerados por empresa

| Campo | Tipo | Descrição |
|---|---|---|
| `tem_site` | bool | Empresa tem website nos dados OSM (não Instagram) |
| `site_acessivel` | bool | Site respondeu com HTTP 2xx |
| `status_http_site` | int\|null | Código de resposta HTTP obtido |
| `usa_https` | bool | URL do site começa com `https://` |
| `tem_telefone_no_site` | bool | Telefone encontrado no HTML |
| `tem_email_no_site` | bool | E-mail encontrado no HTML |
| `tem_whatsapp_no_site` | bool | Link de WhatsApp encontrado |
| `tem_instagram_no_site` | bool | Link para Instagram encontrado |
| `tem_facebook_no_site` | bool | Link para Facebook encontrado |
| `tem_cta_clara` | bool | Chamada clara para ação encontrada |
| `score_presenca_web` | int | Score de 0 a 100 |
| `classificacao_presenca_web` | str | Nível de presença digital do site |
| `diagnostico_presenca_digital` | str | Resumo objetivo do que foi encontrado |
| `oportunidade_marketing_principal` | str | Principal lacuna a corrigir |
| `confianca_diagnostico_presenca` | str | alta / baixa / sem_dados |
| `observacao_limite_dados_presenca` | str | Nota sobre limitações da análise |

---

## Arquivos gerados

| Arquivo | O que contém |
|---|---|
| `candidatas_com_diagnostico_web.json` | Todas as empresas com website registrado, com análise completa de presença web |
| `fila_oportunidades_presenca.json` | Empresas com site acessível + presença fraca/básica/razoável + utilidade comercial, ordenadas por oportunidade |
| `candidatas_com_canais_digitais.json` | Todas as empresas com ao menos um canal digital identificado (qualquer confiança) |

### Critérios da fila de oportunidades de presença

Inclusão: site acessível + classificação `presenca_fraca`, `presenca_basica` ou `presenca_razoavel` + não é `pouco_util`.

Ordenação:
1. `classificacao_presenca_web` (fraca → básica → razoável)
2. `score_presenca_web` crescente (menos estruturado primeiro)
3. `score_prontidao_ia` decrescente (mais prioritária comercialmente)

---

## Módulo de enriquecimento de canais (`enriquecedor_canais.py`)

Consolida os principais canais digitais de cada empresa a partir de múltiplas fontes, produzindo para cada canal: valor confirmado, origem do dado e nível de confiança.

### O que é canal confirmado

Um canal é confirmado quando foi identificado em pelo menos uma fonte confiável. O valor pode ser concreto (URL, número, e-mail) ou `null` quando há sinal de presença mas sem valor extraível (ex: link para Instagram detectado no HTML sem URL capturada).

### O que é origem do dado

| Origem | Significado |
|---|---|
| `osm` | Campo direto do OpenStreetMap (website, telefone, email, instagram tag) |
| `osm_verificado` | Campo OSM + site confirmado como acessível via HTTP |
| `website_osm` | Campo website OSM que aponta para a rede social (ex: instagram.com) |
| `html_website` | Valor extraído do HTML da homepage do site |
| `html_contato` | Valor extraído do HTML da subpágina /contato ou /contact |
| `html_sinal` | Link detectado no HTML mas sem URL/valor capturável |
| `nao_identificado` | Nenhuma fonte encontrou este canal |

### O que é confiança do dado

| Confiança | Quando se aplica |
|---|---|
| `alta` | Campo OSM explícito (registrado publicamente) ou website OSM + site acessível |
| `media` | Valor real extraído do HTML (URL, número, e-mail via href) |
| `baixa` | Sinal booleano detectado (link presente) sem valor extraível |
| `nao_identificado` | Canal não encontrado em nenhuma fonte |

### Canais tratados

website, instagram, facebook, whatsapp, email, telefone

### Fontes por canal (em ordem de prioridade)

**website:** OSM campo + acessível (alta) → OSM campo sem verificação (media)

**instagram:** tag OSM (alta) → website OSM é instagram.com (alta) → URL no HTML (media) → URL na subpágina /contato (media) → sinal booleano (baixa)

**facebook:** URL no HTML (media) → URL na subpágina /contato (media) → sinal booleano (baixa)

**whatsapp:** URL wa.me no HTML (media) → URL na subpágina /contato (media) → sinal booleano (baixa)

**email:** campo OSM (alta) → valor href mailto: no HTML (media) → valor na subpágina /contato (media) → sinal booleano (baixa)

**telefone:** campo OSM (alta) → valor href tel: no HTML (media) → valor na subpágina /contato (media) → sinal booleano (baixa)

### Subpágina /contato

Tentativa controlada de buscar canais adicionais em subpáginas simples.

**Condição:** site já confirmado como acessível pelo analisador_web.

**Tentativas:** `/contato` e `/contact` (primeira que retornar HTTP 2xx é usada).

**Extração:** mesmas heurísticas da homepage — sem JavaScript, apenas HTML estático.

### Limitações do enriquecimento

- **OSM como base:** a maioria dos canais vem do OSM, que tem cobertura esparsa nas cidades brasileiras.
- **HTML estático:** valores em JavaScript (chatbots, formulários dinâmicos) não são capturados.
- **Subpáginas não garantidas:** o caminho `/contato` pode não existir ou ter conteúdo diferente do esperado.
- **Sem validação de canal:** um telefone `alta` do OSM pode estar desatualizado — o sistema não verifica se o número está ativo.
- **WhatsApp sem número isolado:** a URL `wa.me/NUMERO` é capturada, mas o número não é normalizado.

---

## Módulo de consolidação comercial (`consolidador_presenca.py`)

Unifica todos os sinais de presença digital em uma visão comercial única por empresa. Transforma dados brutos em oportunidade classificada, com solução específica e prioridade de oferta.

### O que é presença consolidada

É a fusão de:
- dados OSM (telefone, email, website, instagram)
- análise do website (score_presenca_web, site acessível, CTA)
- canais enriquecidos (confianca_*, *_confirmado)

...em campos comercialmente úteis: score, classificação, gargalo, oportunidade, solução.

### Score de presença consolidado (`score_presenca_consolidado`, 0-100)

Mede a qualidade do perfil digital como base para proposta comercial — quanto sabemos sobre a empresa e como isso sustenta uma oferta.

| Componente | Peso máximo |
|---|---|
| Empresa identificável (não `pouco_util`) | 15 |
| Website confirmado (alta=15, media=10, baixa=4) | 15 |
| Telefone confirmado (alta=12, media=8, baixa=4) | 12 |
| WhatsApp confirmado (media=8, baixa=4) | 12 |
| E-mail confirmado (alta=10, media=7, baixa=3) | 10 |
| Instagram confirmado (alta=8, media=6, baixa=2) | 8 |
| Facebook confirmado (media=4, baixa=2) | 5 |
| Site acessível | 8 |
| Qualidade da presença web (score_presenca_web / 100 × 15) | 15 |
| **Total** | **100** |

### Classificação comercial de presença

| Classificação | Quando se aplica | Prioridade |
|---|---|---|
| `oportunidade_alta_presenca` | Empresa identificável + canal de contato confirmado + presença fraca/básica ou sem website + score ≥ 25 | Alta |
| `oportunidade_media_presenca` | Empresa com canais parcialmente identificados mas perfil incompleto + score ≥ 20 | Média |
| `oportunidade_baixa_presenca` | Empresa com canais mas presença boa ou lacuna pequena | Baixa |
| `pouca_utilidade_presenca` | Empresa não identificável (`pouco_util`) ou sem canais digitais + score < 15 | Nula |

**Regra principal:** para ser `oportunidade_alta`, a empresa precisa ter um canal de contato direto confirmado (telefone ou e-mail com confiança `alta` ou `media`) — sem isso, não é possível sustentar uma proposta comercial ativa.

### Gap principal e solução

O gap é detectado em ordem de prioridade:

| Gap | Gargalo | Solução base |
|---|---|---|
| `dados_insuficientes` | Empresa sem identificação | Pesquisa e mapeamento |
| `sem_canais` | Sem canais digitais identificados | Criação de perfil básico |
| `sem_website` | Sem website próprio | Landing page por categoria |
| `site_inacessivel` | Site não responde | Recuperação e monitoramento |
| `sem_whatsapp` | Sem WhatsApp no site | Botão WhatsApp integrado |
| `sem_cta` | Site sem chamada para ação | Botões de conversão |
| `sem_email` | Sem e-mail público | E-mail profissional + formulário |
| `sem_https` | Site sem HTTPS | Migração SSL |
| `sem_instagram` | Sem Instagram | Criação e gestão de perfil |
| `sem_facebook` | Sem Facebook | Página integrada ao site |
| `presenca_estruturada` | Tudo razoavelmente presente | SEO local |

A solução recomendada (`solucao_recomendada_presenca`) é adaptada à categoria da empresa (barbearia, oficina, padaria, etc.).

### Campos gerados por empresa

| Campo | Tipo | Descrição |
|---|---|---|
| `score_presenca_consolidado` | int | Score 0-100 |
| `classificacao_presenca_comercial` | str | Nível de oportunidade |
| `pronta_para_oferta_presenca` | bool | Tem canal e classificação favorável para proposta |
| `principal_gargalo_presenca` | str | Texto do gargalo principal |
| `oportunidade_presenca_principal` | str | O que pode ser melhorado/vendido |
| `solucao_recomendada_presenca` | str | Solução específica por categoria |
| `prioridade_oferta_presenca` | str | alta / media / baixa / nula |
| `motivo_prioridade_presenca` | str | Por que esta prioridade |

### `fila_oportunidades_marketing.json`

Arquivo fixo (sobrescrito a cada execução) com empresas `oportunidade_alta_presenca` e `oportunidade_media_presenca`.

Ordenação:
1. `prioridade_oferta_presenca` (alta → media)
2. `score_presenca_consolidado` decrescente
3. `score_prontidao_ia` decrescente

### `candidatas_com_presenca_consolidada.json`

Arquivo timestamped (por execução) com todas as empresas após consolidação — incluindo todos os campos de todas as etapas. Serve como base de histórico da linha de presença digital.

---

## Módulo de planejamento de marketing (`planejador_marketing.py`)

Transforma a oportunidade detectada pelo consolidador em um plano prático de execução e em uma proposta de serviço legível para uso interno.

Este módulo **NÃO** executa nada — apenas planeja. Não envia mensagens, não faz anúncios, não contrata serviços.

### O que este módulo faz

Para cada empresa com oportunidade identificada, gera:

| Campo | Descrição |
|---|---|
| `resumo_oportunidade_marketing` | Situação atual em 1-2 frases — o que a empresa tem e o que falta |
| `gargalo_principal_marketing` | Descrição concreta do problema que bloqueia o resultado |
| `objetivo_principal_marketing` | O que se quer alcançar com a solução |
| `solucao_recomendada_marketing` | O que construir ou configurar, adaptado à categoria |
| `quick_wins_marketing` | 2-3 ações de resultado rápido, em texto livre |
| `plano_30_dias_marketing` | Roteiro semanal de execução em 4 etapas |
| `entregaveis_sugeridos_marketing` | Lista do que será entregue ao final da execução |
| `nivel_complexidade_execucao` | baixa / media / alta — indica esforço de execução |
| `impacto_esperado` | O que muda para a empresa após a execução |
| `prioridade_execucao_marketing` | alta / media / baixa / sem_dados |
| `observacoes_execucao_marketing` | Ressalvas sobre qualidade dos dados e limitações |
| `proposta_resumida_marketing` | Brief interno de 3-5 frases para entender o que oferecer |
| `plano_marketing_gerado` | bool — False para empresas sem oportunidade identificada |

### O que este módulo NÃO faz

- Não valida se os dados do OSM estão atualizados
- Não analisa concorrência ou mercado
- Não gera mensagens de abordagem ao cliente
- Não decide preço ou forma de entrega do serviço
- Não executa nenhuma das ações planejadas

### Como interpretar o plano e a proposta

**`proposta_resumida_marketing`** é um brief interno — serve para entender o que vender, não para enviar ao cliente. Leia como: situação atual → gargalo → solução sugerida → complexidade → disponibilidade de contato.

**`plano_30_dias_marketing`** é uma sugestão de roteiro, não um contrato. Cada semana representa uma fase de execução. O prazo real depende de negociação com o cliente e disponibilidade do time.

**`nivel_complexidade_execucao`**:
- `baixa` — execução em dias (ex: adicionar botão de WhatsApp, instalar HTTPS)
- `media` — execução em semanas (ex: criar site simples, recuperar site fora do ar)
- `alta` — exige pesquisa antes da execução (ex: empresa sem dados suficientes)

**Diferença entre oportunidade e execução**: identificar a oportunidade (o que o consolidador faz) é diferente de ter capacidade de executar. A `fila_propostas_marketing` ordena por viabilidade — empresas com solução clara, dados disponíveis e complexidade baixa ou média aparecem primeiro.

### Lógica de prioridade de execução

| Condição | Prioridade |
|---|---|
| oportunidade_alta + contato confirmado (alta/media) + complexidade baixa/media | alta |
| oportunidade_alta ou media + contato confirmado + complexidade baixa | alta |
| oportunidade_media + contato confirmado | media |
| sem contato direto identificado | sem_dados |

### Arquivos gerados

| Arquivo | O que contém |
|---|---|
| `candidatas_com_plano_marketing.json` | Timestamped — todas as empresas analisadas, incluindo campos de plano |
| `fila_propostas_marketing_TIMESTAMP.json` | Timestamped — empresas com plano gerado e viabilidade de execução |
| `fila_propostas_marketing.json` | Fixo (latest) — mesma fila, sobrescrito a cada execução |

### Critérios da fila de propostas

Inclusão: plano gerado + classificação alta ou media + complexidade baixa ou media.

Ordenação:
1. `classificacao_presenca_comercial` (alta → media)
2. `prioridade_execucao_marketing` (alta → media → baixa)
3. `nivel_complexidade_execucao` (baixa primeiro — execução mais fácil)
4. `score_presenca_consolidado` decrescente
