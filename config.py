"""
config.py — Configuração centralizada do sistema.

Todos os parâmetros ajustáveis ficam aqui.
Nenhum outro arquivo deve conter valores fixos de configuração.

Seções:
  [COMPARTILHADO]  Infraestrutura, rede, OSM — usada por ambas as linhas.
  [OPERACIONAL]    Linha local: prospecção, abordagem, histórico.
  [MARKETING]      Linha nacional por nicho: presença digital em escala.
"""

from pathlib import Path

# Diretório raiz do projeto
BASE_DIR = Path(__file__).parent

# Pastas de saída
PASTA_DADOS = BASE_DIR / "dados"
PASTA_LOGS = BASE_DIR / "logs"

# ============================================================
# [COMPARTILHADO] — Tags OSM e infraestrutura de rede
# Usado por ambas as linhas: operacional e marketing.
# ============================================================

# Mapeamento de categorias para tags OSM.
# Formato: identificador → lista de dicts {chave_osm: valor_osm}
# Para adicionar uma categoria nova: basta adicionar um item aqui.
CATEGORIAS = {
    "barbearia": [{"shop": "barber"}],
    "salao_de_beleza": [{"shop": "beauty"}, {"shop": "hairdresser"}],
    "oficina_mecanica": [{"shop": "car_repair"}],
    "borracharia": [{"shop": "tyres"}],
    "acougue": [{"shop": "butcher"}],
    "padaria": [{"shop": "bakery"}],
    "autopecas": [{"shop": "car_parts"}],
}

# Nomes amigáveis para exibição nos resultados
NOMES_CATEGORIAS = {
    "barbearia": "Barbearia",
    "salao_de_beleza": "Salão de Beleza",
    "oficina_mecanica": "Oficina Mecânica",
    "borracharia": "Borracharia / Loja de Pneus",
    "acougue": "Açougue",
    "padaria": "Padaria",
    "autopecas": "Autopeças",
}

# Instâncias públicas da Overpass API — gratuitas, sem chave de API.
# O sistema tenta a primeira; se receber 429 repetido, tenta a próxima.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Pausa entre requisições à Overpass API (segundos) — respeita rate limiting
PAUSA_ENTRE_REQUISICOES = 6

# Pausa extra após receber HTTP 429 (Too Many Requests).
# Precisa ser bem maior que a pausa normal para a API se recuperar.
PAUSA_RATE_LIMIT = 35

# Timeout para requisições HTTP (segundos)
TIMEOUT_REQUISICAO = 45

# Número máximo de tentativas por requisição em caso de falha
MAX_TENTATIVAS = 4

# ============================================================
# [OPERACIONAL] — Linha local: prospecção ativa em uma cidade
# Usada apenas por main.py / core/executor.py
# ============================================================

# Cidade alvo da prospecção operacional
CIDADE = "São José do Rio Preto"
PAIS = "Brazil"  # em inglês para o Nominatim

# Score mínimo para ser considerada candidata
# Quanto menor, menos presença digital foi encontrada nos dados públicos.
LIMITE_SCORE_CANDIDATA = 40

# ============================================================
# [MARKETING] — Linha nacional por nicho: análise de presença digital em escala
# Usada apenas por main_marketing.py / core/executor_marketing.py
# Não inclui abordagem, histórico nem envio de mensagens.
# ============================================================

# Cidades a processar na linha de marketing.
# Adicione ou remova cidades conforme a estratégia de expansão.
CIDADES_MARKETING = [
    "São José do Rio Preto",
    # Exemplos prontos para habilitar:
    # "Ribeirão Preto",
    # "Bauru",
    # "São José dos Campos",
    # "Sorocaba",
]

# Estado inferido por cidade.
# Usado para enriquecer o contexto geográfico na saída.
# Adicione aqui ao incluir novas cidades acima.
ESTADO_POR_CIDADE = {
    "São José do Rio Preto": "SP",
    "Ribeirão Preto": "SP",
    "Bauru": "SP",
    "São José dos Campos": "SP",
    "Sorocaba": "SP",
    "Campinas": "SP",
    "Santos": "SP",
    "Curitiba": "PR",
    "Londrina": "PR",
    "Maringá": "PR",
    "Porto Alegre": "RS",
    "Caxias do Sul": "RS",
    "Florianópolis": "SC",
    "Joinville": "SC",
    "Belo Horizonte": "MG",
    "Uberlândia": "MG",
    "Goiânia": "GO",
    "Brasília": "DF",
    "Salvador": "BA",
    "Fortaleza": "CE",
    "Recife": "PE",
    "Manaus": "AM",
}

# Nichos a processar na linha de marketing.
# Cada nicho é um subconjunto de CATEGORIAS — deve usar os mesmos identificadores.
# Deixe vazio para processar todas as categorias disponíveis em CATEGORIAS.
NICHOS_MARKETING = [
    "barbearia",
    "oficina_mecanica",
    # "salao_de_beleza",
    # "borracharia",
    # "acougue",
    # "padaria",
    # "autopecas",
]

# Limite de empresas aceitas por combinação cidade + nicho.
# Evita sobrecarga em cidades grandes com muitos resultados OSM.
LIMITE_EMPRESAS_POR_CIDADE_NICHO = 100

# Pausa em segundos entre o processamento de cada cidade.
# Respeita o rate limiting da Overpass API em execuções longas.
PAUSA_ENTRE_CIDADES = 5

# ============================================================
# [FINANCEIRO] — Linha financeira interna
# Usada apenas por main_financeiro.py / modulos/financeiro/
# ============================================================

# Valor mínimo (R$) para considerar um atraso ou despesa como relevante.
# Acima deste valor → pode gerar decisão humana.
FINANCEIRO_VALOR_RELEVANTE = 500.0

# Saldo previsto abaixo deste valor dispara risco_caixa = True.
# Zero significa que caixa negativo já é risco.
FINANCEIRO_THRESHOLD_RISCO = 0.0

# Vencimento em até N dias → urgência "imediata"
FINANCEIRO_DIAS_ALERTA_IMEDIATO = 2

# Vencimento em até N dias → urgência "curto_prazo"
FINANCEIRO_DIAS_ALERTA_CURTO_PRAZO = 7
