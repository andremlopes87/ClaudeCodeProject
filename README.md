# Plataforma de Agentes — v0.1

Agente de prospecção que encontra empresas com indícios de baixa presença digital
em São José do Rio Preto, usando dados públicos e gratuitos do OpenStreetMap.

---

## O que este sistema faz

1. Busca automaticamente estabelecimentos comerciais por categoria (barbearia, oficina, padaria etc.)
2. Analisa sinais básicos de presença digital nos dados públicos (site, telefone, horário, e-mail)
3. Gera um score e um diagnóstico textual com linguagem cuidadosa
4. Salva os resultados em arquivos JSON na pasta `dados/`
5. Registra logs de execução na pasta `logs/`

**Custo:** zero. Usa apenas APIs públicas e gratuitas.

---

## Pré-requisitos

- Python 3.9 ou superior
- Conexão com a internet

---

## Instalação

```bash
# 1. Clone o repositório
git clone https://github.com/andremlopes87/ClaudeCodeProject.git
cd ClaudeCodeProject

# 2. (Opcional, recomendado) Crie um ambiente virtual
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate  # Mac/Linux

# 3. Instale as dependências
pip install -r requirements.txt
```

---

## Como rodar

```bash
python main.py
```

O sistema vai rodar automaticamente e exibir o progresso no terminal.
Ao final, um resumo como este aparece:

```
==================================================
PROSPECÇÃO CONCLUÍDA
==================================================
Empresas encontradas : 47
Candidatas           : 31
Resultados salvos em : dados/
Duração              : 58s
==================================================
```

---

## Onde ficam os resultados

| Arquivo | Conteúdo |
|---|---|
| `dados/resultado_YYYY-MM-DD_HH-MM_todas.json` | Todas as empresas encontradas |
| `dados/resultado_YYYY-MM-DD_HH-MM_candidatas.json` | Apenas as candidatas (score baixo) |
| `logs/execucao_YYYY-MM-DD_HH-MM.log` | Log detalhado da execução |

---

## Como configurar

Edite `config.py` para ajustar:

| Configuração | O que faz |
|---|---|
| `CIDADE` | Cidade de busca |
| `PAIS` | País (em inglês, para geocodificação) |
| `LIMITE_SCORE_CANDIDATA` | Score abaixo do qual a empresa é candidata (padrão: 40) |
| `CATEGORIAS` | Categorias de negócio a buscar (tags OSM) |
| `PAUSA_ENTRE_REQUISICOES` | Intervalo entre chamadas à API (segundos) |

---

## Como rodar os testes

```bash
python tests/test_analisador.py
python tests/test_persistencia.py
python tests/test_buscador.py
```

---

## Estrutura do projeto

```
ClaudeCodeProject/
├── agents/prospeccao/       # Agentes do fluxo de prospecção
│   ├── buscador.py          # Orquestra a busca por categoria
│   ├── analisador.py        # Calcula score de presença digital
│   └── diagnosticador.py    # Gera texto de diagnóstico
├── conectores/
│   └── overpass.py          # Conector com OpenStreetMap (substituível)
├── core/
│   ├── executor.py          # Orquestra o fluxo completo
│   └── persistencia.py      # Único ponto de leitura/escrita de dados
├── dados/                   # Resultados em JSON (gerado na execução)
├── docs/
│   └── heuristicas.md       # Documenta as regras de análise
├── logs/                    # Logs de execução
├── tests/                   # Testes automatizados
├── config.py                # Configuração centralizada
├── main.py                  # Ponto de entrada
└── requirements.txt
```

---

## Limitações desta versão

- Depende da qualidade dos dados do OpenStreetMap na cidade buscada
- Diagnóstico baseado apenas em dados públicos (sem verificação de redes sociais)
- Sem integração com Google Maps, Instagram ou WhatsApp Business
- Sem envio automático de mensagens
- Sem interface visual

Para detalhes completos sobre as heurísticas, veja [docs/heuristicas.md](docs/heuristicas.md).

---

## Próximos passos previstos

- Verificar presença em redes sociais
- Incluir mais cidades e regiões
- Gerar mensagem de abordagem personalizada
- Integrar com CRM simples para acompanhamento
