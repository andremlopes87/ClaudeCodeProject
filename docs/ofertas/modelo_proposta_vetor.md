# Modelo de Proposta Comercial — Vetor

**Versão:** v1.0
**Data:** 2026-03-23

---

## Conceito

A proposta comercial da Vetor é o objeto formal que liga:
```
Oportunidade → Proposta → Fechamento → Entrega
```

Sem proposta formal, não há escopo oficial. Sem escopo oficial, não há entrega estruturada.

---

## Campos da Proposta

| Campo | Descrição |
|-------|-----------|
| `id` | Identificador único `prop_XXXXXXXX` |
| `oportunidade_id` | Vinculada ao pipeline comercial |
| `contraparte` | Nome da empresa cliente |
| `oferta_id` / `pacote_id` | Oferta e pacote do catálogo |
| `resumo_problema` | Contexto do cliente que justifica a proposta |
| `escopo` | Descrição do que será entregue |
| `entregaveis` | Lista de itens entregues |
| `checklist_execucao` | Checklist interno de execução |
| `premissas` | O que a Vetor assume do cliente |
| `fora_do_escopo` | O que não está incluído |
| `proposta_valor` | Valor de referência (R$) |
| `prazo_referencia` | Prazo em dias úteis |
| `status` | Estado atual da proposta |
| `requer_deliberacao` | Exige aprovação do conselho |
| `motivo_deliberacao` | Por que foi escalada |

---

## Fluxo de Status

```
rascunho
  ↓
pronta_para_revisao    ← gerada automaticamente quando oferta está clara
  ↓
aguardando_conselho    ← customização alta, valor acima do teto (R$5.000), escopo ambíguo
  ↓
aprovada_para_envio    ← conselho aprovou via painel
  ↓
enviada                ← registrada como enviada ao cliente
  ↓
aceita                 ← aceite registrado (manual, comercial, ou cliente)
  ↓
rejeitada / arquivada  ← encerrada sem aceite
```

---

## Geração Automática

Propostas são geradas pelo `agente_comercial` na **ETAPA 8b** de cada ciclo:
- A oportunidade precisa ter `oferta_id` definida (via catálogo)
- Não pode ter proposta ativa ainda
- Não pode estar em estágio final (ganho/perdido/encerrado)

---

## Deliberação Automática

Uma proposta vai para `aguardando_conselho` automaticamente se:
1. `grau_customizacao == "alta"` (sinais fora do padrão)
2. `valor_proposta > R$5.000`
3. Entregáveis não definidos (escopo ambíguo)

---

## Impacto no Fechamento

O avaliador de fechamento usa sinais de proposta:

| Sinal | Pontos adicionados |
|-------|--------------------|
| `proposta_gerada` | +2 |
| `proposta_aprovada` | +3 |
| `proposta_aceita` | +4 |

---

## Impacto na Entrega

Quando `agente_operacao_entrega` abre uma entrega:
1. Busca proposta `aprovada_para_envio`, `enviada` ou `aceita` para a oportunidade
2. Se encontrada → usa escopo, oferta e pacote da proposta como origem oficial
3. `entrega.origem_escopo = "proposta_aprovada"` vs `"oferta_catalogo"`
4. Checklist gerado com base no pacote da proposta

---

## Arquivos

| Arquivo | Descrição |
|---------|-----------|
| `dados/propostas_comerciais.json` | Lista de todas as propostas |
| `dados/historico_propostas_comerciais.json` | Eventos auditáveis por proposta |
| `dados/aceites_propostas.json` | Registro formal de aceites |
| `core/propostas_empresa.py` | Lógica central |
| `docs/ofertas/catalogo_oficial_vetor.md` | Catálogo de ofertas e pacotes |

*Modelo gerado em 2026-03-23*
