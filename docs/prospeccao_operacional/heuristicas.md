# Heurísticas de Análise de Presença Digital

Este documento descreve as regras usadas para calcular o score de presença digital
de cada empresa encontrada. É a referência principal para entender e ajustar os critérios.

---

## Fonte dos dados

Todos os dados desta versão vêm do **OpenStreetMap** via **Overpass API**.

Limitações importantes:
- O OSM é alimentado por colaboração voluntária. Muitos negócios não estão cadastrados.
- A ausência de um campo no OSM **não significa** que a empresa não tem aquele recurso.
- Esta análise é um **filtro de prioridade**, não um diagnóstico definitivo.
- Verificação manual é sempre recomendada antes de qualquer abordagem comercial.

---

## Score de presença digital

O score vai de **0 a 100**. Quanto menor o score, menos presença digital foi identificada
nos dados públicos. Isso torna a empresa uma candidata prioritária para abordagem.

| Sinal digital | Pontos | Justificativa |
|---|---|---|
| Tem `website` | +40 | Presença web própria é o sinal mais forte de digitalização |
| Tem `telefone` | +30 | Telefone público facilita atendimento e é básico para digitalização |
| Tem `horário de funcionamento` | +20 | Horário online indica gestão mínima de presença digital |
| Tem `e-mail de contato` | +10 | Canal digital secundário, menos comum em negócios físicos |

**Total máximo: 100 pontos**

---

## Classificação por score

| Score | Classificação | O que significa |
|---|---|---|
| 0–39 | Candidata prioritária | Poucos ou nenhum sinal de presença digital nos dados públicos |
| 40–69 | Presença parcial | Alguns sinais identificados, pode ainda haver oportunidades |
| 70–100 | Presença razoável | Dados públicos indicam presença digital mais estruturada |

O limite de 40 pode ser ajustado em `config.py` (variável `LIMITE_SCORE_CANDIDATA`).

---

## Nível de confiança do diagnóstico

Mede o quanto de dados o OSM tinha disponível para análise.
**Não mede a qualidade da presença digital da empresa.**

| Confiança | Campos preenchidos no OSM | O que significa |
|---|---|---|
| `baixa` | 0 campos | Quase nada disponível. Diagnóstico muito limitado. |
| `media` | 1–2 campos | Alguns dados disponíveis. Análise parcial. |
| `alta` | 3–4 campos | Mais dados disponíveis. Análise mais completa (ainda limitada ao OSM). |

---

## Categorias monitoradas (v0.1)

Escolhidas por serem negócios tipicamente locais, físicos e com menor tendência
de digitalização espontânea:

| Categoria | Tag OSM |
|---|---|
| Barbearia | `shop=barber` |
| Salão de Beleza | `shop=beauty`, `shop=hairdresser` |
| Oficina Mecânica | `shop=car_repair` |
| Borracharia / Loja de Pneus | `shop=tyres` |
| Açougue | `shop=butcher` |
| Padaria | `shop=bakery` |
| Autopeças | `shop=car_parts` |

Para adicionar novas categorias: edite `config.py` → `CATEGORIAS` e `NOMES_CATEGORIAS`.

---

## O que esta versão NÃO analisa (próximas evoluções)

- Presença em redes sociais (Instagram, Facebook, WhatsApp Business)
- Avaliações online (Google Maps, Reclame Aqui)
- Qualidade do site (se existe, se é responsivo, se tem e-commerce)
- Tempo de resposta a contatos
- Presença em aplicativos de delivery

---

## Linguagem do diagnóstico

O sistema usa linguagem cuidadosa intencionalmente. Preferimos:

✅ "indícios de baixa presença digital"
✅ "não identificado nos dados públicos"
✅ "verificação manual recomendada"

❌ "empresa não tem site"
❌ "negócio sem presença digital"
❌ "empresa desatualizada"

Isso evita conclusões incorretas baseadas em dados incompletos.
