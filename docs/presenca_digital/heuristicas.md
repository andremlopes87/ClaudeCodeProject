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

### Critérios da fila de oportunidades de presença

Inclusão: site acessível + classificação `presenca_fraca`, `presenca_basica` ou `presenca_razoavel` + não é `pouco_util`.

Ordenação:
1. `classificacao_presenca_web` (fraca → básica → razoável)
2. `score_presenca_web` crescente (menos estruturado primeiro)
3. `score_prontidao_ia` decrescente (mais prioritária comercialmente)
