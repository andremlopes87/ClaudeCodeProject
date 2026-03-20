# Plataforma de Agentes — v0.6

Agente de prospecção que encontra empresas com oportunidade de melhoria digital
em São José do Rio Preto, usando dados públicos e gratuitos do OpenStreetMap.

---

## O que este sistema faz

1. Busca estabelecimentos comerciais por categoria (barbearia, oficina, padaria etc.)
2. Analisa sinais de presença digital nos dados públicos (site, telefone, horário, e-mail, Instagram)
3. Calcula dois scores: presença digital e prontidão para abordagem comercial
4. Classifica cada empresa comercialmente
5. Avalia se há canal prático de contato disponível
6. Gera pacote de abordagem pronto por empresa: mensagens, orientações e tom recomendado
7. Mantém histórico acumulado entre execuções, detecta mudanças e atualiza fila de revisão
8. **Analisa a presença digital real** das empresas com website: verifica se o site responde, identifica telefone, WhatsApp, Instagram, Facebook, CTA e HTTPS no HTML público
9. Salva os resultados em 6 arquivos por execução + 4 arquivos persistentes

**Custo:** zero. Usa apenas APIs públicas e gratuitas (OpenStreetMap, Nominatim, Overpass, HTTP direto).

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

Cada execução gera 6 arquivos em `dados/` com timestamp. A lógica de cada um é:

| Arquivo | O que contém | Para que serve |
|---|---|---|
| `todas.json` | Todas as empresas encontradas, sem filtro | Referência completa e auditoria |
| `candidatas_brutas.json` | Todas exceto `pouco_util` (têm nome identificado) | Revisão manual sem filtro de abordagem |
| `candidatas_priorizadas.json` | `semi_digital` + `analogica`, ordenadas por prioridade | Lista de trabalho principal |
| `candidatas_abordaveis.json` | Não `pouco_util` + têm canal direto de contato | Ação imediata — quem pode ser contatado agora |
| `candidatas_com_abordagem.json` | Abordáveis + pacote de mensagens e orientações prontas | **Arquivo de uso direto** — abrir, ler e ligar/enviar |
| `candidatas_com_diagnostico_web.json` | Empresas com website + análise completa de presença digital | Auditoria de sites e diagnóstico web |

### O que cada arquivo exclui

- `candidatas_brutas` exclui: `pouco_util` (sem nome = sem como abordar)
- `candidatas_priorizadas` exclui: `pouco_util` + `digital_basica` (pouco oportunidade)
- `candidatas_abordaveis` exclui: `pouco_util` + empresas sem telefone ou e-mail identificado
- `candidatas_com_abordagem` é o mesmo conjunto de `candidatas_abordaveis`, com campos de abordagem adicionados

### Arquivos persistentes (nome fixo — sobrescritos a cada execução)

| Arquivo | O que contém | Para que serve |
|---|---|---|
| `prospeccao_historico.json` | Todas as empresas já encontradas, com histórico e status interno | Memória acumulada da prospecção |
| `fila_revisao.json` | Leads prioritários filtrados e ordenados por relevância | **Arquivo principal de trabalho** — abrir aqui primeiro |
| `prospeccao_resumo_execucao.json` | Estatísticas e mudanças detectadas nesta execução | Auditoria e acompanhamento de evolução |
| `fila_oportunidades_presenca.json` | Empresas com site acessível + presença digital fraca/básica | Oportunidades de melhoria de marketing digital |

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

## Histórico e memória de prospecção

O sistema mantém um registro acumulado de todas as empresas já encontradas em `prospeccao_historico.json`. A cada execução, este arquivo é atualizado com os dados mais recentes.

### O que é rastreado por empresa

Cada entrada no histórico contém:
- Identificador estável (`empresa_id`) baseado no OSM ID — não muda entre execuções
- Data da primeira e da última aparição, e quantas vezes foi encontrada
- Classificação comercial e prioridade atuais
- Abordabilidade e canal de contato identificado
- **Status interno**: estado atual na jornada de prospecção
- **Mudanças detectadas**: o que mudou nesta execução em relação à anterior

### Status interno

| Status | Significado |
|---|---|
| `novo` | Apareceu pela primeira vez nesta execução. Ainda não consolidada. |
| `pronto_para_abordagem` | Tem canal de contato direto e perfil comercial adequado. Não é novo. |
| `revisar` | Mudança relevante detectada (ganhou/perdeu contato, classificação mudou) ou empresa sumiu entre execuções. |
| `baixa_prioridade` | Pouco urgente: digital_basica, sem contato, ou sem mudanças relevantes. |
| `descartar` | Dados insuficientes para abordagem comercial (`pouco_util`). |

### Detecção de mudanças entre execuções

O sistema detecta automaticamente quando uma empresa:
- Apareceu pela primeira vez (`nova_empresa`)
- Não foi encontrada nesta execução (`empresa_sumiu`)
- Mudou de classificação comercial (`classificacao_mudou`)
- Mudou de prioridade (`prioridade_mudou`)
- Ganhou canal de contato direto (`ganhou_contato`)
- Perdeu canal de contato direto (`perdeu_contato`)
- Mudou de canal (`canal_mudou`)

### Fila de revisão (`fila_revisao.json`)

Arquivo gerado a cada execução com os leads mais relevantes, na seguinte ordem:
1. **Novos** com boa classificação (semi_digital ou analogica)
2. **Prontos para abordagem** (abordáveis e priorizados, não novos)
3. **Revisar** (mudanças detectadas ou empresa sumiu)

Baixa prioridade e descartar ficam fora da fila.

---

## Pacote de abordagem (`candidatas_com_abordagem.json`)

Cada empresa no arquivo final recebe campos prontos para uso direto:

