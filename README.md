# Plataforma de Agentes — v0.3

Agente de prospecção que encontra empresas com oportunidade de melhoria digital
em São José do Rio Preto, usando dados públicos e gratuitos do OpenStreetMap.

---

## O que este sistema faz

1. Busca estabelecimentos comerciais por categoria (barbearia, oficina, padaria etc.)
2. Analisa sinais de presença digital nos dados públicos (site, telefone, horário, e-mail, Instagram)
3. Calcula dois scores: presença digital e prontidão para abordagem comercial
4. Classifica cada empresa comercialmente
5. Avalia se há canal prático de contato disponível
6. Salva os resultados em 4 arquivos JSON organizados por utilidade

**Custo:** zero. Usa apenas APIs públicas e gratuitas (OpenStreetMap, Nominatim, Overpass).

---

## Instalação

```bash
pip install -r requirements.txt
```

## Como rodar

```bash
python main.py
```

---

## Arquivos de saída

Cada execução gera 4 arquivos em `dados/` com timestamp. A lógica de cada um é:

| Arquivo | O que contém | Para que serve |
|---|---|---|
| `todas.json` | Todas as empresas encontradas, sem filtro | Referência completa e auditoria |
| `candidatas_brutas.json` | Todas exceto `pouco_util` (têm nome identificado) | Revisão manual sem filtro de abordagem |
| `candidatas_priorizadas.json` | `semi_digital` + `analogica`, ordenadas por prioridade | Lista de trabalho principal |
| `candidatas_abordaveis.json` | Não `pouco_util` + têm canal direto de contato | Ação imediata — quem pode ser contatado agora |

### O que cada arquivo exclui

- `candidatas_brutas` exclui: `pouco_util` (sem nome = sem como abordar)
- `candidatas_priorizadas` exclui: `pouco_util` + `digital_basica` (pouco oportunidade)
- `candidatas_abordaveis` exclui: `pouco_util` + empresas sem telefone ou e-mail identificado

---

## Classificação comercial

Cada empresa recebe uma das 4 classificações:

| Classificação | Prioridade | Significado |
|---|---|---|
| `semi_digital_prioritaria` | Alta | Nome + pelo menos 1 sinal digital + lacunas claras. Melhor alvo. |
| `analogica` | Média | Nome identificado mas poucos dados. Abordável, mais difícil. |
| `digital_basica` | Baixa | Já relativamente organizada digitalmente. Menor oportunidade agora. |
| `pouco_util` | Nula | Sem nome ou dados insuficientes para abordagem prática. |

**Critérios do `score_presenca_digital` (0-100):**

| Sinal | Pontos |
|---|---|
| Site próprio | +40 |
| Telefone público | +30 |
| Horário de funcionamento | +20 |
| E-mail de contato | +10 |

**Nota:** Se o campo `website` for uma URL do Instagram, ele não conta como site próprio — é registrado em `tem_instagram` separadamente.

---

## Score de prontidão para IA (`score_prontidao_ia`)

Mede a oportunidade comercial de abordar a empresa (0-100):

| Condição | Pontos |
|---|---|
| Nome identificado | +25 (base obrigatória) |
| Tem telefone | +20 |
| Tem site próprio | +15 |
| Tem horário | +10 |
| Tem e-mail | +5 |
| Tem Instagram | +5 (bônus) |
| Score de presença >= 65 | -20 (já organizada) |

Sem nome: score = 0.

---

## Camada de abordabilidade

Determina se há canal prático de contato disponível **nos dados públicos**:

| Campo | Significado |
|---|---|
| `abordavel_agora` | True se tem telefone OU e-mail identificado |
| `canal_abordagem_sugerido` | telefone / email / website_contato_indireto / sem_canal_identificado |
| `contato_principal` | Dado concreto de contato (número, e-mail ou URL) |
| `tipo_contato_principal` | telefone / email / website / null |
| `motivo_nao_abordavel` | Explicação quando não é abordável |
| `tem_telefone_util` | Telefone disponível nos dados públicos |
| `tem_email_util` | E-mail disponível nos dados públicos |
| `tem_site_util` | Site próprio disponível (não conta URL do Instagram) |

**Regra:** Website sem telefone ou e-mail = canal indireto. A empresa **não** entra em `candidatas_abordaveis` apenas com website.

---

## Detecção de Instagram

Verificada em duas fontes já disponíveis, sem scraping e sem API paga:

1. Tags OSM diretas: `contact:instagram`, `instagram`, `social:instagram`
2. Campo `website` quando a URL aponta para `instagram.com`

**Importante:** Ausência de Instagram no resultado não significa que a empresa não tem perfil — apenas que não foi encontrado nos dados públicos.

---

## Ordenação de `candidatas_priorizadas` e `candidatas_abordaveis`

1. `prioridade_abordagem` (alta > media > baixa > nula)
2. `abordavel_agora` (True primeiro — empresa contatável sobe sobre não-contatável)
3. `score_prontidao_ia` (maior primeiro)
4. `campos_osm_preenchidos` (maior primeiro)

---

## Configuração

Edite `config.py` para ajustar:

| Parâmetro | Descrição |
|---|---|
| `CIDADE` | Cidade de busca |
| `CATEGORIAS` | Categorias OSM a buscar |
| `LIMITE_SCORE_CANDIDATA` | Threshold antigo (mantido por compatibilidade) |
| `PAUSA_ENTRE_REQUISICOES` | Intervalo entre chamadas (segundos) |
| `PAUSA_RATE_LIMIT` | Espera após HTTP 429 |

---

## Como rodar os testes

```bash
python tests/test_analisador.py
python tests/test_priorizador.py
python tests/test_abordabilidade.py
python tests/test_persistencia.py
python tests/test_buscador.py
```

---

## Estrutura do projeto

```
agents/prospeccao/
  buscador.py           Busca por categoria, remove duplicatas
  analisador.py         score_presenca_digital, detecção de Instagram
  priorizador.py        score_prontidao_ia, classificacao_comercial
  abordabilidade.py     abordavel_agora, canal_abordagem_sugerido
  diagnosticador.py     Texto de diagnóstico por empresa

conectores/
  overpass.py           Conector OpenStreetMap (substituível)

core/
  executor.py           Orquestra o fluxo completo
  persistencia.py       Único ponto de leitura/escrita de dados

docs/
  heuristicas.md        Documentação das regras de análise

tests/                  Testes automatizados (35 casos)
config.py               Configuração centralizada
main.py                 Ponto de entrada
```

---

## Limitações

- Dados dependem da qualidade do OpenStreetMap na cidade
- Instagram detectado apenas se cadastrado no OSM ou se website é instagram.com
- Sem integração com Google Maps, redes sociais ou aplicativos de entrega
- Abordabilidade baseada em dados públicos — empresa pode ter contato não registrado

Para detalhes das heurísticas: [docs/heuristicas.md](docs/heuristicas.md)
