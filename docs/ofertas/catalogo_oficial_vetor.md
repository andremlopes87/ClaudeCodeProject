# Catálogo Oficial de Ofertas — Vetor

**Versão:** v1.0
**Data:** 2026-03-23
**Empresa:** Vetor Operações Ltda

---

## Visão Geral

A Vetor opera com um catálogo estruturado de 4 famílias de ofertas, cada uma com 2 a 3 pacotes (essencial/padrão/avançado). O catálogo é a fonte única de verdade para agentes comerciais, avaliadores de fechamento e operação de entrega.

---

## Famílias de Ofertas

### 1. Diagnóstico de Presença Digital
**ID:** `diagnostico_presenca_digital`
**Linha:** `marketing_presenca_digital`

Mapeamento completo da presença digital: site, redes sociais, Google Business, atendimento online e gaps prioritários.

| Pacote | ID | Valor | Prazo |
|--------|----|-------|-------|
| Essencial | `dpd_essencial` | R$ 890 | 7 dias |
| Padrão | `dpd_padrao` | R$ 1.890 | 14 dias |
| Avançado | `dpd_avancado` | R$ 3.490 | 21 dias |

---

### 2. Operação Comercial Base
**ID:** `operacao_comercial_base`
**Linha:** `automacao_atendimento`

Estruturação do processo comercial: atendimento por WhatsApp, qualificação de leads, follow-up e pipeline básico.

| Pacote | ID | Valor | Prazo |
|--------|----|-------|-------|
| Essencial | `ocb_essencial` | R$ 1.290 | 10 dias |
| Padrão | `ocb_padrao` | R$ 2.490 | 21 dias |
| Avançado | `ocb_avancado` | R$ 4.490 | 30 dias |

> Exige escopo confirmado antes de promover a ganho.

---

### 3. Estruturação Financeira Operacional
**ID:** `estruturacao_financeira_operacional`
**Linha:** `gestao_financeira`

Organização do fluxo de caixa, DRE simplificado, controle de contas a pagar/receber.

| Pacote | ID | Valor | Prazo |
|--------|----|-------|-------|
| Essencial | `efo_essencial` | R$ 990 | 7 dias |
| Padrão | `efo_padrao` | R$ 2.190 | 21 dias |
| Avançado | `efo_avancado` | R$ 3.990 | 30 dias |

> Exige escopo confirmado antes de promover a ganho.

---

### 4. Acompanhamento de Implantação
**ID:** `acompanhamento_implantacao_operacional`
**Linha:** `gestao_comercial`

Suporte contínuo pós-implantação. Complementar às demais ofertas.

| Pacote | ID | Valor | Ciclo |
|--------|----|-------|-------|
| Mensal | `aio_mensal` | R$ 590 | 30 dias |
| Trimestral | `aio_trimestral` | R$ 1.490 | 90 dias |

---

## Regras Comerciais

- Desconto máximo sem aprovação: **15%** (varia por oferta)
- Valor acima de **R$ 5.000** exige deliberação do conselho
- Customização fora do catálogo exige deliberação
- Parcelamento disponível em Operação Comercial e Financeiro (até 3×)

---

## Seleção Automática de Pacote

O agente comercial sugere o pacote com base em:
- `prioridade=alta` + `score_qualificacao >= 6` → pacote **Avançado**
- `prioridade=alta` OU `score >= 3` → pacote **Padrão**
- Demais casos → pacote **Essencial**

---

## Arquivos do Sistema

| Arquivo | Descrição |
|---------|-----------|
| `dados/catalogo_ofertas.json` | Catálogo completo com pacotes e checklists |
| `dados/regras_comerciais_ofertas.json` | Regras de desconto, parcelamento, deliberação |
| `dados/templates_proposta.json` | Templates de proposta por linha de serviço |
| `dados/historico_ofertas_empresa.json` | Histórico de decisões de oferta |
| `core/ofertas_empresa.py` | Lógica central de ofertas |

*Catálogo gerado em 2026-03-23 — atualizar ao adicionar ou modificar ofertas*