| Campo | Descrição |
|---|---|
| `resumo_empresa` | Resumo objetivo com nome, categoria e sinais identificados |
| `oportunidade_principal` | Oportunidade comercial específica da categoria |
| `motivo_abordagem` | Por que esta empresa é um bom alvo agora |
| `canal_abordagem_recomendado` | Canal sugerido: `telefone` ou `email` |
| `mensagem_inicial_curta` | Telefone: abertura de conversa (20-35 palavras) / E-mail: assunto |
| `mensagem_inicial_media` | Telefone: script completo / E-mail: corpo do e-mail |
| `followup_curto` | Mensagem de follow-up caso não haja resposta |
| `observacoes_abordagem` | Dicas práticas para quem vai fazer o contato |
| `risco_abordagem` | Riscos identificados com os dados disponíveis |
| `tom_recomendado` | Tom sugerido adaptado ao canal e perfil da empresa |

**Regras de tom:** profissional, direto, sem buzzwords. Nada de "IA revolucionária" ou "transformação digital". Foco no problema concreto do negócio (ex: "clientes esquecem horário", "orçamento demora a sair").

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

## Módulo de presença digital

Analisa o website público das empresas com site registrado nos dados do OpenStreetMap.

### O que este módulo mede

| Sinal | Método |
|---|---|
| Site responde (HTTP 2xx) | HEAD → GET com timeout curto |
| Usa HTTPS | Prefixo da URL |
| Telefone no site | `href="tel:"` + regex no texto |
| E-mail no site | `href="mailto:"` + regex no texto |
| Link para WhatsApp | `href` com `wa.me` ou `api.whatsapp.com` |
| Link para Instagram | `href` com `instagram.com` |
| Link para Facebook | `href` com `facebook.com` |
| Chamada clara para ação | Texto de botões/links + palavras-chave no `href` |

### O que este módulo NÃO mede

- Conteúdo carregado via JavaScript (React, Vue, Angular etc.)
- Anúncios pagos (Google Ads, Meta Ads)
- SEO, métricas de tráfego ou conversão
- Subpáginas — apenas a homepage é analisada
- Redes sociais além dos links encontrados no site

### Classificação de presença web

| Classificação | Score | Significado |
|---|---|---|
| `presenca_boa` | 76–100 | Site completo e organizado |
| `presenca_razoavel` | 56–75 | Bem estruturado, falta pouco |
| `presenca_basica` | 36–55 | Tem 1–2 elementos de contato |
| `presenca_fraca` | 20–35 | Site acessível, sem contato ou CTA |
| `dados_insuficientes` | 0 | Site inacessível ou sem website |

### Limitações

- Apenas empresas com website registrado no OSM são analisadas
- Ausência de sinal não garante que o elemento não existe no site (pode estar em JavaScript)
- Disponibilidade do site pode variar entre execuções

Para detalhes das heurísticas: [docs/presenca_digital/heuristicas.md](docs/presenca_digital/heuristicas.md)

---

## Como rodar os testes

```bash
python tests/prospeccao_operacional/test_analisador.py
python tests/prospeccao_operacional/test_priorizador.py
python tests/prospeccao_operacional/test_abordabilidade.py
python tests/prospeccao_operacional/test_buscador.py
python tests/prospeccao_operacional/test_abordagem.py
python tests/prospeccao_operacional/test_historico.py
python tests/core/test_persistencia.py
python tests/presenca_digital/test_analisador_web.py
python tests/presenca_digital/test_diagnosticador_presenca.py
```

---

## Estrutura do projeto

```
modulos/
  prospeccao_operacional/   Linha de solução: prospecção operacional
    buscador.py             Busca por categoria, remove duplicatas
    analisador.py           score_presenca_digital, detecção de Instagram
    priorizador.py          score_prontidao_ia, classificacao_comercial
    abordabilidade.py       abordavel_agora, canal_abordagem_sugerido
    diagnosticador.py       Texto de diagnóstico por empresa
    abordagem.py            Pacote de abordagem: mensagens e orientações por empresa
    historico.py            Memória persistente: histórico, mudanças, status interno, fila de revisão

  presenca_digital/         Linha de solução: análise de presença digital via website
    analisador_web.py       Verificação HTTP, extração de sinais do HTML (HEAD → GET)
    diagnosticador_presenca.py  score_presenca_web, classificacao_presenca_web, diagnóstico e oportunidade

conectores/
  overpass.py               Conector OpenStreetMap (substituível)

core/
  executor.py               Orquestra o fluxo completo de prospecção
  persistencia.py           Único ponto de leitura/escrita de dados

docs/
  prospeccao_operacional/
    heuristicas.md          Documentação das regras de análise da prospecção
  presenca_digital/
    heuristicas.md          Sinais e regras planejados para a próxima etapa

tests/
  prospeccao_operacional/   Testes da linha de prospecção (60 casos)
  presenca_digital/         Testes do módulo de presença digital (37 casos)
  core/                     Testes do núcleo (5 casos)

config.py                   Configuração centralizada
main.py                     Ponto de entrada
```

---

## Limitações

- Dados dependem da qualidade do OpenStreetMap na cidade
- Instagram detectado apenas se cadastrado no OSM ou se website é instagram.com
- Sem integração com Google Maps, redes sociais ou aplicativos de entrega
- Abordabilidade baseada em dados públicos — empresa pode ter contato não registrado

Para detalhes das heurísticas de prospecção: [docs/prospeccao_operacional/heuristicas.md](docs/prospeccao_operacional/heuristicas.md)

Para detalhes das heurísticas de presença digital: [docs/presenca_digital/heuristicas.md](docs/presenca_digital/heuristicas.md)
